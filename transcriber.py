from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = ROOT_DIR / "storage" / "audio"
TRANSCRIPT_DIR = ROOT_DIR / "storage" / "transcripts"


def transcribe_audio(audio_path: str | Path) -> str:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다. 음성 전사를 진행할 수 없습니다.")

    audio_path = Path(audio_path)
    model = os.getenv("OPENAI_STT_MODEL", "whisper-1")
    print(f"[STT] 변환 시작: {audio_path.name} / model={model}", flush=True)

    client = OpenAI(api_key=api_key)
    with audio_path.open("rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
            language="ko",
        )

    text = str(transcript).strip()
    if not text:
        raise RuntimeError("STT 결과가 비어 있습니다.")
    print(f"[STT] 변환 완료: {audio_path.name} / {len(text)}자", flush=True)
    return text
