from __future__ import annotations

import re

from services.dictionary_loader import protected_terms
from services.transcript_normalizer import normalize_transcript_terms


def postprocess_summary_markdown(markdown: str) -> str:
    processed = normalize_transcript_terms(markdown or "")
    processed = _compact_repeated_blank_lines(processed)
    return processed.strip()


def protected_terms_context() -> str:
    terms = protected_terms()
    if not terms:
        return ""
    return ", ".join(terms[:80])


def _compact_repeated_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)
