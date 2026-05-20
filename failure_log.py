from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parent
ERROR_LOG_DIR = ROOT_DIR / "storage" / "error_logs"
FAILED_MEETINGS_LOG = ERROR_LOG_DIR / "failed_meetings.jsonl"
KST = ZoneInfo("Asia/Seoul")


def write_failure_log(
    *,
    event: str,
    file_name: str = "",
    error: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "failed_at": datetime.now(KST).isoformat(timespec="seconds"),
        "event": event,
        "file_name": file_name,
        "error": error,
        "extra": extra or {},
    }
    with FAILED_MEETINGS_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
