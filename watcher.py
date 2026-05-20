import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers.polling import PollingObserver

from summarizer import process_txt_file


ROOT_DIR = Path(__file__).resolve().parent
INPUT_DIR = ROOT_DIR / "input" / "clova_txt"


class ClovaTxtHandler(FileSystemEventHandler):
    def on_created(self, event) -> None:
        self._handle_path(Path(event.src_path), event.is_directory, "새 TXT 감지")

    def on_modified(self, event) -> None:
        self._handle_path(Path(event.src_path), event.is_directory, "TXT 변경 감지")

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        self._handle_path(Path(event.dest_path), event.is_directory, "TXT 이동 감지")

    def _handle_path(self, path: Path, is_directory: bool, reason: str) -> None:
        if is_directory or path.suffix.lower() != ".txt":
            return
        print(f"[WATCHER] {reason}: {path}", flush=True)
        process_when_ready(path)


def process_when_ready(path: Path, retries: int = 10) -> None:
    last_size = -1
    for _ in range(retries):
        if not path.exists():
            time.sleep(0.5)
            continue
        size = path.stat().st_size
        if size == last_size and size > 0:
            try:
                print(f"[WATCHER] 처리 시작: {path.name}", flush=True)
                meeting_id = process_txt_file(path)
                print(f"[WATCHER] 처리 완료: {path.name} -> meeting #{meeting_id}", flush=True)
            except Exception as exc:
                print(f"[ERROR] 처리 실패: {path.name} / {exc}", flush=True)
            return
        last_size = size
        time.sleep(0.5)
    print(f"[ERROR] 파일 쓰기가 끝나지 않아 건너뜀: {path}", flush=True)


def process_existing_files() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(INPUT_DIR.glob("*.txt"))
    print(f"[WATCHER] 기존 TXT 확인: {INPUT_DIR} / {len(paths)}개", flush=True)
    for path in paths:
        print(f"[WATCHER] 기존 TXT 처리 대상: {path}", flush=True)
        process_when_ready(path, retries=2)


def start_watcher() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[WATCHER] 감시 폴더: {INPUT_DIR}", flush=True)
    process_existing_files()
    observer = PollingObserver(timeout=1)
    observer.schedule(ClovaTxtHandler(), str(INPUT_DIR), recursive=False)
    observer.start()
    print(f"[WATCHER] 감시 시작", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[WATCHER] 감시 종료 요청", flush=True)
        observer.stop()
    observer.join()
