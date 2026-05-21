from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = ROOT_DIR / "storage" / "audio"
TRANSCRIPT_DIR = ROOT_DIR / "storage" / "transcripts"
PREPROCESSED_DIR = ROOT_DIR / "storage" / "temp_audio" / "preprocessed"
DEFAULT_STT_PROMPT = (
    "한국어 회의 음성입니다. 회의 참석자의 발화를 가능한 정확히 전사하고, "
    "전문 용어와 제품명은 유지해주세요. 문장은 자연스럽게 구분해주세요."
)


@dataclass
class TranscriptionResult:
    text: str
    quality: str
    low_quality: bool
    model: str
    audio_for_stt_path: Path
    preprocessed: bool


def transcribe_audio(audio_path: str | Path) -> str:
    return transcribe_audio_with_metadata(audio_path).text


def transcribe_audio_with_metadata(audio_path: str | Path) -> TranscriptionResult:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다. 음성 전사를 진행할 수 없습니다.")

    audio_path = Path(audio_path)
    model = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    prompt = os.getenv("OPENAI_STT_PROMPT", DEFAULT_STT_PROMPT)
    audio_for_stt_path, preprocessed = prepare_audio_for_stt(audio_path)
    print(
        f"[STT] 변환 시작: {audio_path.name} / model={model} / "
        f"language=ko / preprocessed={preprocessed}",
        flush=True,
    )

    client = OpenAI(api_key=api_key)
    with audio_for_stt_path.open("rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
            language="ko",
            prompt=prompt,
        )

    text = postprocess_transcript(str(transcript))
    if not text:
        raise RuntimeError("STT 결과가 비어 있습니다.")
    quality = assess_transcript_quality(text)
    print(
        f"[STT] 변환 완료: {audio_path.name} / {len(text)}자 / quality={quality}",
        flush=True,
    )
    return TranscriptionResult(
        text=text,
        quality=quality,
        low_quality=quality == "low",
        model=model,
        audio_for_stt_path=audio_for_stt_path,
        preprocessed=preprocessed,
    )


def prepare_audio_for_stt(audio_path: Path) -> tuple[Path, bool]:
    enabled = os.getenv("OPENAI_STT_PREPROCESS_AUDIO", "true").lower() not in {"0", "false", "no"}
    ffmpeg = shutil.which("ffmpeg")
    if not enabled:
        print("[STT] 오디오 전처리 비활성화", flush=True)
        return audio_path, False
    if not ffmpeg:
        print("[STT] ffmpeg를 찾지 못해 원본 audio로 STT 진행", flush=True)
        return audio_path, False

    sample_rate = os.getenv("OPENAI_STT_SAMPLE_RATE", "24000")
    if sample_rate not in {"16000", "24000"}:
        sample_rate = "24000"
    PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = PREPROCESSED_DIR / f"{audio_path.stem}_{sample_rate}hz_mono.wav"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        sample_rate,
        "-f",
        "wav",
        str(wav_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"[STT] 오디오 전처리 완료: {wav_path}", flush=True)
        return wav_path, True
    except subprocess.CalledProcessError as exc:
        print(f"[STT] 오디오 전처리 실패, 원본으로 진행: {exc.stderr[-500:]}", flush=True)
        return audio_path, False


def postprocess_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    text = _remove_repeated_fillers(text)
    text = re.sub(r"\b(\S{1,12})(?:\s+\1){2,}\b", r"\1", text)
    text = re.sub(r"([.!?。！？])\s+", r"\1\n", text)
    text = re.sub(r"(습니다|합니다|했습니다|됩니다|입니다|예요|이에요|거예요|거죠|나요|세요)\s+", r"\1\n", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def assess_transcript_quality(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) < 30:
        return "low"
    words = re.findall(r"[\w가-힣]+", text)
    if words:
        repeated_ratio = 1 - (len(set(words)) / max(len(words), 1))
        if len(words) >= 8 and repeated_ratio > 0.65:
            return "low"
    filler_count = len(re.findall(r"(아+|음+|어+|테스트|하나|둘|셋|들리나요)", text))
    if filler_count >= 5 and len(compact) < 120:
        return "low"
    if re.search(r"(전사|인식).{0,12}(불가|실패|어렵)", text):
        return "low"
    return "ok"


def _remove_repeated_fillers(text: str) -> str:
    filler_patterns = [
        r"(?:아+\s*){3,}",
        r"(?:음+\s*){3,}",
        r"(?:어+\s*){3,}",
        r"(?:테스트\s*){3,}",
    ]
    for pattern in filler_patterns:
        text = re.sub(pattern, "", text)
    return text.strip()
