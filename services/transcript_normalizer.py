from __future__ import annotations

import re

from services.dictionary_loader import replacement_pairs


def normalize_transcript_terms(text: str) -> str:
    normalized = text or ""
    for variant, standard in replacement_pairs():
        normalized = _replace_term(normalized, variant, standard)
    return normalized


def normalize_transcript(text: str) -> str:
    normalized = normalize_transcript_terms(text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _replace_term(text: str, variant: str, standard: str) -> str:
    if re.search(r"[A-Za-z0-9]", variant):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])", re.IGNORECASE)
    else:
        particle_or_boundary = r"(?=$|[\s,.;:!?)]|은|는|이|가|을|를|랑|와|과|도|에서|으로|로|에|의|하고|부터|까지)"
        pattern = re.compile(rf"(?<![\w가-힣]){re.escape(variant)}{particle_or_boundary}")
    return pattern.sub(standard, text)
