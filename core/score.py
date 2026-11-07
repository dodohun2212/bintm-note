# -*- coding: utf-8 -*-
"""F07 출제 가능성 점수 (개발기획안 8장). AI를 부르지 않는 순수 함수. 같은 입력이면 항상 같은 결과."""
from __future__ import annotations

from core.schemas import Concept, Reason, ScoreRow, ScoresResult, Utterance

# 8.1 가중치 v0. 바꾸면 버전을 올리고 README에 적는다.
WEIGHTS = {
    "objective": 3.0,        # 학습목표에 있음
    "page": 1.0,             # 본문 쪽당
    "page_cap": 4,           # 본문 쪽수 상한
    "example": 1.5,          # 예제·그림으로 과정 설명
    "exercise": 2.0,         # 연습문제에 포함 (한 번만)
    "emphasis": 1.0,         # × strength/3, 발화마다
    "exam_hint": 1.5,        # × strength/3
    "mistake_warning": 0.7,  # × strength/3
    "exercise_hint": 1.0,    # × strength/3
    "question": 0.5,         # 학우 질문 (F12), 질문마다
    "deferral": -2.5,        # 발화마다
    "skip": -1.0,            # 발화마다
}
WEIGHTS_VERSION = "v0"

UTTERANCE_LABELS = {
    "emphasis": "강조",
    "exam_hint": "시험 암시",
    "mistake_warning": "실수 경고",
    "exercise_hint": "연습문제 지목",
    "question": "학우 질문",
    "deferral": "다음에 다룸",
    "skip": "가볍게 넘어감",
}


def utterance_points(u: Utterance) -> float:
    w = WEIGHTS.get(u.type)
    if w is None:
        return 0.0
    if u.type in ("deferral", "skip", "question"):
        return w
    return w * (u.strength / 3.0)


def score_concept(c: Concept, utterances: list[Utterance], meta_pages: set[int]) -> tuple[float, list[int], list[Reason]]:
    body_pages = [p for p in c.pages if p not in meta_pages]
    raw = 0.0
    reasons: list[Reason] = []
    if c.in_objectives:
        raw += WEIGHTS["objective"]
        reasons.append(Reason(kind="objective", points=WEIGHTS["objective"], label="학습목표"))
    rep = min(len(body_pages), WEIGHTS["page_cap"])
    if body_pages:
        pts = rep * WEIGHTS["page"]
        raw += pts
        reasons.append(Reason(kind="page", points=pts, label=f"본문 {len(body_pages)}쪽"))
    if c.has_example:
        raw += WEIGHTS["example"]
        reasons.append(Reason(kind="example", points=WEIGHTS["example"], label="예제"))
    if c.has_exercise:
        raw += WEIGHTS["exercise"]
        nums = ",".join(str(n) for n in c.exercise_numbers) or "있음"
        reasons.append(Reason(kind="exercise", points=WEIGHTS["exercise"], label=f"연습문제 {nums}"))
    for u in utterances:
        if u.concept_id != c.id:
            continue
        pts = utterance_points(u)
        if pts == 0.0:
            continue
        raw += pts
        short = u.quote if len(u.quote) <= 30 else u.quote[:30] + "…"
        reasons.append(Reason(kind=u.type, points=round(pts, 2), label=f"{UTTERANCE_LABELS.get(u.type, u.type)}: “{short}”", strength=u.strength))
    return raw, body_pages, reasons


def compute_scores(concepts: list[Concept], utterances: list[Utterance], meta_pages: set[int]) -> ScoresResult:
    rows = []
    for c in concepts:
        raw, body_pages, reasons = score_concept(c, utterances, meta_pages)
        raw = max(0.0, raw)  # 8.2-2 음수는 0
        rows.append((c, round(raw, 2), body_pages, reasons))
    max_raw = max((r[1] for r in rows), default=0.0)
    out: list[ScoreRow] = []
    for c, raw, body_pages, reasons in rows:
        pct = int(round(100 * raw / max_raw)) if max_raw > 0 else 0
        out.append(ScoreRow(concept_id=c.id, name=c.name, raw=raw, pct=pct, body_pages=body_pages, reasons=reasons))
    # 8.2-4 정렬: pct 내림차순 → 본문 쪽수 많은 순 → 첫 등장 페이지 빠른 순
    first_page = {c.id: (min(c.pages) if c.pages else 10**6) for c in concepts}
    out.sort(key=lambda r: (-r.pct, -len(r.body_pages), first_page[r.concept_id]))
    return ScoresResult(max_raw=max_raw, scores=out)
