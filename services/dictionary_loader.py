from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parents[1]
DICTIONARY_DIR = ROOT_DIR / "dictionary"
TERMS_XLSX = DICTIONARY_DIR / "terms.xlsx"
TERMS_JSON = DICTIONARY_DIR / "terms.json"
_CACHE: tuple[tuple[float, float], list["DictionaryTerm"]] | None = None


@dataclass(frozen=True)
class DictionaryTerm:
    standard: str
    variants: tuple[str, ...]
    description: str = ""


def load_dictionary(force: bool = False) -> list[DictionaryTerm]:
    global _CACHE
    signature = (_mtime(TERMS_XLSX), _mtime(TERMS_JSON))
    if _CACHE and not force and _CACHE[0] == signature:
        return _CACHE[1]

    terms: dict[str, DictionaryTerm] = {}
    for term in _load_json_terms(TERMS_JSON) + _load_xlsx_terms(TERMS_XLSX):
        if not term.standard:
            continue
        existing = terms.get(term.standard)
        if existing:
            variants = tuple(dict.fromkeys([*existing.variants, *term.variants]))
            description = existing.description or term.description
            terms[term.standard] = DictionaryTerm(term.standard, variants, description)
        else:
            terms[term.standard] = term

    loaded = sorted(terms.values(), key=lambda item: item.standard)
    _CACHE = (signature, loaded)
    print(f"[DICTIONARY] 용어 사전 로드: {len(loaded)}개", flush=True)
    return loaded


def dictionary_prompt_context(limit: int = 80) -> str:
    lines = []
    for term in load_dictionary()[:limit]:
        variants = ", ".join(term.variants[:8])
        description = f" = {term.description}" if term.description else ""
        if variants:
            lines.append(f"- {term.standard}{description} / 유사 표현: {variants}")
        else:
            lines.append(f"- {term.standard}{description}")
    return "\n".join(lines)


def protected_terms() -> list[str]:
    terms = []
    for term in load_dictionary():
        terms.append(term.standard)
    return terms


def replacement_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen_variants: set[str] = set()
    source_terms = _load_json_terms(TERMS_JSON) + _load_xlsx_terms(TERMS_XLSX)
    standards = {term.standard.casefold() for term in source_terms if term.standard}
    for term in source_terms:
        for variant in term.variants:
            key = variant.casefold()
            if not variant or key in seen_variants or key in standards or variant == term.standard:
                continue
            seen_variants.add(key)
            pairs.append((variant, term.standard))
    return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


def _load_json_terms(path: Path) -> list[DictionaryTerm]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = []
    for item in data if isinstance(data, list) else []:
        terms.append(
            DictionaryTerm(
                standard=str(item.get("standard", "")).strip(),
                variants=tuple(_split_variants(item.get("variants", []))),
                description=str(item.get("description", "")).strip(),
            )
        )
    return terms


def _load_xlsx_terms(path: Path) -> list[DictionaryTerm]:
    if not path.is_file():
        return []
    rows = _read_xlsx_rows(path)
    terms: list[DictionaryTerm] = []
    for row in rows:
        cells = [cell.strip() for cell in row]
        if len(cells) < 2:
            continue
        standard = cells[0]
        if not standard or standard == "표준 용어" or standard[0].isdigit():
            continue
        if "회의록" in standard and "용어" in standard:
            continue
        variants = _split_variants(cells[1] if len(cells) > 1 else "")
        description = cells[2] if len(cells) > 2 else ""
        terms.append(DictionaryTerm(standard=standard, variants=tuple(variants), description=description))
    return terms


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", ns):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", ns)))
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row in sheet.findall(".//a:row", ns):
            values: list[str] = []
            for cell in row.findall("a:c", ns):
                value_node = cell.find("a:v", ns)
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                values.append(value or "")
            rows.append(values)
        return rows


def _split_variants(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value).replace("/", ",").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0
