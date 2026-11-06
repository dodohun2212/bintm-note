# -*- coding: utf-8 -*-
"""F05 개념 추출 (AI 호출 1, 프롬프트 01) + 결과 검사."""
from __future__ import annotations

from typing import Optional

from core import prompts
from core.extract import meta_pages_heuristic, pages_to_text
from core.llm import Usage, ask_json
from core.schemas import Concept, ConceptsResult, Material


class NoConceptsError(Exception):
    """E-09 개념 0개."""


def _clamp_pages(pages: list, n_pages: int) -> list[int]:
    out = []
    for p in pages:
        try:
            p = int(p)
        except (TypeError, ValueError):
            continue
        if 1 <= p <= n_pages and p not in out:
            out.append(p)
    return sorted(out)


def validate_concepts(raw: dict, material: Material) -> ConceptsResult:
    """AI 결과를 6.2 형식으로 검사: 페이지 범위, id 중복, 이름 중복, meta_pages 보정."""
    result = ConceptsResult.model_validate(raw)
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    cleaned: list[Concept] = []
    for i, c in enumerate(result.concepts, start=1):
        cid = c.id or f"c{i}"
        while cid in seen_ids:
            cid = f"{cid}_{i}"
        name = c.name.strip()
        if not name or name in seen_names:
            continue
        seen_ids.add(cid)
        seen_names.add(name)
        c = c.model_copy(update={"id": cid, "name": name, "pages": _clamp_pages(c.pages, material.n_pages)})
        cleaned.append(c)
    if not cleaned:
        raise NoConceptsError("개념을 찾지 못함")
    meta = set(_clamp_pages(result.meta_pages, material.n_pages))
    meta |= meta_pages_heuristic(material)
    for p in (result.objectives_page, result.exercise_page):
        if p and 1 <= int(p) <= material.n_pages:
            meta.add(int(p))
    return result.model_copy(update={"concepts": cleaned, "meta_pages": sorted(meta)})


def extract_concepts(material: Material, usage: Optional[Usage] = None) -> ConceptsResult:
    prompt = prompts.fill("01", MATERIAL=pages_to_text(material))
    raw = ask_json(prompt, name="01", max_tokens=8000, thinking=True, usage=usage)
    return validate_concepts(raw, material)
