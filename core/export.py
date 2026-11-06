# -*- coding: utf-8 -*-
"""F10 결과를 마크다운 한 파일로 (6.8 구조)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.schemas import Explanation, Grading, PriorityRow, ScoresResult

NOTICE = "이 결과는 자료와 녹음의 신호를 규칙대로 더한 것으로, 실제 출제를 보장하지 않습니다."


def to_markdown(material_name: str, scores: ScoresResult, grading: dict[str, Grading], priorities: list[PriorityRow],
                explanations: dict[str, Explanation], transcript_used: bool, today: Optional[date] = None) -> str:
    today = today or date.today()
    names = {s.concept_id: s.name for s in scores.scores}
    out = [f"# 빈틈노트 결과 · {material_name} · {today.isoformat()}", ""]
    out.append("녹음/대본 " + ("포함" if transcript_used else "없음 (자료만으로 계산)"))
    out.append("")
    out.append("## 1. 출제 포인트 순위")
    out.append("")
    out.append("| 순위 | 개념 | 출제 가능성 | 근거 |")
    out.append("|---|---|---|---|")
    for i, s in enumerate(scores.scores, start=1):
        why = " · ".join(r.label for r in s.reasons) or "-"
        out.append(f"| {i} | {s.name} | {s.pct}% | {why} |")
    out.append("")
    out.append("## 2. 진단 결과")
    out.append("")
    if grading:
        out.append("| 개념 | 상태 | 점수 | 틀린 유형 | 이유 |")
        out.append("|---|---|---|---|---|")
        for cid, g in grading.items():
            out.append(f"| {names.get(cid, cid)} | {g.status} | {g.score}/10 | {g.error_type or '-'} | {g.reason} |")
    else:
        out.append("진단하지 않음")
    out.append("")
    out.append("## 3. 우선순위")
    out.append("")
    out.append("| 우선순위 | 개념 | 출제 가능성 | 이해 상태 | 우선순위 점수 | 권장 |")
    out.append("|---|---|---|---|---|---|")
    for i, p in enumerate(priorities, start=1):
        out.append(f"| {i} | {p.name} | {p.exam_pct}% | {p.status} | {p.priority} | {p.action} |")
    out.append("")
    out.append("## 4. 보완 설명")
    out.append("")
    if explanations:
        for cid, e in explanations.items():
            out.append(f"### {names.get(cid, cid)}")
            out.append("")
            if e.my_gap:
                out.append(f"- 내가 놓친 점: {e.my_gap}")
            out.append("")
            out.append(e.explanation)
            if e.not_found:
                out.append("")
                out.append(f"> 올린 자료에서 찾지 못함: {e.not_found_note or ''}")
            if e.check_pages:
                out.append("")
                out.append("다시 볼 페이지: " + ", ".join(f"p.{p}" for p in e.check_pages))
            out.append("")
    else:
        out.append("생성된 설명 없음")
        out.append("")
    out.append("---")
    out.append(NOTICE)
    return "\n".join(out) + "\n"
