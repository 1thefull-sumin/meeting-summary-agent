from __future__ import annotations

from pathlib import Path

from app_helpers import is_short_test_transcript
from summarizer import ROOT_DIR, process_transcript_text
from transcriber import AUDIO_DIR, TRANSCRIPT_DIR


AUDIO_EXTENSIONS = {".webm", ".mp4", ".m4a", ".mp3", ".wav", ".ogg"}


def recover_recordings() -> dict[str, int]:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    audio_by_stem = {
        path.stem: path
        for path in sorted(AUDIO_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    }
    transcript_paths = [
        path
        for path in sorted(TRANSCRIPT_DIR.iterdir())
        if path.is_file() and path.suffix.lower() == ".txt"
    ]

    print(f"[RECOVER] 녹음 파일 확인: {len(audio_by_stem)}개", flush=True)
    print(f"[RECOVER] 전사 파일 확인: {len(transcript_paths)}개", flush=True)

    stats = {"checked": 0, "saved": 0, "failed": 0, "skipped": 0}
    for transcript_path in transcript_paths:
        stats["checked"] += 1
        audio_path = audio_by_stem.get(transcript_path.stem)
        transcript = transcript_path.read_text(encoding="utf-8").strip()
        print(f"[RECOVER] DB 저장 시작: {transcript_path.name}", flush=True)
        try:
            reason = ""
            if is_short_test_transcript(transcript):
                reason = "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다."

            meeting_id = process_transcript_text(
                transcript=transcript,
                source_name=transcript_path.name,
                source_path=transcript_path,
                title_seed=f"복구 녹음 {transcript_path.stem}",
                file_hash_seed=f"recovered-recording:{transcript_path.stem}",
                audio_path=audio_path,
                transcript_path=transcript_path,
                source_type="web_recording",
                summary_error_status="pending",
                skip_summary_reason=reason,
            )
            stats["saved"] += 1
            if reason:
                stats["skipped"] += 1
            print(f"[RECOVER] DB 저장 완료: meeting #{meeting_id}", flush=True)
        except Exception as exc:
            stats["failed"] += 1
            print(f"[ERROR] DB 저장 실패 사유: {transcript_path.name} / {exc}", flush=True)
    return stats
