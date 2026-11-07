# 객관식 진단: 응답 검사, 보기 섞기, 코드 채점, 문제 형식 고르기, 진단 대상 고르기 (AI 호출 없음)
import json
import os
from pathlib import Path

import pytest

os.environ["BINTM_FAKE_AI"] = "1"

from core import diagnose, prompts
from core.diagnose import (MODE_ESSAY, MODE_MCQ, MODE_MIX, check_mcq, diag_targets, grade_mcq, mcq_answer_text,
                           question_kind, shuffle_choices)
from core.explain import _diagnosis_json
from core.schemas import QTYPE_ESSAY, QTYPE_MCQ, Question, ScoreRow, ScoresResult

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
RAW = {"question": "삭제 후 내려갈 때 비교하는 대상은?", "choices": ["① 더 큰 자식", "② 왼쪽 자식", "③ 부모", "④ 형제"],
       "answer_index": 0, "explanation": "더 큰 자식과 비교한다 (p.16).", "source_pages": [16]}


def _mcq(answer_index=2):
    return Question(question="q", answer="c", kind=QTYPE_MCQ, choices=["a", "b", "c", "d"], answer_index=answer_index)


def test_check_mcq_strips_numbers_and_validates():
    q, choices, idx, exp, pages = check_mcq(RAW)
    assert choices == ["더 큰 자식", "왼쪽 자식", "부모", "형제"] and idx == 0 and pages == [16]
    for bad in ({**RAW, "choices": RAW["choices"][:3]}, {**RAW, "answer_index": 4}, {**RAW, "answer_index": None},
                {**RAW, "choices": ["a", "a", "b", "c"]}, {**RAW, "question": ""}):
        with pytest.raises(ValueError):
            check_mcq(bad)


def test_shuffle_keeps_right_answer_and_is_stable():
    choices = ["정답", "오답1", "오답2", "오답3"]
    a, ia = shuffle_choices(choices, 0, "seed")
    b, ib = shuffle_choices(choices, 0, "seed")
    assert (a, ia) == (b, ib) and a[ia] == "정답" and sorted(a) == sorted(choices)
    # 여러 문제에서 정답 위치가 한 곳에 몰리지 않는다
    positions = {shuffle_choices(choices, 0, f"s{i}")[1] for i in range(40)}
    assert len(positions) >= 3


def test_grade_mcq_uses_confidence():
    q = _mcq(2)
    assert grade_mcq(q, 2).status == "앎" and grade_mcq(q, 2).score == 10
    g = grade_mcq(q, 2, guessed=True)
    assert g.status == "헷갈림" and g.score == 5 and g.error_type == "찍어서 맞힘"
    g = grade_mcq(q, 1)
    assert g.status == "모름" and g.error_type == "오답" and g.reason == "②번을 골랐는데 정답은 ③번이에요."
    g = grade_mcq(q, None)
    assert g.status == "모름" and g.error_type == "무응답" and "고르지 않아" in g.reason
    g = grade_mcq(q, -1)
    assert g.status == "모름" and g.error_type == "무응답" and "모르겠어요" in g.reason
    assert mcq_answer_text(q, 1, guessed=True) == "② b (확신 없이 고름)" and mcq_answer_text(q, None) == ""


def test_question_kind_modes():
    assert question_kind(80) == QTYPE_ESSAY and question_kind(50) == QTYPE_ESSAY and question_kind(49) == QTYPE_MCQ
    assert question_kind(90, MODE_MCQ) == QTYPE_MCQ and question_kind(10, MODE_ESSAY) == QTYPE_ESSAY
    assert question_kind(30, MODE_MIX) == QTYPE_MCQ


def test_diag_targets_threshold():
    rows = [ScoreRow(concept_id=f"c{p}", name=str(p), raw=p, pct=p, body_pages=[], reasons=[]) for p in (100, 40, 20, 19, 0)]
    assert diag_targets(ScoresResult(max_raw=100, scores=rows)) == ["c100", "c40", "c20"]


def test_make_question_falls_back_to_essay_when_mcq_is_broken(monkeypatch):
    from core.extract import extract_material
    from core.schemas import Concept

    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concept = Concept(id="c1", name="힙의 삭제 연산", pages=[16, 17])
    q = diagnose.make_question(concept, material, set(), kind=QTYPE_MCQ)
    assert q.is_mcq and q.choices[q.answer_index] == q.answer
    assert "(정답)" in q.answer  # 가짜 응답의 정답 보기가 섞인 뒤에도 정답 위치를 따라감

    real = diagnose.ask_json
    monkeypatch.setattr(diagnose, "ask_json", lambda p, **kw: {"question": "x", "choices": ["a"], "answer_index": 0}
                        if kw["name"] == "03C" else real(p, **kw))
    q = diagnose.make_question(concept, material, set(), kind=QTYPE_MCQ)
    assert q.kind == QTYPE_ESSAY and sum(r.score for r in q.rubric) == 10


def test_explain_gets_mcq_context():
    q = _mcq(2).model_copy(update={"explanation": "해설"})
    d = json.loads(_diagnosis_json("모름", q, mcq_answer_text(q, 1), grade_mcq(q, 1)))
    assert d["question_type"] == "객관식" and len(d["choices"]) == 4
    assert d["model_answer"].startswith("③ c") and "해설" in d["model_answer"] and d["student_answer"] == "② b"


def test_prompt_03c_placeholders():
    assert prompts.placeholders("03C") == {"CONCEPT_NAME", "PAGES", "OTHER_CONCEPTS"}
    assert prompts.placeholders("03A") == {"CONCEPT_NAME", "PAGES", "OTHER_CONCEPTS"}


def test_question_prompts_list_other_concepts(monkeypatch):
    """T-23: 문제를 만들 때 함께 진단하는 다른 개념 이름이 프롬프트에 들어가고, 자기 이름은 빠진다."""
    from core.extract import extract_material
    from core.schemas import Concept

    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concept = Concept(id="c1", name="힙의 정의(최대 힙·최소 힙)", pages=[14])
    seen = {}
    real = diagnose.ask_json

    def spy(prompt, **kw):
        seen[kw["name"]] = prompt
        return real(prompt, **kw)

    monkeypatch.setattr(diagnose, "ask_json", spy)
    others = ["완전 이진 트리의 배열 표현", "힙의 삽입 연산"]
    diagnose.make_question(concept, material, set(), kind=QTYPE_MCQ, others=others)
    diagnose.make_question(concept, material, set(), kind=QTYPE_ESSAY, others=others)
    for name in ("03C", "03A"):
        block = seen[name].split("\n<other_concepts>\n")[1].split("</other_concepts>")[0]
        assert "- 완전 이진 트리의 배열 표현" in block and "- 힙의 삽입 연산" in block
    diagnose.make_question(concept, material, set(), kind=QTYPE_ESSAY)
    assert seen["03A"].split("\n<other_concepts>\n")[1].startswith("(없음)")


def test_empty_answer_reasons_differ():
    from core.diagnose import REASON_BLANK, REASON_DONT_KNOW, empty_grading
    assert empty_grading().reason == REASON_BLANK and "비워" in REASON_BLANK
    assert "모르겠어요" in empty_grading(REASON_DONT_KNOW).reason
