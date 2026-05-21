from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from app_helpers import is_short_test_transcript
from database import create_uploaded_meeting, log_database_debug_info, update_meeting_processing_state
from failure_log import write_failure_log
from summarizer import ROOT_DIR, process_transcript_text
from transcriber import AUDIO_DIR, TRANSCRIPT_DIR, transcribe_audio_with_metadata


AUDIO_EXTENSIONS = {".webm", ".mp4", ".m4a", ".mp3", ".wav", ".ogg"}


def recover_recordings() -> dict[str, int]:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    temp_audio_dir = ROOT_DIR / "storage" / "temp_audio"
    temp_audio_dir.mkdir(parents=True, exist_ok=True)
    summary_dir = ROOT_DIR / "storage" / "summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    assembled = _assemble_temp_audio(temp_audio_dir)

    audio_by_stem = {
        path.stem: path
        for path in sorted(AUDIO_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    }
    transcripts_by_stem = {
        path.stem: path
        for path in sorted(TRANSCRIPT_DIR.iterdir())
        if path.is_file() and path.suffix.lower() == ".txt"
    }
    summaries_by_stem = {
        path.stem: path
        for path in sorted(summary_dir.iterdir())
        if path.is_file() and path.suffix.lower() == ".md"
    }
    stems = sorted(set(audio_by_stem) | set(transcripts_by_stem) | set(summaries_by_stem))

    print(f"[RECOVER] 녹음 파일 확인: {len(audio_by_stem)}개", flush=True)
    print(f"[RECOVER] 전사 파일 확인: {len(transcripts_by_stem)}개", flush=True)
    print(f"[RECOVER] 요약 파일 확인: {len(summaries_by_stem)}개", flush=True)

    stats = {
        "checked": 0,
        "saved": 0,
        "failed": 0,
        "skipped": 0,
        "stt_retried": 0,
        "temp_assembled": assembled,
    }
    for stem in stems:
        stats["checked"] += 1
        audio_path = audio_by_stem.get(stem)
        transcript_path = transcripts_by_stem.get(stem)
        transcript_quality = ""
        print(
            f"[RECOVER] 상태 비교: {stem} / "
            f"audio={bool(audio_path)} transcript={bool(transcript_path)} summary={stem in summaries_by_stem}",
            flush=True,
        )
        try:
            uploaded_id = None
            recovery_hash = hashlib.sha256(
                f"recording:{audio_path.name if audio_path else stem}".encode("utf-8")
            ).hexdigest()
            if audio_path:
                uploaded_id = create_uploaded_meeting(
                    {
                        "file_hash": recovery_hash,
                        "title": f"복구 녹음 {stem}",
                        "meeting_date": _date_from_stem(stem),
                        "audio_path": str(audio_path.relative_to(ROOT_DIR)),
                        "source_type": "web_recording",
                        "source_filename": audio_path.name,
                    }
                )
                print(f"[RECOVER] uploaded row 확인 완료: meeting #{uploaded_id}", flush=True)

            if not transcript_path and audio_path:
                print(f"[RECOVER] 전사 파일 없음, 다시 STT: {audio_path.name}", flush=True)
                try:
                    transcription = transcribe_audio_with_metadata(audio_path)
                    transcript = transcription.text
                    transcript_quality = transcription.quality
                    transcript_path = TRANSCRIPT_DIR / f"{stem}.txt"
                    transcript_path.write_text(transcript, encoding="utf-8")
                    stats["stt_retried"] += 1
                    if uploaded_id:
                        update_meeting_processing_state(
                            uploaded_id,
                            stt_status="done",
                            transcript_quality=transcription.quality,
                        )
                except Exception as exc:
                    if uploaded_id:
                        update_meeting_processing_state(
                            uploaded_id,
                            status="error",
                            stt_status="error",
                            summary_status="pending",
                            last_error=str(exc),
                            retry_increment=True,
                        )
                    raise

            if not transcript_path:
                stats["skipped"] += 1
                continue

            transcript = transcript_path.read_text(encoding="utf-8").strip()
            if not transcript_quality:
                transcript_quality = "unknown"
            print(f"[RECOVER] DB 저장 시작: {transcript_path.name}", flush=True)
            reason = ""
            if is_short_test_transcript(transcript):
                reason = "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다."

            meeting_id = process_transcript_text(
                transcript=transcript,
                source_name=transcript_path.name,
                source_path=transcript_path,
                title_seed=f"복구 녹음 {transcript_path.stem}",
                file_hash_seed=f"recovered-recording:{transcript_path.stem}",
                file_hash_override=recovery_hash,
                audio_path=audio_path,
                transcript_path=transcript_path,
                source_type="web_recording",
                summary_error_status="pending",
                transcript_quality=transcript_quality,
                skip_summary_reason=reason,
            )
            stats["saved"] += 1
            if reason:
                stats["skipped"] += 1
            print(f"[RECOVER] DB 저장 완료: meeting #{meeting_id}", flush=True)
        except Exception as exc:
            stats["failed"] += 1
            print(f"[ERROR] DB 저장 실패 사유: {stem} / {exc}", flush=True)
            write_failure_log(
                event="recover_failed",
                file_name=stem,
                error=str(exc),
                extra={
                    "audio_path": str(audio_path.relative_to(ROOT_DIR)) if audio_path else "",
                    "transcript_path": str(transcript_path.relative_to(ROOT_DIR)) if transcript_path else "",
                },
            )
    log_database_debug_info("[RECOVER]")
    return stats


def _assemble_temp_audio(temp_audio_dir: Path) -> int:
    assembled = 0
    for session_dir in sorted(temp_audio_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        meta_path = session_dir / "meta.json"
        chunk_paths = sorted(session_dir.glob("*.part"))
        if not meta_path.is_file() or not chunk_paths:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            audio_name = meta.get("audio_name") or f"{session_dir.name}.webm"
            audio_path = AUDIO_DIR / Path(audio_name).name
            if audio_path.exists():
                continue
            print(f"[RECOVER] temp_audio 조립 시작: {session_dir.name}", flush=True)
            with audio_path.open("wb") as output:
                for chunk_path in chunk_paths:
                    with chunk_path.open("rb") as chunk_file:
                        shutil.copyfileobj(chunk_file, output)
            assembled += 1
            print(f"[RECOVER] temp_audio 조립 완료: {audio_path.name}", flush=True)
        except Exception as exc:
            print(f"[ERROR] temp_audio 조립 실패: {session_dir.name} / {exc}", flush=True)
            write_failure_log(
                event="temp_audio_assemble_failed",
                file_name=session_dir.name,
                error=str(exc),
            )
    return assembled


def _date_from_stem(stem: str) -> str:
    if len(stem) >= 8 and stem[:8].isdigit():
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
