from __future__ import annotations

import argparse
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from app_helpers import is_short_test_transcript
from database import delete_meeting, get_meeting, init_db, list_meetings
from recovery import recover_recordings
from summarizer import process_transcript_text, process_txt_file
from transcriber import AUDIO_DIR, TRANSCRIPT_DIR, transcribe_audio
from watcher import INPUT_DIR, process_existing_files, start_watcher


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
KST = ZoneInfo("Asia/Seoul")

load_dotenv(ROOT_DIR / ".env", override=True)
init_db()

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


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
    elif status in {"pending", "done", "error", "skipped"}:
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
    safe_title = secure_filename(Path(original_name).stem) or "browser_recording"
    audio_name = f"{timestamp}_{safe_title}{suffix}"
    started_at = request.form.get("started_at", "")
    ended_at = request.form.get("ended_at", "")
    duration_seconds = _parse_int(request.form.get("duration_seconds"))

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = AUDIO_DIR / audio_name
    transcript_path = TRANSCRIPT_DIR / f"{timestamp}_{safe_title}.txt"

    try:
        print(f"[RECORDING] 업로드 수신: {original_name}", flush=True)
        audio.save(audio_path)
        print(f"[RECORDING] 음성 저장 완료: {audio_path}", flush=True)

        transcript = transcribe_audio(audio_path)
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"[STT] 텍스트 저장 완료: {transcript_path}", flush=True)

        if is_short_test_transcript(transcript):
            print("[RECORDING] 짧은 테스트 녹음으로 회의록 생성 건너뜀", flush=True)
            try:
                meeting_id = process_transcript_text(
                    transcript=transcript,
                    source_name=transcript_path.name,
                    source_path=transcript_path,
                    title_seed=f"웹 녹음 회의 {timestamp}",
                    file_hash_seed=f"recording:{audio_name}",
                    meeting_start_time=started_at,
                    meeting_end_time=ended_at,
                    duration_seconds=duration_seconds,
                    audio_path=audio_path,
                    transcript_path=transcript_path,
                    source_type="web_recording",
                    skip_summary_reason="회의 내용이 너무 짧아 회의록을 생성하지 않았습니다.",
                )
                print(f"[RECORDING] skipped row 저장 완료: meeting #{meeting_id}", flush=True)
            except Exception as exc:
                print(f"[ERROR] skipped row 저장 실패: {exc}", flush=True)
                raise
            return jsonify(
                {
                    "ok": True,
                    "skipped": True,
                    "message": "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다.",
                    "id": meeting_id,
                    "audio_path": str(audio_path.relative_to(ROOT_DIR)),
                    "transcript_path": str(transcript_path.relative_to(ROOT_DIR)),
                }
            )

        meeting_id = process_transcript_text(
            transcript=transcript,
            source_name=transcript_path.name,
            source_path=transcript_path,
            title_seed=f"웹 녹음 회의 {timestamp}",
            file_hash_seed=f"recording:{audio_name}",
            meeting_start_time=started_at,
            meeting_end_time=ended_at,
            duration_seconds=duration_seconds,
            audio_path=audio_path,
            transcript_path=transcript_path,
            source_type="web_recording",
        )
        print(f"[RECORDING] 회의록 생성 완료: meeting #{meeting_id}", flush=True)
        return jsonify(
            {
                "ok": True,
                "id": meeting_id,
                "audio_path": str(audio_path.relative_to(ROOT_DIR)),
                "transcript_path": str(transcript_path.relative_to(ROOT_DIR)),
            }
        )
    except Exception as exc:
        print(f"[ERROR] 녹음 처리 실패: {exc}", flush=True)
        return jsonify({"error": str(exc)}), 500


def _parse_int(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return max(0, int(value))
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
    args = parser.parse_args()

    watch_enabled = not args.no_watch

    if args.recover_recordings:
        recover_recordings()
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
