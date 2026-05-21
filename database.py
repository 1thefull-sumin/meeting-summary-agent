from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

from failure_log import write_failure_log


ROOT_DIR = Path(__file__).resolve().parent
_LOGGED_CONFIG = False
_LOGGED_SERVER = False
PROCESS_STATUSES = {"pending", "done", "error", "skipped"}


def get_connection():
    config = _mysql_config()
    _ensure_database(config)
    conn = pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    with conn.cursor() as cursor:
        cursor.execute("SET time_zone = '+09:00'")
        _log_server_once(cursor)
    return conn


def _mysql_config() -> dict[str, Any]:
    load_dotenv(ROOT_DIR / ".env")
    database = os.getenv("MYSQL_DATABASE") or "MEETING_AGENT_DEV"
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise RuntimeError("MYSQL_DATABASE는 영문, 숫자, underscore만 사용할 수 있습니다.")

    config = {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": database,
    }
    _log_config_once(config)
    return config


def _log_config_once(config: dict[str, Any]) -> None:
    global _LOGGED_CONFIG
    if _LOGGED_CONFIG:
        return
    print(
        "[DB] MySQL 연결 대상: "
        f"{config['user']}@{config['host']}:{config['port']} / {config['database']}",
        flush=True,
    )
    _LOGGED_CONFIG = True


def _log_server_once(cursor) -> None:
    global _LOGGED_SERVER
    if _LOGGED_SERVER:
        return
    cursor.execute(
        """
        SELECT
            DATABASE() AS database_name,
            @@hostname AS hostname,
            @@port AS port,
            @@version AS version,
            @@socket AS socket_path,
            CURRENT_USER() AS current_user_name,
            CONNECTION_ID() AS connection_id
        """
    )
    row = cursor.fetchone()
    print(
        "[DB] MySQL 서버 확인: "
        f"database={row.get('database_name')} / "
        f"hostname={row.get('hostname')} / "
        f"port={row.get('port')} / "
        f"version={row.get('version')} / "
        f"user={row.get('current_user_name')} / "
        f"connection_id={row.get('connection_id')} / "
        f"socket={row.get('socket_path')}",
        flush=True,
    )
    _LOGGED_SERVER = True


def _ensure_database(config: dict[str, Any]) -> None:
    conn = pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET time_zone = '+09:00'")
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config['database']}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    file_hash VARCHAR(64) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    meeting_date DATE NOT NULL,
                    meeting_start_time CHAR(5) DEFAULT '',
                    meeting_end_time CHAR(5) DEFAULT '',
                    duration_seconds INT UNSIGNED NULL,
                    status ENUM('uploaded','pending','done','error','skipped','deleted') NOT NULL DEFAULT 'pending',
                    upload_status VARCHAR(30) DEFAULT '',
                    stt_status VARCHAR(30) DEFAULT '',
                    transcript_quality VARCHAR(30) DEFAULT '',
                    summary_status VARCHAR(30) DEFAULT '',
                    db_status VARCHAR(30) DEFAULT '',
                    last_error TEXT,
                    retry_count INT UNSIGNED NOT NULL DEFAULT 0,
                    summary MEDIUMTEXT,
                    decisions MEDIUMTEXT,
                    risks MEDIUMTEXT,
                    next_actions MEDIUMTEXT,
                    flow_message MEDIUMTEXT,
                    raw_text LONGTEXT,
                    markdown_path VARCHAR(500) DEFAULT '',
                    audio_path VARCHAR(500) DEFAULT '',
                    transcript_path VARCHAR(500) DEFAULT '',
                    source_type VARCHAR(50) DEFAULT 'txt',
                    uploaded_by VARCHAR(100) DEFAULT '',
                    meeting_type VARCHAR(100) DEFAULT '',
                    tags JSON NULL,
                    error_message TEXT,
                    source_filename VARCHAR(255) DEFAULT '',
                    deleted_at DATETIME NULL,
                    trash_until DATETIME NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_meetings_file_hash (file_hash),
                    KEY idx_meetings_date (meeting_date),
                    KEY idx_meetings_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            _migrate_meetings(cursor)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_action_items (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    meeting_id BIGINT UNSIGNED NOT NULL,
                    owner VARCHAR(100) DEFAULT '',
                    task TEXT NOT NULL,
                    due_date DATE NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY idx_action_items_meeting_id (meeting_id),
                    CONSTRAINT fk_action_items_meeting
                        FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_files (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    meeting_id BIGINT UNSIGNED NOT NULL,
                    file_name VARCHAR(255) NOT NULL,
                    file_type VARCHAR(50) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY idx_files_meeting_id (meeting_id),
                    CONSTRAINT fk_files_meeting
                        FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        conn.commit()


def _migrate_meetings(cursor) -> None:
    cursor.execute(
        "ALTER TABLE meetings MODIFY status "
        "ENUM('uploaded','pending','done','error','skipped','deleted') "
        "NOT NULL DEFAULT 'pending'"
    )
    columns = {
        "upload_status": "VARCHAR(30) DEFAULT ''",
        "stt_status": "VARCHAR(30) DEFAULT ''",
        "transcript_quality": "VARCHAR(30) DEFAULT ''",
        "summary_status": "VARCHAR(30) DEFAULT ''",
        "db_status": "VARCHAR(30) DEFAULT ''",
        "last_error": "TEXT",
        "retry_count": "INT UNSIGNED NOT NULL DEFAULT 0",
        "deleted_at": "DATETIME NULL",
        "trash_until": "DATETIME NULL",
    }
    for column, definition in columns.items():
        _ensure_column(cursor, "meetings", column, definition)


def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %(table)s
          AND COLUMN_NAME = %(column)s
        """,
        {"table": table, "column": column},
    )
    if cursor.fetchone()["count"]:
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def save_meeting(record: dict[str, Any]) -> int:
    status = _normalize_status(record.get("status"))
    error_message = record.get("error_message", "")
    values = {
        "file_hash": record["file_hash"],
        "title": record.get("title", "회의록"),
        "meeting_date": record.get("meeting_date"),
        "meeting_start_time": record.get("meeting_start_time", ""),
        "meeting_end_time": record.get("meeting_end_time", ""),
        "duration_seconds": record.get("duration_seconds"),
        "status": status,
        "upload_status": record.get("upload_status", _default_upload_status(record)),
        "stt_status": record.get("stt_status", _default_stt_status(record)),
        "transcript_quality": record.get("transcript_quality", ""),
        "summary_status": record.get("summary_status", _default_summary_status(status)),
        "db_status": record.get("db_status", "done"),
        "last_error": record.get("last_error", error_message),
        "retry_count": int(record.get("retry_count", 0) or 0),
        "summary": record.get("key_summary", ""),
        "decisions": record.get("decisions", ""),
        "risks": record.get("risks", ""),
        "next_actions": record.get("next_actions", ""),
        "flow_message": record.get("flow_text", ""),
        "raw_text": record.get("raw_text", ""),
        "markdown_path": record.get("summary_path", ""),
        "audio_path": record.get("audio_path", ""),
        "transcript_path": record.get("transcript_path", ""),
        "source_type": record.get("source_type") or _infer_source_type(record),
        "uploaded_by": record.get("uploaded_by", ""),
        "meeting_type": record.get("meeting_type", ""),
        "tags": json.dumps(record.get("tags", []), ensure_ascii=False),
        "error_message": error_message,
        "source_filename": record.get("source_filename", ""),
    }

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                print(
                    f"[DB] insert 시작: {values['source_filename']} / "
                    f"status={values['status']}",
                    flush=True,
                )
                cursor.execute(
                """
                INSERT INTO meetings (
                    file_hash, title, meeting_date, meeting_start_time, meeting_end_time,
                    duration_seconds, status, upload_status, stt_status, transcript_quality, summary_status,
                    db_status, last_error, retry_count, summary, decisions, risks, next_actions,
                    flow_message, raw_text, markdown_path, audio_path, transcript_path,
                    source_type, uploaded_by, meeting_type, tags, error_message,
                    source_filename
                ) VALUES (
                    %(file_hash)s, %(title)s, %(meeting_date)s, %(meeting_start_time)s,
                    %(meeting_end_time)s, %(duration_seconds)s, %(status)s,
                    %(upload_status)s, %(stt_status)s, %(transcript_quality)s, %(summary_status)s,
                    %(db_status)s, %(last_error)s, %(retry_count)s, %(summary)s,
                    %(decisions)s, %(risks)s, %(next_actions)s, %(flow_message)s,
                    %(raw_text)s, %(markdown_path)s, %(audio_path)s, %(transcript_path)s,
                    %(source_type)s, %(uploaded_by)s, %(meeting_type)s, %(tags)s,
                    %(error_message)s, %(source_filename)s
                )
                ON DUPLICATE KEY UPDATE
                    title=VALUES(title),
                    meeting_date=VALUES(meeting_date),
                    meeting_start_time=VALUES(meeting_start_time),
                    meeting_end_time=VALUES(meeting_end_time),
                    duration_seconds=VALUES(duration_seconds),
                    status=VALUES(status),
                    upload_status=VALUES(upload_status),
                    stt_status=VALUES(stt_status),
                    transcript_quality=VALUES(transcript_quality),
                    summary_status=VALUES(summary_status),
                    db_status=VALUES(db_status),
                    last_error=VALUES(last_error),
                    retry_count=GREATEST(meetings.retry_count, VALUES(retry_count)),
                    summary=VALUES(summary),
                    decisions=VALUES(decisions),
                    risks=VALUES(risks),
                    next_actions=VALUES(next_actions),
                    flow_message=VALUES(flow_message),
                    raw_text=VALUES(raw_text),
                    markdown_path=VALUES(markdown_path),
                    audio_path=VALUES(audio_path),
                    transcript_path=VALUES(transcript_path),
                    source_type=VALUES(source_type),
                    uploaded_by=VALUES(uploaded_by),
                    meeting_type=VALUES(meeting_type),
                    tags=VALUES(tags),
                    error_message=VALUES(error_message),
                    source_filename=VALUES(source_filename)
                """,
                    values,
                )
                cursor.execute(
                    "SELECT id FROM meetings WHERE file_hash = %(file_hash)s",
                    {"file_hash": values["file_hash"]},
                )
                meeting_id = int(cursor.fetchone()["id"])

                cursor.execute(
                    "DELETE FROM meeting_action_items WHERE meeting_id = %(meeting_id)s",
                    {"meeting_id": meeting_id},
                )
                _insert_action_items(cursor, meeting_id, record.get("action_items", []))

                cursor.execute(
                    "DELETE FROM meeting_files WHERE meeting_id = %(meeting_id)s",
                    {"meeting_id": meeting_id},
                )
                _insert_files(cursor, meeting_id, record)
            conn.commit()
            _log_save_verification(conn, meeting_id)
    except Exception as exc:
        print(
            f"[ERROR] MySQL insert 실패: {values['source_filename']} / {exc}",
            flush=True,
        )
        write_failure_log(
            event="mysql_save_failed",
            file_name=values["source_filename"],
            error=str(exc),
            extra={
                "audio_path": values.get("audio_path", ""),
                "transcript_path": values.get("transcript_path", ""),
                "status": values.get("status", ""),
            },
        )
        raise
    return meeting_id


def create_uploaded_meeting(record: dict[str, Any]) -> int:
    uploaded = {
        **record,
        "status": record.get("status", "uploaded"),
        "key_summary": record.get("key_summary", ""),
        "decisions": record.get("decisions", ""),
        "risks": record.get("risks", ""),
        "next_actions": record.get("next_actions", ""),
        "flow_text": record.get("flow_text", ""),
        "raw_text": record.get("raw_text", ""),
        "summary_path": record.get("summary_path", ""),
        "transcript_path": record.get("transcript_path", ""),
        "upload_status": record.get("upload_status", "done"),
        "stt_status": record.get("stt_status", "pending"),
        "transcript_quality": record.get("transcript_quality", ""),
        "summary_status": record.get("summary_status", "pending"),
        "db_status": record.get("db_status", "done"),
        "last_error": record.get("last_error", ""),
        "action_items": record.get("action_items", []),
    }
    return save_meeting(uploaded)


def update_meeting_processing_state(
    meeting_id: int,
    *,
    status: str | None = None,
    upload_status: str | None = None,
    stt_status: str | None = None,
    transcript_quality: str | None = None,
    summary_status: str | None = None,
    db_status: str | None = None,
    last_error: str | None = None,
    retry_increment: bool = False,
) -> None:
    fields: list[str] = []
    values: dict[str, Any] = {"meeting_id": meeting_id}
    for name, value in {
        "status": status,
        "upload_status": upload_status,
        "stt_status": stt_status,
        "transcript_quality": transcript_quality,
        "summary_status": summary_status,
        "db_status": db_status,
        "last_error": last_error,
        "error_message": last_error,
    }.items():
        if value is None:
            continue
        fields.append(f"{name} = %({name})s")
        values[name] = value
    if retry_increment:
        fields.append("retry_count = retry_count + 1")
    if not fields:
        return
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE meetings SET {', '.join(fields)} WHERE id = %(meeting_id)s",
                values,
            )
        conn.commit()


def _log_save_verification(conn, meeting_id: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS row_count FROM meetings")
        count_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                id, title, status, source_filename,
                DATABASE() AS database_name,
                @@hostname AS hostname,
                @@port AS port
            FROM meetings
            WHERE id = %(meeting_id)s
            """,
            {"meeting_id": meeting_id},
        )
        saved_row = cursor.fetchone()
    print(
        f"[DB] 저장 후 meetings row count: {count_row.get('row_count')}",
        flush=True,
    )
    print(
        "[DB] 저장 후 meeting 재조회: "
        f"{saved_row if saved_row else 'NOT FOUND'}",
        flush=True,
    )


def list_meetings() -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM meetings
                WHERE status <> 'deleted'
                ORDER BY meeting_date DESC, updated_at DESC
                """
            )
            rows = cursor.fetchall()
            ids = [row["id"] for row in rows]
            action_items = _fetch_action_items(cursor, ids)
            files = _fetch_files(cursor, ids)
    return [
        _row_to_dict(row, action_items.get(row["id"], []), files.get(row["id"], []), False)
        for row in rows
    ]


def get_database_debug_info() -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    DATABASE() AS database_name,
                    @@hostname AS hostname,
                    @@port AS port,
                    @@version AS version,
                    @@socket AS socket_path,
                    CURRENT_USER() AS current_user_name,
                    CONNECTION_ID() AS connection_id
                """
            )
            info = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS row_count FROM meetings")
            info["meetings_count"] = cursor.fetchone()["row_count"]
    return info


def log_database_debug_info(prefix: str = "[DB]") -> dict[str, Any]:
    info = get_database_debug_info()
    print(
        f"{prefix} 실제 저장 DB 확인: "
        f"database={info.get('database_name')} / "
        f"hostname={info.get('hostname')} / "
        f"port={info.get('port')} / "
        f"version={info.get('version')} / "
        f"user={info.get('current_user_name')} / "
        f"connection_id={info.get('connection_id')} / "
        f"socket={info.get('socket_path')} / "
        f"meetings_count={info.get('meetings_count')}",
        flush=True,
    )
    return info


def get_meeting(meeting_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM meetings WHERE id = %(id)s AND status <> 'deleted'",
                {"id": meeting_id},
            )
            row = cursor.fetchone()
            if not row:
                return None
            action_items = _fetch_action_items(cursor, [meeting_id]).get(meeting_id, [])
            files = _fetch_files(cursor, [meeting_id]).get(meeting_id, [])
    return _row_to_dict(row, action_items, files, True)


def delete_meeting(meeting_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM meetings WHERE id = %(id)s", {"id": meeting_id})
            row = cursor.fetchone()
            if not row:
                return False
            cursor.execute(
                """
                UPDATE meetings
                SET status = 'deleted',
                    deleted_at = NOW(),
                    trash_until = DATE_ADD(NOW(), INTERVAL 7 DAY),
                    last_error = '',
                    error_message = ''
                WHERE id = %(id)s
                """,
                {"id": meeting_id},
            )
        conn.commit()
    print(
        f"[DB] soft delete 완료: meeting #{meeting_id} / "
        "원본 파일은 삭제하지 않고 휴지통 보관 상태로 유지합니다.",
        flush=True,
    )
    return True


def _insert_action_items(cursor, meeting_id: int, items: list[dict[str, Any]]) -> None:
    for item in items:
        task = item.get("task", "").strip()
        if not task:
            continue
        cursor.execute(
            """
            INSERT INTO meeting_action_items (meeting_id, owner, task, due_date, status)
            VALUES (%(meeting_id)s, %(owner)s, %(task)s, %(due_date)s, %(status)s)
            """,
            {
                "meeting_id": meeting_id,
                "owner": item.get("owner", ""),
                "task": task,
                "due_date": item.get("due_date") or None,
                "status": item.get("status", "pending"),
            },
        )


def _insert_files(cursor, meeting_id: int, record: dict[str, Any]) -> None:
    file_specs = [
        ("raw", record.get("source_filename") or Path(record.get("raw_path", "")).name, record.get("raw_path")),
        ("markdown", Path(record.get("summary_path", "")).name, record.get("summary_path")),
        ("flow", Path(record.get("flow_path", "")).name, record.get("flow_path")),
        ("audio", Path(record.get("audio_path", "")).name, record.get("audio_path")),
        ("transcript", Path(record.get("transcript_path", "")).name, record.get("transcript_path")),
    ]
    seen: set[tuple[str, str]] = set()
    for file_type, file_name, file_path in file_specs:
        if not file_path:
            continue
        key = (file_type, file_path)
        if key in seen:
            continue
        seen.add(key)
        cursor.execute(
            """
            INSERT INTO meeting_files (meeting_id, file_name, file_type, file_path)
            VALUES (%(meeting_id)s, %(file_name)s, %(file_type)s, %(file_path)s)
            """,
            {
                "meeting_id": meeting_id,
                "file_name": file_name or Path(file_path).name,
                "file_type": file_type,
                "file_path": file_path,
            },
        )


def _fetch_action_items(cursor, meeting_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not meeting_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(meeting_ids))
    cursor.execute(
        f"""
        SELECT meeting_id, owner, task, due_date, status
        FROM meeting_action_items
        WHERE meeting_id IN ({placeholders})
        ORDER BY id ASC
        """,
        meeting_ids,
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        grouped.setdefault(row["meeting_id"], []).append(
            {
                "owner": row.get("owner") or "",
                "task": row.get("task") or "",
                "due_date": str(row["due_date"]) if row.get("due_date") else "",
                "status": row.get("status") or "",
            }
        )
    return grouped


def _fetch_files(cursor, meeting_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not meeting_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(meeting_ids))
    cursor.execute(
        f"""
        SELECT meeting_id, file_name, file_type, file_path
        FROM meeting_files
        WHERE meeting_id IN ({placeholders})
        ORDER BY id ASC
        """,
        meeting_ids,
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        grouped.setdefault(row["meeting_id"], []).append(row)
    return grouped


def _row_to_dict(
    row: dict[str, Any],
    action_items: list[dict[str, Any]],
    files: list[dict[str, Any]],
    include_markdown: bool,
) -> dict[str, Any]:
    paths = _paths_by_type(files)
    meeting_time = _meeting_time(row)
    markdown_path = row.get("markdown_path") or paths.get("markdown", "")
    flow_text = row.get("flow_message") or ""
    markdown = _read_text(markdown_path) if include_markdown else ""
    raw_path = paths.get("raw", "")
    item = {
        "id": row["id"],
        "title": row.get("title") or "회의록",
        "date": str(row.get("meeting_date") or ""),
        "meeting_time": meeting_time,
        "meeting_start_time": row.get("meeting_start_time") or "",
        "meeting_end_time": row.get("meeting_end_time") or "",
        "duration_seconds": row.get("duration_seconds"),
        "duration_label": _format_duration(row.get("duration_seconds")),
        "status": row.get("status") or "pending",
        "upload_status": row.get("upload_status") or "",
        "stt_status": row.get("stt_status") or "",
        "transcript_quality": row.get("transcript_quality") or "",
        "transcript_low_quality": row.get("transcript_quality") == "low",
        "summary_status": row.get("summary_status") or "",
        "db_status": row.get("db_status") or "",
        "last_error": row.get("last_error") or "",
        "retry_count": row.get("retry_count") or 0,
        "source_filename": row.get("source_filename") or Path(raw_path).name,
        "key_summary": row.get("summary") or "",
        "decisions": row.get("decisions") or "",
        "risks": row.get("risks") or "",
        "next_actions": row.get("next_actions") or "",
        "action_items": action_items,
        "has_action_items": bool(action_items),
        "search_text": _search_text(row, action_items, markdown, flow_text),
        "created_at": _format_datetime(row.get("created_at")),
        "updated_at": _format_datetime(row.get("updated_at")),
    }
    if include_markdown:
        item.update(
            {
                "markdown": markdown,
                "flow_text": flow_text,
                "raw_text": row.get("raw_text") or "",
                "raw_path": raw_path,
                "summary_path": markdown_path,
                "flow_path": paths.get("flow", ""),
                "audio_path": row.get("audio_path") or paths.get("audio", ""),
                "transcript_path": row.get("transcript_path") or paths.get("transcript", ""),
                "source_type": row.get("source_type") or "",
                "uploaded_by": row.get("uploaded_by") or "",
                "meeting_type": row.get("meeting_type") or "",
                "tags": _loads_json(row.get("tags"), []),
                "error_message": row.get("error_message") or "",
                "deleted_at": _format_datetime(row.get("deleted_at")),
                "trash_until": _format_datetime(row.get("trash_until")),
                "files": files,
            }
        )
    return item


def _paths_by_type(files: list[dict[str, Any]]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for file in files:
        paths.setdefault(file.get("file_type", ""), file.get("file_path", ""))
    return paths


def _meeting_time(row: dict[str, Any]) -> str:
    start = row.get("meeting_start_time") or ""
    end = row.get("meeting_end_time") or ""
    if start and end:
        return f"{start} ~ {end}"
    return start or ""


def _search_text(
    row: dict[str, Any],
    action_items: list[dict[str, Any]],
    markdown: str,
    flow_text: str,
) -> str:
    return "\n".join(
        [
            str(row.get("title") or ""),
            str(row.get("meeting_date") or ""),
            row.get("meeting_start_time") or "",
            row.get("meeting_end_time") or "",
            row.get("source_filename") or "",
            row.get("summary") or "",
            row.get("decisions") or "",
            row.get("risks") or "",
            row.get("next_actions") or "",
            row.get("raw_text") or "",
            markdown,
            flow_text,
            json.dumps(action_items, ensure_ascii=False),
        ]
    )


def _read_text(path_value: str) -> str:
    if not path_value:
        return ""
    target = (ROOT_DIR / path_value).resolve()
    root = ROOT_DIR.resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        return ""
    if not target.is_file():
        return ""
    return target.read_text(encoding="utf-8")


def _delete_project_file(path_value: str | None) -> None:
    if not path_value:
        return
    target = (ROOT_DIR / path_value).resolve()
    root = ROOT_DIR.resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        return
    if target.is_file():
        target.unlink()


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes = max(1, round(seconds / 60))
    hours, rest = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {rest}분" if rest else f"{hours}시간"
    return f"{minutes}분"


def _format_datetime(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value or "")


def _normalize_status(status: str | None) -> str:
    if status in {"uploaded", "pending", "done", "error", "skipped", "deleted"}:
        return status
    if status == "failed":
        return "error"
    return "pending"


def _default_upload_status(record: dict[str, Any]) -> str:
    return "done" if record.get("audio_path") or record.get("raw_path") else ""


def _default_stt_status(record: dict[str, Any]) -> str:
    if record.get("source_type") == "txt" or record.get("raw_path") and not record.get("audio_path"):
        return "not_required"
    return "done" if record.get("transcript_path") or record.get("raw_text") else "pending"


def _default_summary_status(status: str) -> str:
    if status in PROCESS_STATUSES:
        return status
    if status == "uploaded":
        return "pending"
    return ""


def _infer_source_type(record: dict[str, Any]) -> str:
    if record.get("audio_path"):
        return "web_recording"
    return "txt"


def _loads_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
