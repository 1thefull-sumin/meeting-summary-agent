from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app_helpers import is_short_test_transcript
from database import create_uploaded_meeting, update_meeting_processing_state
from failure_log import write_failure_log
from summarizer import ROOT_DIR, process_transcript_text
from transcriber import AUDIO_DIR, TRANSCRIPT_DIR, transcribe_audio


INPUT_ROOT = ROOT_DIR / "input"
CLOVA_TXT_DIR = INPUT_ROOT / "clova_txt"
CLOVA_AUDIO_DIR = INPUT_ROOT / "clova_audio"
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".webm"}
KST = ZoneInfo("Asia/Seoul")


def ensure_clova_dirs() -> None:
    for directory in (
        CLOVA_TXT_DIR,
        CLOVA_AUDIO_DIR,
        CLOVA_TXT_DIR / "processed",
        CLOVA_TXT_DIR / "failed",
        CLOVA_AUDIO_DIR / "processed",
        CLOVA_AUDIO_DIR / "failed",
    ):
        directory.mkdir(parents=True, exist_ok=True)


def process_clova_stem(stem: str) -> int | None:
    ensure_clova_dirs()
    txt_path = _find_txt(stem)
    audio_path = _find_audio(stem)
    if not txt_path and not audio_path:
        return None

    print(
        f"[CLOVA] 처리 시작: stem={stem} / "
        f"txt={txt_path.name if txt_path else '-'} / "
        f"audio={audio_path.name if audio_path else '-'}",
        flush=True,
    )
    try:
        meeting_id = process_clova_files(txt_path=txt_path, audio_path=audio_path)
        _move_input_file(txt_path, "processed")
        _move_input_file(audio_path, "processed")
        print(f"[CLOVA] 처리 완료: stem={stem} -> meeting #{meeting_id}", flush=True)
        return meeting_id
    except Exception as exc:
        _move_input_file(txt_path, "failed")
        _move_input_file(audio_path, "failed")
        print(f"[ERROR] 클로바 처리 실패: stem={stem} / {exc}", flush=True)
        write_failure_log(
            event="clova_import_failed",
            file_name=stem,
            error=str(exc),
            extra={
                "txt_path": str(txt_path.relative_to(ROOT_DIR)) if txt_path else "",
                "audio_path": str(audio_path.relative_to(ROOT_DIR)) if audio_path else "",
            },
        )
        raise


def process_clova_files(txt_path: Path | None, audio_path: Path | None) -> int:
    if not txt_path and not audio_path:
        raise ValueError("TXT 또는 audio 파일이 필요합니다.")

    file_hash = _content_hash(txt_path, audio_path)
    stored_audio_path = _store_audio(audio_path) if audio_path else None
    transcript_path = None
    uploaded_meeting_id = None

    if audio_path and not txt_path:
        created_at = _source_created_at(audio_path)
        uploaded_meeting_id = create_uploaded_meeting(
            {
                "file_hash": file_hash,
                "title": f"클로바 녹음 {audio_path.stem}",
                "meeting_date": created_at.date().isoformat(),
                "meeting_start_time": created_at.strftime("%H:%M"),
                "audio_path": str(stored_audio_path.relative_to(ROOT_DIR)),
                "source_type": "clova",
                "source_filename": audio_path.name,
            }
        )
        print(f"[CLOVA] audio-only uploaded row 저장 완료: meeting #{uploaded_meeting_id}", flush=True)

    if txt_path:
        transcript = txt_path.read_text(encoding="utf-8-sig").strip()
        source_name = txt_path.name
        source_path = txt_path
        title_seed = txt_path.stem
    else:
        print(f"[CLOVA] audio-only STT 시작: {audio_path.name}", flush=True)
        try:
            transcript = transcribe_audio(stored_audio_path)
        except Exception as exc:
            if uploaded_meeting_id:
                update_meeting_processing_state(
                    uploaded_meeting_id,
                    status="error",
                    stt_status="error",
                    summary_status="pending",
                    last_error=str(exc),
                    retry_increment=True,
                )
            raise
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        transcript_path = TRANSCRIPT_DIR / f"{stored_audio_path.stem}.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"[CLOVA] audio-only 전사 저장 완료: {transcript_path}", flush=True)
        source_name = transcript_path.name
        source_path = transcript_path
        title_seed = audio_path.stem

    if txt_path and stored_audio_path:
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        transcript_path = TRANSCRIPT_DIR / f"{stored_audio_path.stem}.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"[CLOVA] TXT transcript 저장 완료: {transcript_path}", flush=True)

    reason = ""
    if is_short_test_transcript(transcript):
        reason = "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다."

    created_at = _source_created_at(txt_path or audio_path)
    meeting_start_time = created_at.strftime("%H:%M")

    return process_transcript_text(
        transcript=transcript,
        source_name=source_name,
        source_path=source_path,
        title_seed=title_seed,
        file_hash_seed=f"clova:{(txt_path or audio_path).stem}",
        file_hash_override=file_hash,
        meeting_start_time=meeting_start_time,
        audio_path=stored_audio_path,
        transcript_path=transcript_path,
        source_type="clova",
        skip_summary_reason=reason,
    )


def pending_stems() -> list[str]:
    ensure_clova_dirs()
    stems = {path.stem for path in CLOVA_TXT_DIR.glob("*.txt")}
    stems.update(path.stem for path in CLOVA_AUDIO_DIR.iterdir() if _is_audio(path))
    return sorted(stems)


def _find_txt(stem: str) -> Path | None:
    path = CLOVA_TXT_DIR / f"{stem}.txt"
    return path if path.is_file() else None


def _find_audio(stem: str) -> Path | None:
    for suffix in sorted(SUPPORTED_AUDIO_EXTENSIONS):
        path = CLOVA_AUDIO_DIR / f"{stem}{suffix}"
        if path.is_file():
            return path
    return None


def _is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _store_audio(audio_path: Path | None) -> Path | None:
    if not audio_path:
        return None
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    digest = _hash_file(audio_path)[:12]
    safe_name = _safe_name(audio_path.stem)
    target = AUDIO_DIR / f"{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}_clova_{digest}_{safe_name}{audio_path.suffix.lower()}"
    shutil.copy2(audio_path, target)
    print(f"[CLOVA] audio 저장 완료: {target}", flush=True)
    return target


def _content_hash(txt_path: Path | None, audio_path: Path | None) -> str:
    digest = hashlib.sha256()
    for path in (txt_path, audio_path):
        if not path:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _move_input_file(path: Path | None, bucket: str) -> None:
    if not path or not path.exists():
        return
    target_dir = path.parent / bucket
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    shutil.move(str(path), str(target))
    print(f"[CLOVA] {bucket} 이동: {target}", flush=True)


def _source_created_at(path: Path | None) -> datetime:
    if not path:
        return datetime.now(KST)
    return datetime.fromtimestamp(path.stat().st_ctime, KST)


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "clova_audio"
