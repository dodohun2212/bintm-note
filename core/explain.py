# -*- coding: utf-8 -*-
"""F09 보완 설명 (AI 호출 4, 프롬프트 04) + 페이지 검사."""
from __future__ import annotations

import json
from typing import Optional

from core import prompts
from core.extract import evidence_pages, pages_to_text
from core.llm import Usage, ask_json
from core.schemas import STATUS_NOT_DIAGNOSED, Concept, Explanation, Grading, Material, Question


def _diagnosis_json(status: str, question: Optional[Question], answer: Optional[str], grading: Optional[Grading]) -> str:
    d = {"status": status}
    if question is not None:
        d["question"] = question.question
        d["model_answer"] = question.answer
    if answer is not None:
        d["student_answer"] = answer
    if grading is not None:
        d["score"] = grading.score
        d["error_type"] = grading.error_type
        d["reason"] = grading.reason
    return json.dumps(d, ensure_ascii=False, indent=1)


def explain(concept: Concept, material: Material, meta_pages: set[int], status: str = STATUS_NOT_DIAGNOSED,
            question: Optional[Question] = None, answer: Optional[str] = None, grading: Optional[Grading] = None,
            usage: Optional[Usage] = None) -> Explanation:
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill(
        "04",
        CONCEPT_NAME=concept.name,
        DIAGNOSIS_JSON=_diagnosis_json(status, question, answer, grading),
        PAGES=pages_to_text(material, pages),
    )
    raw = ask_json(prompt, name="04", max_tokens=2000, usage=usage)
    e = Explanation.model_validate(raw)
    allowed = set(pages)
    return e.model_copy(update={
        "source_pages": [p for p in e.source_pages if p in allowed],
        "check_pages": [p for p in e.check_pages if p in allowed][:4],
    })
