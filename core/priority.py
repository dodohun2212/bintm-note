# -*- coding: utf-8 -*-
"""F09 이해도 숫자화(8.5)와 우선순위(8.6). 순수 함수."""
from __future__ import annotations

from typing import Optional

from core.schemas import (STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, STATUS_UNSURE, Grading, PriorityRow,
                          ScoresResult)

UNDERSTANDING = {
    STATUS_KNOWN: 1.0,
    STATUS_UNSURE: 0.5,
    STATUS_UNKNOWN: 0.0,
    STATUS_NOT_DIAGNOSED: 0.5,
}


def understanding(status: str) -> float:
    return UNDERSTANDING.get(status, 0.5)


def action_for(priority: int) -> str:
    if priority >= 50:
        return "지금 당장"
    if priority >= 20:
        return "다음"
    return "복습만"


def priority_of(exam_pct: int, status: str) -> int:
    return int(round(exam_pct * (1.0 - understanding(status))))


def compute_priorities(scores: ScoresResult, grading: dict[str, Optional[Grading]]) -> list[PriorityRow]:
    rows: list[PriorityRow] = []
    for s in scores.scores:
        g = grading.get(s.concept_id)
        status = g.status if g is not None else STATUS_NOT_DIAGNOSED
        pr = priority_of(s.pct, status)
        rows.append(PriorityRow(concept_id=s.concept_id, name=s.name, exam_pct=s.pct, status=status,
                                understanding=understanding(status), priority=pr, action=action_for(pr)))
    rows.sort(key=lambda r: (-r.priority, -r.exam_pct))
    return rows


def review_split(rows: list[PriorityRow], asked_ids: set[str]) -> tuple[list[PriorityRow], list[PriorityRow]]:
    """'복습만' 묶음을 (헷갈린 점을 적은 개념, 나머지)로 나눈다. 앞쪽은 접지 않고 보인다 (v1.11)."""
    asked = [p for p in rows if p.concept_id in asked_ids]
    rest = [p for p in rows if p.concept_id not in asked_ids]
    return asked, rest
