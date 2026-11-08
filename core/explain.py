# -*- coding: utf-8 -*-
"""F09 보완 설명 (AI 호출 4, 프롬프트 04) + 페이지 검사."""
from __future__ import annotations

import json
from typing import Optional

from config import AI_MAX_TOKENS, CONFUSION_MAX_CHARS
from core import prompts
from core.diagnose import CIRCLED
from core.figure import figure_text
from core.extract import evidence_pages, pages_to_text
from core.llm import Usage, ask_json
from core.schemas import STATUS_NOT_DIAGNOSED, Concept, Explanation, Grading, Material, Question


def _diagnosis_json(status: str, question: Optional[Question], answer: Optional[str], grading: Optional[Grading]) -> str:
    d = {"status": status}
    if question is not None:
        d["question_type"] = question.kind
        d["question"] = question.question
        if question.figure is not None:
            d["figure"] = figure_text(question.figure)
        if question.is_mcq:
            d["choices"] = [f"{CIRCLED[i]} {c}" for i, c in enumerate(question.choices)]
            d["model_answer"] = f"{CIRCLED[question.answer_index or 0]} {question.answer}"
            if question.explanation:
                d["model_answer"] += " / 해설: " + question.explanation
        else:
            d["model_answer"] = question.answer
    if answer is not None:
        d["student_answer"] = answer
    if grading is not None:
        d["score"] = grading.score
        d["error_type"] = grading.error_type
        d["reason"] = grading.reason
    return json.dumps(d, ensure_ascii=False, indent=1)


def clean_confusion(text: Optional[str]) -> str:
    """학생이 적은 "헷갈린 점"을 프롬프트에 넣을 수 있게 다듬는다 (v1.4).

    앞뒤 공백을 지우고 글자 수를 자르며, 꺾쇠(<, >)는 비슷한 모양의 다른 글자로 바꿔 태그를 닫거나 열 수 없게 한다.
    """
    t = " ".join(str(text or "").split())[:CONFUSION_MAX_CHARS]
    return t.replace("<", "‹").replace(">", "›")


def explain(concept: Concept, material: Material, meta_pages: set[int], status: str = STATUS_NOT_DIAGNOSED,
            question: Optional[Question] = None, answer: Optional[str] = None, grading: Optional[Grading] = None,
            usage: Optional[Usage] = None, confusion: str = "") -> Explanation:
    """confusion: 객관식에서 '확신 없이 골랐어요'를 체크하고 학생이 직접 적은 헷갈린 점 (없으면 빈 글)."""
    pages = evidence_pages(concept.pages, meta_pages)
    confusion = clean_confusion(confusion)
    prompt = prompts.fill(
        "04",
        CONCEPT_NAME=concept.name,
        DIAGNOSIS_JSON=_diagnosis_json(status, question, answer, grading),
        CONFUSION=confusion or "(없음)",
        PAGES=pages_to_text(material, pages),
    )
    raw = ask_json(prompt, name="04", max_tokens=AI_MAX_TOKENS, usage=usage)
    e = Explanation.model_validate(raw)
    allowed = set(pages)
    reply = (e.confusion_reply or "").strip()
    return e.model_copy(update={
        "source_pages": [p for p in e.source_pages if p in allowed],
        "check_pages": [p for p in e.check_pages if p in allowed][:4],
        "confusion_reply": reply if confusion and reply else None,   # 적은 게 없으면 답도 버린다
    })
