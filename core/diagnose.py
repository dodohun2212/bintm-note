# -*- coding: utf-8 -*-
"""F08 진단 문제 생성(AI 호출 3-A)과 채점(3-B). 상태 판정은 코드가 한다."""
from __future__ import annotations

import json
from typing import Optional

from core import prompts
from core.extract import evidence_pages, pages_to_text
from core.llm import Usage, ask_json
from core.schemas import (STATUS_KNOWN, STATUS_UNKNOWN, STATUS_UNSURE, Concept, Grading, Material, Question,
                          RubricItem)


def status_from_score(score: int) -> str:
    """8점 이상 앎, 4~7 헷갈림, 3 이하 모름 (T-07)."""
    if score >= 8:
        return STATUS_KNOWN
    if score >= 4:
        return STATUS_UNSURE
    return STATUS_UNKNOWN


def _normalize_rubric(items: list[RubricItem]) -> list[RubricItem]:
    """루브릭 합이 10이 아니면 비례로 맞춘다."""
    total = sum(max(0, it.score) for it in items)
    if not items:
        return [RubricItem(point="정답과 일치", score=10)]
    if total == 10:
        return items
    if total <= 0:
        each = 10 // len(items)
        out = [RubricItem(point=it.point, score=each) for it in items]
    else:
        out = [RubricItem(point=it.point, score=int(round(10 * max(0, it.score) / total))) for it in items]
    diff = 10 - sum(it.score for it in out)
    out[0] = RubricItem(point=out[0].point, score=out[0].score + diff)
    return out


def make_question(concept: Concept, material: Material, meta_pages: set[int], usage: Optional[Usage] = None) -> Question:
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("03A", CONCEPT_NAME=concept.name, PAGES=pages_to_text(material, pages))
    raw = ask_json(prompt, name="03A", max_tokens=2000, usage=usage)
    q = Question.model_validate(raw)
    src = [p for p in q.source_pages if p in pages] or pages[:2]
    return q.model_copy(update={"rubric": _normalize_rubric(q.rubric), "source_pages": src})


def empty_grading() -> Grading:
    return Grading(score=0, max=10, rubric_scores=[], status=STATUS_UNKNOWN, error_type="무응답",
                   reason="답을 비워두어 모름으로 표시했어요.")


def grade_answer(concept: Concept, question: Question, answer: str, material: Material, meta_pages: set[int],
                 usage: Optional[Usage] = None) -> Grading:
    """빈 답은 AI 호출 없이 0점 (E-11). 상태는 코드가 점수로 정한다."""
    if not answer or not answer.strip():
        return empty_grading()
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill(
        "03B",
        CONCEPT_NAME=concept.name,
        QUESTION_JSON=json.dumps(question.model_dump(), ensure_ascii=False, indent=1),
        PAGES=pages_to_text(material, pages),
        ANSWER=answer.strip(),
    )
    raw = ask_json(prompt, name="03B", max_tokens=2000, usage=usage)
    g = Grading.model_validate(raw)
    return g.model_copy(update={"max": 10, "status": status_from_score(g.score)})
