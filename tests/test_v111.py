# -*- coding: utf-8 -*-
"""T-51~T-53 (v1.11): 분석 중 안내 유지, 헷갈린 점을 적은 '복습만' 개념 펼치기, 채점 실패 원인별 문구."""
from pathlib import Path

from core.priority import review_split
from core.schemas import PriorityRow

APP = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")


def _row(cid: str) -> PriorityRow:
    return PriorityRow(concept_id=cid, name=cid, exam_pct=30, status="헷갈림", understanding=0.5, priority=15,
                       action="복습만")


def test_t51_analysis_notices_survive_rerun():
    # 분석 중 안내는 st.warning으로 바로 그리지 않고 세션에 담아 ② 위에 그린다 (rerun으로 사라지지 않게)
    body = APP.split("def run_analysis", 1)[1].split("def screen_s01", 1)[0]
    assert "notices.append" in body and "st.session_state.notices = notices" in body
    assert "st.warning(" not in body and "st.info(" not in body
    for code in ("(E-05)", "(E-10)", "(E-13)"):
        assert code in body
    s02 = APP.split("def screen_s02", 1)[1].split("def ", 1)[0]
    assert "st.session_state.notices" in s02
    assert "notices=[]" in APP.split("DEFAULTS = dict(", 1)[1].split(")", 1)[0]


def test_t52_review_split_keeps_confusion_open():
    rows = [_row("a"), _row("b"), _row("c")]
    asked, rest = review_split(rows, {"b"})
    assert [p.concept_id for p in asked] == ["b"] and [p.concept_id for p in rest] == ["a", "c"]
    asked, rest = review_split(rows, set())
    assert asked == [] and len(rest) == 3
    assert "review_split(rows" in APP


def test_t53_grade_failure_shows_cause():
    s03 = APP.split("def screen_s03", 1)[1].split("\ndef ", 1)[0]
    i = s03.index("문제를 채점하지 못했어요")
    assert "grade_cause" in s03[i - 200:i + 200] and "(E-08)\")" not in s03[i:i + 200]
    assert "st.session_state.grade_cause = error_message(" in APP
