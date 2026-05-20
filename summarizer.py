from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from openai import OpenAI

from database import save_meeting
from prompts import SUMMARY_SYSTEM_PROMPT, build_summary_prompt


ROOT_DIR = Path(__file__).resolve().parent
RAW_DIR = ROOT_DIR / "storage" / "raw"
SUMMARY_DIR = ROOT_DIR / "storage" / "summaries"
FLOW_DIR = ROOT_DIR / "storage" / "flow"
KST = ZoneInfo("Asia/Seoul")


def process_txt_file(path: str | Path) -> int:
    source_path = Path(path)
    print(f"[SUMMARY] TXT 처리 요청: {source_path}", flush=True)
    if source_path.suffix.lower() != ".txt":
        raise ValueError("TXT 파일만 처리할 수 있습니다.")

    transcript = source_path.read_text(encoding="utf-8-sig").strip()
    return process_transcript_text(
        transcript=transcript,
        source_name=source_path.name,
        source_path=source_path,
        title_seed=source_path.stem,
        file_hash_seed=source_path.name,
    )


def process_transcript_text(
    transcript: str,
    source_name: str,
    source_path: str | Path | None = None,
    title_seed: str | None = None,
    file_hash_seed: str | None = None,
    file_hash_override: str = "",
    meeting_start_time: str = "",
    meeting_end_time: str = "",
    duration_seconds: int | None = None,
    audio_path: str | Path | None = None,
    transcript_path: str | Path | None = None,
    source_type: str = "",
    summary_error_status: str = "error",
    skip_summary_reason: str = "",
) -> int:
    transcript = transcript.strip()
    title_seed = title_seed or Path(source_name).stem
    file_hash = file_hash_override or _hash_text((file_hash_seed or source_name) + "\n" + transcript)
    meeting_date = _extract_date_from_text(source_name, transcript, source_path)
    meeting_time = _extract_time(source_name + "\n" + transcript)
    time_meta = _build_time_metadata(
        source_path=source_path,
        meeting_date=meeting_date,
        meeting_time=meeting_time,
        meeting_start_time=meeting_start_time,
        meeting_end_time=meeting_end_time,
        duration_seconds=duration_seconds,
    )
    meeting_date = time_meta["meeting_date"]
    meeting_time = time_meta["meeting_time"]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    FLOW_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_file_name(title_seed)
    raw_path = RAW_DIR / f"{meeting_date}_{safe_name}.txt"
    summary_path = SUMMARY_DIR / f"{meeting_date}_{safe_name}.md"
    flow_path = FLOW_DIR / f"{meeting_date}_{safe_name}_flow.txt"

    if source_path:
        shutil.copy2(Path(source_path), raw_path)
    else:
        raw_path.write_text(transcript, encoding="utf-8")
    print(f"[SUMMARY] 원문 저장 완료: {raw_path}", flush=True)

    status = "done"
    error_message = ""
    if skip_summary_reason:
        status = "skipped"
        error_message = skip_summary_reason
        print(f"[SUMMARY] 요약 건너뜀: {source_name} / {skip_summary_reason}", flush=True)
        markdown = build_pending_markdown(
            title=title_seed,
            meeting_date=meeting_date,
            meeting_time=meeting_time,
            reason=skip_summary_reason,
            transcript=transcript,
        )
    else:
        try:
            if not transcript:
                raise RuntimeError("빈 TXT 파일입니다.")
            print(f"[SUMMARY] 요약 시작: {source_name}", flush=True)
            markdown = summarize_with_openai(source_name, transcript)
            print(f"[SUMMARY] 요약 완료: {source_name}", flush=True)
        except Exception as exc:
            status = summary_error_status
            error_message = str(exc)
            print(f"[ERROR] 요약 실패, {status} 저장으로 전환: {source_name} / {exc}", flush=True)
            markdown = build_pending_markdown(
                title=title_seed,
                meeting_date=meeting_date,
                meeting_time=meeting_time,
                reason=str(exc),
                transcript=transcript,
            )

    flow_text = extract_section(markdown, "Flow 공유용 요약") or build_flow_fallback(markdown)

    summary_path.write_text(markdown, encoding="utf-8")
    flow_path.write_text(flow_text, encoding="utf-8")
    print(f"[SUMMARY] Markdown 저장 완료: {summary_path}", flush=True)
    print(f"[SUMMARY] Flow 문구 저장 완료: {flow_path}", flush=True)

    title = _extract_title(markdown) or title_seed
    action_items = parse_action_items(markdown)
    key_summary = extract_section(markdown, "핵심 요약")
    decisions = extract_section(markdown, "결정사항")
    risks = extract_section(markdown, "리스크 및 이슈")
    next_actions = extract_section(markdown, "다음 액션")
    search_text = "\n".join(
        [
            title,
            meeting_date,
            meeting_time,
            source_name,
            markdown,
            flow_text,
            time_meta["meeting_start_time"],
            time_meta["meeting_end_time"],
            str(time_meta["duration_seconds"] or ""),
        ]
    )

    relative_audio_path = _relative_path(audio_path)
    relative_transcript_path = _relative_path(transcript_path)
    record = {
        "file_hash": file_hash,
        "title": title,
        "meeting_date": meeting_date,
        "meeting_time": meeting_time,
        "status": status,
        "source_filename": source_name,
        "raw_text": transcript,
        "raw_path": str(raw_path.relative_to(ROOT_DIR)),
        "summary_path": str(summary_path.relative_to(ROOT_DIR)),
        "flow_path": str(flow_path.relative_to(ROOT_DIR)),
        "markdown": markdown,
        "flow_text": flow_text,
        "key_summary": key_summary,
        "decisions": decisions,
        "risks": risks,
        "next_actions": next_actions,
        "action_items": action_items,
        "search_text": search_text,
        "error_message": error_message,
        "source_type": source_type or ("web_recording" if relative_audio_path else "txt"),
        "meeting_start_time": time_meta["meeting_start_time"],
        "meeting_end_time": time_meta["meeting_end_time"],
        "duration_seconds": time_meta["duration_seconds"],
        "audio_path": relative_audio_path,
        "transcript_path": relative_transcript_path,
        "upload_status": "done" if relative_audio_path or source_type == "txt" else "",
        "stt_status": "done" if relative_transcript_path or source_type == "txt" else "pending",
        "summary_status": status,
        "db_status": "done",
        "last_error": error_message,
    }
    print(f"[DB] 저장 시작: {source_name} / status={status}", flush=True)
    try:
        meeting_id = save_meeting(record)
    except Exception as exc:
        print(f"[ERROR] DB 저장 실패: {source_name} / {exc}", flush=True)
        raise
    print(f"[DB] 저장 완료: meeting #{meeting_id} / status={status}", flush=True)
    return meeting_id


def summarize_with_openai(file_name: str, transcript: str) -> str:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. .env 파일을 만들고 API 키를 입력해 주세요."
        )

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": build_summary_prompt(file_name, transcript)},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI API가 빈 응답을 반환했습니다.")
    return content.strip()


def extract_section(markdown: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_action_items(markdown: str) -> list[dict[str, str]]:
    section = extract_section(markdown, "액션 아이템")
    items: list[dict[str, str]] = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] in {"담당자", "---"} or set(cells[0]) <= {"-"}:
            continue
        if all(set(cell) <= {"-", " "} for cell in cells[:3]):
            continue
        owner, task, status = cells[:3]
        if owner or task or status:
            items.append({"owner": owner, "task": task, "status": status})
    return items


def build_flow_fallback(markdown: str) -> str:
    title = _extract_title(markdown) or "회의록"
    summary = extract_section(markdown, "핵심 요약")
    next_actions = extract_section(markdown, "다음 액션")
    return f"[회의록 공유] {title}\n\n{summary}\n\n다음 액션\n{next_actions}".strip()


def build_pending_markdown(
    title: str,
    meeting_date: str,
    meeting_time: str,
    reason: str,
    transcript: str,
) -> str:
    preview = transcript[:1000].strip() or "원문 내용 없음"
    return f"""
# {title}

## 회의 정보
- 날짜: {meeting_date}
- 시간: {meeting_time or "확인 필요"}

## 핵심 요약
- 요약 대기중입니다.
- 실패 사유: {reason}

## 주요 논의 내용
요약 대기중입니다. OpenAI API 키 또는 네트워크 상태를 확인한 뒤 다시 처리해 주세요.

## 결정사항
확인 필요

## 액션 아이템
| 담당자 | 업무 | 상태 |
|---|---|---|
| 확인 필요 | 요약 재시도 | pending |

## 리스크 및 이슈
- 요약 생성 실패: {reason}

## 다음 액션
- `.env`의 OPENAI_API_KEY 설정을 확인합니다.
- 문제가 해결되면 같은 TXT 파일을 다시 저장하거나 `/api/process-file`로 재처리합니다.

## Flow 공유용 요약
[회의록 요약 대기중] {title}
- 날짜: {meeting_date}
- 시간: {meeting_time or "확인 필요"}
- 상태: OpenAI 요약 실패로 pending 저장
- 실패 사유: {reason}

## 원문 미리보기
{preview}
""".strip()


def _extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_date(path: Path, transcript: str) -> str:
    return _extract_date_from_text(path.name, transcript, path)


def _extract_date_from_text(
    source_name: str,
    transcript: str,
    source_path: str | Path | None = None,
) -> str:
    text = source_name + "\n" + transcript[:1000]
    iso = re.search(r"(20\d{2})[-./년 ]\s*(\d{1,2})[-./월 ]\s*(\d{1,2})", text)
    if iso:
        return f"{iso.group(1)}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"

    short = re.search(r"(?<!\d)(\d{1,2})[_./월 ]\s*(\d{1,2})(?:일)?", text)
    if short:
        year = datetime.now(KST).year
        return f"{year}-{int(short.group(1)):02d}-{int(short.group(2)):02d}"

    if source_path:
        return datetime.fromtimestamp(Path(source_path).stat().st_mtime, KST).strftime("%Y-%m-%d")
    return datetime.now(KST).strftime("%Y-%m-%d")


def _extract_time(text: str) -> str:
    match = re.search(r"(오전|오후)?\s*(\d{1,2})\s*(?:시|:)\s*(\d{1,2})?", text)
    if not match:
        return ""
    period = match.group(1) or ""
    hour = int(match.group(2))
    minute = int(match.group(3) or 0)
    if period == "오후" and hour < 12:
        hour += 12
    if period == "오전" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[^\w가-힣.-]+", "_", value, flags=re.UNICODE).strip("_")
    return cleaned or "meeting"


def _build_time_metadata(
    source_path: str | Path | None,
    meeting_date: str,
    meeting_time: str,
    meeting_start_time: str,
    meeting_end_time: str,
    duration_seconds: int | None,
) -> dict[str, Any]:
    start_dt = _parse_client_datetime(meeting_start_time)
    end_dt = _parse_client_datetime(meeting_end_time)

    if start_dt:
        meeting_date = start_dt.strftime("%Y-%m-%d")
        start_time = start_dt.strftime("%H:%M")
    elif meeting_time:
        start_time = meeting_time
    elif source_path:
        modified_at = datetime.fromtimestamp(Path(source_path).stat().st_mtime, KST)
        start_time = modified_at.strftime("%H:%M")
    else:
        start_time = ""

    end_time = end_dt.strftime("%H:%M") if end_dt else ""
    if duration_seconds is None and start_dt and end_dt:
        duration_seconds = max(0, int((end_dt - start_dt).total_seconds()))

    if start_time and end_time:
        meeting_time = f"{start_time} ~ {end_time}"
    elif start_time:
        meeting_time = start_time

    return {
        "meeting_date": meeting_date,
        "meeting_time": meeting_time,
        "meeting_start_time": start_time,
        "meeting_end_time": end_time,
        "duration_seconds": duration_seconds,
    }


def _parse_client_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=KST)
        return parsed.astimezone(KST)
    except ValueError:
        return None


def _relative_path(path: str | Path | None) -> str:
    if not path:
        return ""
    path = Path(path)
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)
