from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "data" / "meetings.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                meeting_date TEXT NOT NULL,
                meeting_time TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'done',
                source_filename TEXT NOT NULL,
                raw_path TEXT NOT NULL,
                summary_path TEXT NOT NULL,
                flow_path TEXT NOT NULL,
                markdown TEXT NOT NULL,
                flow_text TEXT NOT NULL,
                key_summary TEXT DEFAULT '',
                decisions TEXT DEFAULT '',
                risks TEXT DEFAULT '',
                next_actions TEXT DEFAULT '',
                action_items_json TEXT DEFAULT '[]',
                search_text TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status)"
        )
        _ensure_column(conn, "meeting_start_time", "TEXT DEFAULT ''")
        _ensure_column(conn, "meeting_end_time", "TEXT DEFAULT ''")
        _ensure_column(conn, "duration_seconds", "INTEGER")
        _ensure_column(conn, "audio_path", "TEXT DEFAULT ''")
        _ensure_column(conn, "transcript_path", "TEXT DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, name: str, definition: str) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(meetings)").fetchall()
    }
    if name not in columns:
        conn.execute(f"ALTER TABLE meetings ADD COLUMN {name} {definition}")


def save_meeting(record: dict[str, Any]) -> int:
    action_items_json = json.dumps(
        record.get("action_items", []), ensure_ascii=False
    )
    values = {
        **record,
        "action_items_json": action_items_json,
        "meeting_start_time": record.get("meeting_start_time", ""),
        "meeting_end_time": record.get("meeting_end_time", ""),
        "duration_seconds": record.get("duration_seconds"),
        "audio_path": record.get("audio_path", ""),
        "transcript_path": record.get("transcript_path", ""),
    }
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO meetings (
                file_hash, title, meeting_date, meeting_time, status,
                source_filename, raw_path, summary_path, flow_path,
                markdown, flow_text, key_summary, decisions, risks,
                next_actions, action_items_json, search_text,
                meeting_start_time, meeting_end_time, duration_seconds,
                audio_path, transcript_path
            ) VALUES (
                :file_hash, :title, :meeting_date, :meeting_time, :status,
                :source_filename, :raw_path, :summary_path, :flow_path,
                :markdown, :flow_text, :key_summary, :decisions, :risks,
                :next_actions, :action_items_json, :search_text,
                :meeting_start_time, :meeting_end_time, :duration_seconds,
                :audio_path, :transcript_path
            )
            ON CONFLICT(file_hash) DO UPDATE SET
                title=excluded.title,
                meeting_date=excluded.meeting_date,
                meeting_time=excluded.meeting_time,
                status=excluded.status,
                source_filename=excluded.source_filename,
                raw_path=excluded.raw_path,
                summary_path=excluded.summary_path,
                flow_path=excluded.flow_path,
                markdown=excluded.markdown,
                flow_text=excluded.flow_text,
                key_summary=excluded.key_summary,
                decisions=excluded.decisions,
                risks=excluded.risks,
                next_actions=excluded.next_actions,
                action_items_json=excluded.action_items_json,
                search_text=excluded.search_text,
                meeting_start_time=excluded.meeting_start_time,
                meeting_end_time=excluded.meeting_end_time,
                duration_seconds=excluded.duration_seconds,
                audio_path=excluded.audio_path,
                transcript_path=excluded.transcript_path,
                updated_at=CURRENT_TIMESTAMP
            """,
            values,
        )
        row = conn.execute(
            "SELECT id FROM meetings WHERE file_hash = ?", (record["file_hash"],)
        ).fetchone()
        return int(row["id"] if row else cursor.lastrowid)


def list_meetings() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, meeting_date, meeting_time, status, source_filename,
                   key_summary, decisions, risks, next_actions, action_items_json,
                   search_text, meeting_start_time, meeting_end_time,
                   duration_seconds, created_at, updated_at
            FROM meetings
            ORDER BY meeting_date DESC, updated_at DESC
            """
        ).fetchall()
    return [_row_to_dict(row, include_markdown=False) for row in rows]


def get_meeting(meeting_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
    return _row_to_dict(row, include_markdown=True) if row else None


def delete_meeting(meeting_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT raw_path, summary_path, flow_path, audio_path, transcript_path
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()
        if not row:
            return False

        conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))

    for path_value in dict(row).values():
        _delete_project_file(path_value)
    return True


def _delete_project_file(path_value: str | None) -> None:
    if not path_value:
        return
    target = (ROOT_DIR / path_value).resolve()
    root = ROOT_DIR.resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        return
    if target.is_file():
        target.unlink()


def _row_to_dict(row: sqlite3.Row, include_markdown: bool) -> dict[str, Any]:
    item = dict(row)
    item["date"] = item.pop("meeting_date")
    item["action_items"] = json.loads(item.pop("action_items_json") or "[]")
    item["has_action_items"] = bool(item["action_items"])
    item["duration_label"] = _format_duration(item.get("duration_seconds"))
    if not include_markdown:
        item.pop("markdown", None)
        item.pop("flow_text", None)
        item.pop("raw_path", None)
        item.pop("summary_path", None)
        item.pop("flow_path", None)
        item.pop("audio_path", None)
        item.pop("transcript_path", None)
    return item


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
