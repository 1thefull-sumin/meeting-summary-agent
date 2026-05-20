from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers.polling import PollingObserver

from clova_importer import (
    CLOVA_AUDIO_DIR,
    CLOVA_TXT_DIR,
    SUPPORTED_AUDIO_EXTENSIONS,
    ensure_clova_dirs,
    pending_stems,
    process_clova_stem,
)


INPUT_DIR = CLOVA_TXT_DIR
INPUT_AUDIO_DIR = CLOVA_AUDIO_DIR
_scheduled: set[str] = set()
_lock = threading.Lock()


class ClovaImportHandler(FileSystemEventHandler):
    def on_created(self, event) -> None:
        self._handle_path(Path(event.src_path), event.is_directory, "새 파일 감지")

    def on_modified(self, event) -> None:
        self._handle_path(Path(event.src_path), event.is_directory, "파일 변경 감지")

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        self._handle_path(Path(event.dest_path), event.is_directory, "파일 이동 감지")

    def _handle_path(self, path: Path, is_directory: bool, reason: str) -> None:
        if is_directory or not _is_supported(path):
            return
        if path.parent.name in {"processed", "failed"}:
            return
        print(f"[WATCHER] {reason}: {path}", flush=True)
        schedule_stem(path.stem)


def schedule_stem(stem: str, delay_seconds: float = 2.0) -> None:
    with _lock:
        if stem in _scheduled:
            return
        _scheduled.add(stem)

    def run() -> None:
        try:
            time.sleep(delay_seconds)
            process_when_ready(stem)
        finally:
            with _lock:
                _scheduled.discard(stem)

    threading.Thread(target=run, daemon=True).start()


def process_when_ready(stem: str, retries: int = 10) -> None:
    for _ in range(retries):
        paths = _candidate_paths(stem)
        if paths and all(_is_stable(path) for path in paths):
            try:
                process_clova_stem(stem)
            except Exception:
                pass
            return
        time.sleep(0.5)
    print(f"[ERROR] 파일 쓰기가 끝나지 않아 건너뜀: {stem}", flush=True)


def process_existing_files() -> None:
    ensure_clova_dirs()
    stems = pending_stems()
    print(
        f"[WATCHER] 기존 파일 확인: txt={CLOVA_TXT_DIR} / audio={CLOVA_AUDIO_DIR} / {len(stems)}개 stem",
        flush=True,
    )
    for stem in stems:
        print(f"[WATCHER] 기존 처리 대상: {stem}", flush=True)
        process_when_ready(stem, retries=2)


def start_watcher() -> None:
    ensure_clova_dirs()
    print(f"[WATCHER] TXT 감시 폴더: {CLOVA_TXT_DIR}", flush=True)
    print(f"[WATCHER] audio 감시 폴더: {CLOVA_AUDIO_DIR}", flush=True)
    process_existing_files()
    observer = PollingObserver(timeout=1)
    handler = ClovaImportHandler()
    observer.schedule(handler, str(CLOVA_TXT_DIR), recursive=False)
    observer.schedule(handler, str(CLOVA_AUDIO_DIR), recursive=False)
    observer.start()
    print("[WATCHER] 감시 시작", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[WATCHER] 감시 종료 요청", flush=True)
        observer.stop()
    observer.join()


def _candidate_paths(stem: str) -> list[Path]:
    paths: list[Path] = []
    txt_path = CLOVA_TXT_DIR / f"{stem}.txt"
    if txt_path.is_file():
        paths.append(txt_path)
    for suffix in SUPPORTED_AUDIO_EXTENSIONS:
        audio_path = CLOVA_AUDIO_DIR / f"{stem}{suffix}"
        if audio_path.is_file():
            paths.append(audio_path)
    return paths


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() == ".txt" or path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _is_stable(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    size = path.stat().st_size
    time.sleep(0.2)
    return path.exists() and path.stat().st_size == size
