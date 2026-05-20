from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from app_helpers import is_short_test_transcript
from database import (
    create_uploaded_meeting,
    delete_meeting,
    get_meeting,
    init_db,
    list_meetings,
    log_database_debug_info,
    update_meeting_processing_state,
)
from failure_log import write_failure_log
from recovery import recover_recordings
from summarizer import process_transcript_text, process_txt_file
from transcriber import AUDIO_DIR, TRANSCRIPT_DIR, transcribe_audio
from watcher import INPUT_DIR, process_existing_files, start_watcher


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
TEMP_AUDIO_DIR = ROOT_DIR / "storage" / "temp_audio"
KST = ZoneInfo("Asia/Seoul")

load_dotenv(ROOT_DIR / ".env")
init_db()

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/media/<path:file_path>")
def media_file(file_path: str):
    target = (ROOT_DIR / file_path).resolve()
    root = ROOT_DIR.resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root) or not target.is_file():
        return jsonify({"error": "파일을 찾을 수 없습니다."}), 404
    return send_from_directory(target.parent, target.name)


@app.get("/api/meetings")
def api_list_meetings():
    query = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "all").strip()
    items = list_meetings()
    if query:
        items = [
            item for item in items if query in (item.get("search_text") or "").lower()
        ]
    if status == "actions":
        items = [item for item in items if item["has_action_items"]]
    elif status in {"uploaded", "pending", "done", "error", "skipped"}:
        items = [item for item in items if item["status"] == status]
    return jsonify(items)


@app.get("/api/meetings/<int:meeting_id>")
def api_get_meeting(meeting_id: int):
    item = get_meeting(meeting_id)
    if not item:
        return jsonify({"error": "회의록을 찾을 수 없습니다."}), 404
    return jsonify(item)


@app.delete("/api/meetings/<int:meeting_id>")
def api_delete_meeting(meeting_id: int):
    deleted = delete_meeting(meeting_id)
    if not deleted:
        return jsonify({"error": "회의록을 찾을 수 없습니다."}), 404
    print(f"[DB] 삭제 완료: meeting #{meeting_id}", flush=True)
    return jsonify({"ok": True})


@app.post("/api/process-existing")
def api_process_existing():
    process_existing_files()
    return jsonify({"ok": True})


@app.post("/api/process-file")
def api_process_file():
    payload = request.get_json(silent=True) or {}
    filename = payload.get("filename")
    if not filename:
        return jsonify({"error": "filename이 필요합니다."}), 400
    path = INPUT_DIR / Path(filename).name
    if not path.exists():
        return jsonify({"error": "input/clova_txt 폴더에서 파일을 찾을 수 없습니다."}), 404
    meeting_id = process_txt_file(path)
    return jsonify({"ok": True, "id": meeting_id})


@app.post("/api/recover-recordings")
def api_recover_recordings():
    stats = recover_recordings()
    return jsonify({"ok": True, **stats})


@app.post("/api/recordings")
def api_recording_upload():
    if "audio" not in request.files:
        return jsonify({"error": "audio 파일이 필요합니다."}), 400

    audio = request.files["audio"]
    original_name = audio.filename or "browser-recording.webm"
    suffix = Path(original_name).suffix.lower() or ".webm"
    timestamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    recording_id = uuid.uuid4().hex
    audio_name = f"{timestamp}_meeting_{recording_id}{suffix}"
    started_at = request.form.get("started_at", "")
    ended_at = request.form.get("ended_at", "")
    duration_seconds = _parse_int(request.form.get("duration_seconds"))

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = AUDIO_DIR / audio_name

    try:
        print(f"[RECORDING] 업로드 수신: {original_name}", flush=True)
        audio.save(audio_path)
        print(f"[RECORDING] 음성 저장 완료: {audio_path}", flush=True)
        result = _create_uploaded_then_process(
            audio_path=audio_path,
            audio_name=audio_name,
            timestamp=timestamp,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
        )
        return jsonify({"ok": True, **result})
    except Exception as exc:
        print(f"[ERROR] 녹음 처리 실패: {exc}", flush=True)
        write_failure_log(
            event="recording_upload_failed",
            file_name=original_name,
            error=str(exc),
            extra={"audio_path": str(audio_path.relative_to(ROOT_DIR)) if audio_path.exists() else ""},
        )
        return jsonify({"error": str(exc)}), 500


@app.post("/api/recordings/start")
def api_recording_start():
    TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    recording_id = uuid.uuid4().hex
    timestamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    audio_name = f"{timestamp}_meeting_{recording_id}.webm"
    session_dir = TEMP_AUDIO_DIR / recording_id
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "recording_id": recording_id,
        "audio_name": audio_name,
        "timestamp": timestamp,
        "created_at": datetime.now(KST).isoformat(timespec="seconds"),
        "started_at": request.json.get("started_at", "") if request.is_json else "",
        "status": "recording",
    }
    (session_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[RECORDING] 임시 녹음 세션 생성: {recording_id} / {audio_name}", flush=True)
    return jsonify({"ok": True, "recording_id": recording_id, "audio_name": audio_name})


@app.post("/api/recordings/chunk")
def api_recording_chunk():
    recording_id = request.form.get("recording_id", "")
    chunk = request.files.get("chunk")
    if not recording_id or not chunk:
        return jsonify({"error": "recording_id와 chunk가 필요합니다."}), 400
    session_dir = TEMP_AUDIO_DIR / secure_filename(recording_id)
    if not session_dir.is_dir():
        return jsonify({"error": "녹음 세션을 찾을 수 없습니다."}), 404
    sequence = _parse_int(request.form.get("sequence")) or 0
    chunk_path = session_dir / f"{sequence:08d}.part"
    chunk.save(chunk_path)
    print(f"[RECORDING] 임시 chunk 저장: {recording_id} / #{sequence}", flush=True)
    return jsonify({"ok": True, "sequence": sequence})


@app.post("/api/recordings/finish")
def api_recording_finish():
    payload = request.get_json(silent=True) or {}
    recording_id = payload.get("recording_id", "")
    if not recording_id:
        return jsonify({"error": "recording_id가 필요합니다."}), 400
    session_dir = TEMP_AUDIO_DIR / secure_filename(recording_id)
    meta_path = session_dir / "meta.json"
    if not meta_path.is_file():
        return jsonify({"error": "녹음 세션을 찾을 수 없습니다."}), 404
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    audio_name = meta["audio_name"]
    audio_path = AUDIO_DIR / audio_name
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        chunk_paths = sorted(session_dir.glob("*.part"))
        if not chunk_paths:
            raise RuntimeError("저장된 녹음 chunk가 없습니다.")
        with audio_path.open("wb") as output:
            for chunk_path in chunk_paths:
                with chunk_path.open("rb") as chunk_file:
                    shutil.copyfileobj(chunk_file, output)
        print(f"[RECORDING] 원본 audio 확정 저장: {audio_path}", flush=True)
        result = _create_uploaded_then_process(
            audio_path=audio_path,
            audio_name=audio_name,
            timestamp=meta["timestamp"],
            started_at=payload.get("started_at") or meta.get("started_at", ""),
            ended_at=payload.get("ended_at", ""),
            duration_seconds=_parse_int(str(payload.get("duration_seconds", ""))),
        )
        return jsonify({"ok": True, **result})
    except Exception as exc:
        print(f"[ERROR] 녹음 종료 처리 실패: {exc}", flush=True)
        write_failure_log(
            event="recording_finish_failed",
            file_name=audio_name,
            error=str(exc),
            extra={"recording_id": recording_id, "audio_path": str(audio_path.relative_to(ROOT_DIR))},
        )
        return jsonify({"error": str(exc), "audio_path": str(audio_path.relative_to(ROOT_DIR))}), 500


def _create_uploaded_then_process(
    *,
    audio_path: Path,
    audio_name: str,
    timestamp: str,
    started_at: str,
    ended_at: str,
    duration_seconds: int | None,
) -> dict:
    file_hash = _recording_hash(audio_name)
    uploaded_record = {
        "file_hash": file_hash,
        "title": f"웹 녹음 회의 {timestamp}",
        "meeting_date": _date_from_iso(started_at) or datetime.now(KST).date().isoformat(),
        "meeting_start_time": _time_from_iso(started_at),
        "meeting_end_time": _time_from_iso(ended_at),
        "duration_seconds": duration_seconds,
        "audio_path": str(audio_path.relative_to(ROOT_DIR)),
        "source_type": "web_recording",
        "source_filename": audio_name,
    }
    print("[DB] uploaded row 저장 시작", flush=True)
    try:
        meeting_id = create_uploaded_meeting(uploaded_record)
        print(f"[DB] uploaded row 저장 완료: meeting #{meeting_id}", flush=True)
    except Exception as exc:
        print(f"[ERROR] uploaded row 저장 실패: {exc}", flush=True)
        write_failure_log(
            event="uploaded_row_failed",
            file_name=audio_name,
            error=str(exc),
            extra={"audio_path": str(audio_path.relative_to(ROOT_DIR))},
        )
        raise

    transcript_path = TRANSCRIPT_DIR / f"{Path(audio_name).stem}.txt"
    try:
        print("[STT] 처리 중", flush=True)
        transcript = transcribe_audio(audio_path)
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(transcript, encoding="utf-8")
        update_meeting_processing_state(meeting_id, stt_status="done")
        print(f"[STT] 텍스트 저장 완료: {transcript_path}", flush=True)
    except Exception as exc:
        print(f"[ERROR] STT 실패, audio는 유지: {exc}", flush=True)
        update_meeting_processing_state(
            meeting_id,
            status="error",
            stt_status="error",
            summary_status="pending",
            last_error=str(exc),
            retry_increment=True,
        )
        write_failure_log(
            event="stt_failed",
            file_name=audio_name,
            error=str(exc),
            extra={"meeting_id": meeting_id, "audio_path": str(audio_path.relative_to(ROOT_DIR))},
        )
        return {"id": meeting_id, "status": "error", "message": "STT 처리에 실패했지만 원본 audio는 보존되었습니다."}

    reason = ""
    if is_short_test_transcript(transcript):
        reason = "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다."
        print("[RECORDING] 짧은 테스트 녹음으로 회의록 생성 건너뜀", flush=True)

    print("[SUMMARY] GPT 요약 처리 시작", flush=True)
    meeting_id = process_transcript_text(
        transcript=transcript,
        source_name=transcript_path.name,
        source_path=transcript_path,
        title_seed=f"웹 녹음 회의 {timestamp}",
        file_hash_seed=f"recording:{audio_name}",
        file_hash_override=file_hash,
        meeting_start_time=started_at,
        meeting_end_time=ended_at,
        duration_seconds=duration_seconds,
        audio_path=audio_path,
        transcript_path=transcript_path,
        source_type="web_recording",
        skip_summary_reason=reason,
    )
    print(f"[DB] 저장 완료: meeting #{meeting_id}", flush=True)
    return {
        "id": meeting_id,
        "skipped": bool(reason),
        "message": reason,
        "audio_path": str(audio_path.relative_to(ROOT_DIR)),
        "transcript_path": str(transcript_path.relative_to(ROOT_DIR)),
    }


def _recording_hash(audio_name: str) -> str:
    return hashlib.sha256(f"recording:{audio_name}".encode("utf-8")).hexdigest()


def _parse_int(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _date_from_iso(value: str) -> str:
    parsed = _parse_iso_kst(value)
    return parsed.date().isoformat() if parsed else ""


def _time_from_iso(value: str) -> str:
    parsed = _parse_iso_kst(value)
    return parsed.strftime("%H:%M") if parsed else ""


def _parse_iso_kst(value: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(KST)
    except ValueError:
        return None


def run_web(watch: bool) -> None:
    if watch:
        print("[APP] watcher thread 시작", flush=True)
        thread = threading.Thread(target=start_watcher, daemon=True)
        thread.start()
    else:
        print("[APP] watcher 비활성화", flush=True)
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    print(f"[APP] Flask 시작: http://{host}:{port}", flush=True)
    app.run(host=host, port=port, debug=False, use_reloader=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="회의록 요약 에이전트")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="TXT 폴더 자동 감시. 현재는 기본값으로 켜져 있으며 호환성을 위해 유지합니다.",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="TXT 폴더 자동 감시를 끕니다.",
    )
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="input/clova_txt 안의 기존 TXT를 한 번 처리",
    )
    parser.add_argument("--no-web", action="store_true", help="웹 서버 실행 안 함")
    parser.add_argument(
        "--recover-recordings",
        action="store_true",
        help="storage/audio와 storage/transcripts를 스캔해 누락된 MySQL row를 복구",
    )
    parser.add_argument(
        "--db-check",
        action="store_true",
        help="현재 앱이 접속하는 MySQL 서버, DB, meetings row count를 출력",
    )
    args = parser.parse_args()

    watch_enabled = not args.no_watch

    if args.recover_recordings:
        recover_recordings()
        if args.no_web:
            return
    if args.db_check:
        log_database_debug_info("[DB-CHECK]")
        if args.no_web:
            return
    if args.process_existing:
        process_existing_files()
    if args.no_web:
        if watch_enabled:
            start_watcher()
        return
    run_web(watch=watch_enabled)


if __name__ == "__main__":
    main()
