# -*- coding: utf-8 -*-
"""F13 시험 대비 요약 노트 (AI 호출 5, 프롬프트 05).

강의 순서대로 모든 개념을 정리한다. 중요한 개념일수록 자세히 쓴다.
- 자세히: '지금 당장'이거나, 출제 가능성이 높거나(ESSAY_MIN_PCT 이상), 진단에서 틀린(모름) 개념
- 보통: '다음'이거나 헷갈린 개념
- 짧게: 나머지. AI를 부르지 않고 개념 추출(호출 1)에서 받은 한 줄 요약을 쓴다 (비용 절약).
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from config import DIAG_MIN_PCT, ESSAY_MIN_PCT, NOTE_MAX_TOKENS
from core import prompts
from core.extract import evidence_pages, pages_to_text
from core.llm import Usage, ask_json
from core.schemas import (DETAIL_FULL, DETAIL_MID, DETAIL_SHORT, STATUS_UNKNOWN, STATUS_UNSURE, Concept, Grading,
                          Material, NoteSection, PriorityRow, Utterance)

NOW, NEXT = "지금 당장", "다음"


def note_detail(p: PriorityRow) -> str:
    """개념마다 요약을 얼마나 자세히 쓸지. 코드가 정한다."""
    if p.action == NOW or p.exam_pct >= ESSAY_MIN_PCT or (p.status == STATUS_UNKNOWN and p.exam_pct >= DIAG_MIN_PCT):
        return DETAIL_FULL
    if p.action == NEXT or p.status == STATUS_UNSURE:
        return DETAIL_MID
    return DETAIL_SHORT


def lecture_order(concepts: Sequence[Concept], meta_pages: set[int]) -> list[Concept]:
    """강의 순서 = 본문에 처음 나오는 쪽 순서 (메타 페이지 제외). 본문 쪽이 없으면 맨 뒤. 같으면 원래 순서."""
    def first(c: Concept) -> int:
        body = [p for p in c.pages if p not in meta_pages]
        return min(body) if body else 10 ** 6

    return [c for _, c in sorted(enumerate(concepts), key=lambda t: (first(t[1]), t[0]))]


def short_section(concept: Concept, meta_pages: set[int]) -> NoteSection:
    """'짧게' 개념. AI 호출 없이 개념 추출 때 받은 한 줄 요약을 쓴다."""
    pages = evidence_pages(concept.pages, meta_pages)[:2]
    return NoteSection(concept_id=concept.id, detail=DETAIL_SHORT, summary=concept.summary or concept.name,
                       source_pages=pages, from_ai=False)


def professor_quotes(concept_id: str, utterances: Sequence[Utterance], limit: int = 3) -> list[Utterance]:
    """그 개념에 대한 교수님 말. 강한 것부터 limit개 (같은 말은 한 번)."""
    seen, out = set(), []
    for u in sorted((u for u in utterances if u.concept_id == concept_id), key=lambda u: -u.strength):
        if u.quote in seen:
            continue
        seen.add(u.quote)
        out.append(u)
    return out[:limit]


def _concept_json(concept: Concept, p: PriorityRow, utterances: Sequence[Utterance],
                  grading: Optional[Grading]) -> str:
    d: dict = {"name": concept.name, "exam_pct": p.exam_pct, "priority_tier": p.action, "status": p.status}
    if concept.objective_quote:
        d["learning_objective"] = concept.objective_quote
    quotes = professor_quotes(concept.id, utterances, limit=5)
    if quotes:
        d["professor"] = [{"type": u.type, "quote": u.quote} for u in quotes]
    if grading is not None:
        d["diagnosis"] = {"score": grading.score, "error_type": grading.error_type, "reason": grading.reason}
    return json.dumps(d, ensure_ascii=False, indent=1)


def make_note_section(concept: Concept, material: Material, meta_pages: set[int], p: PriorityRow,
                      utterances: Sequence[Utterance] = (), grading: Optional[Grading] = None,
                      usage: Optional[Usage] = None) -> NoteSection:
    detail = note_detail(p)
    if detail == DETAIL_SHORT:
        return short_section(concept, meta_pages)
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("05", CONCEPT_NAME=concept.name, DETAIL=detail,
                          CONCEPT_JSON=_concept_json(concept, p, utterances, grading),
                          PAGES=pages_to_text(material, pages))
    raw = ask_json(prompt, name="05", max_tokens=NOTE_MAX_TOKENS, usage=usage)
    sec = NoteSection.model_validate({**raw, "concept_id": concept.id, "detail": detail})
    allowed = set(pages)
    limit = 5 if detail == DETAIL_FULL else 3
    return sec.model_copy(update={
        "source_pages": [n for n in sec.source_pages if n in allowed] or pages[:2],
        "key_points": [k for k in sec.key_points if str(k).strip()][:limit],
        "pitfalls": [k for k in sec.pitfalls if str(k).strip()][:2],
        "from_ai": True,
    })
