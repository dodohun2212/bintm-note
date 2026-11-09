# T-42 ~ T-46 (v1.8): 대본도 가리기, 형식이 틀린 AI 항목은 그것만 버리기, '내가 놓친 점' 바로잡기,
# 문제 그림 때문에 교재에 오류가 있다고 단정하지 않기, 기다리는 안내가 어디서든 보이기
from pathlib import Path

import pytest

from core import explain as explain_mod, prompts, utterances as utt_mod
from core.concepts import NoConceptsError, validate_concepts
from core.diagnose import REASON_BLANK, REASON_DONT_KNOW, empty_grading
from core.schemas import (STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, Concept, Grading, Material, Page, Question,
                          to_int_list)
from core.utterances import validate_utterances

ROOT = Path(__file__).resolve().parent.parent


def _material(n: int = 6) -> Material:
    pages = [Page(n=i, text=f"{i}쪽 본문. 힙과 트리 설명.") for i in range(1, n + 1)]
    return Material(name="m.pdf", kind="pdf", n_pages=n, chars=sum(len(p.text) for p in pages), pages=pages)


# ----------------------------------------------------------------- T-42 대본 가리기


def test_t42_transcript_is_masked_before_ai(monkeypatch):
    seen = []

    def fake_ask(prompt, **kw):
        seen.append(prompt)
        return {"utterances": [{"concept_id": "c1", "concept_name": "힙", "quote": "학번 [마스킹] 학생, 이건 꼭 알아두세요.",
                                "type": "emphasis", "strength": 3}]}

    monkeypatch.setattr(utt_mod, "ask_json", fake_ask)
    transcript = "학번 2021136001 학생, 이건 꼭 알아두세요. 질문은 a@b.ac.kr 이나 010-1234-5678로 주세요."
    out = utt_mod.find_utterances([Concept(id="c1", name="힙")], transcript)
    for secret in ("2021136001", "a@b.ac.kr", "010-1234-5678"):
        assert secret not in seen[0]
    assert "[마스킹]" in seen[0]
    assert len(out) == 1          # 인용 검사도 가린 대본으로 하므로 AI가 돌려준 문장이 그대로 통과한다

    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "transcript = mask_pii(transcript)" in app_src   # 화면에서도 받자마자 가린다 (세션·캐시에 원문이 남지 않게)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "세션 메모리에만" not in readme and "세션 메모리에만" not in app_src   # 서버 메모리 캐시가 있으므로


# ----------------------------------------------------------------- T-43 형식이 틀린 항목만 버리기


def test_t43_one_bad_concept_does_not_stop_analysis():
    raw = {"objectives_page": "p.1", "exercise_page": None, "meta_pages": ["6"], "concepts": [
        {"id": "c1", "name": "힙 삽입", "pages": [2, 3]},
        {"id": None, "name": "힙 삭제", "pages": "3-4"},                              # id null, 쪽 번호가 글자
        {"id": 7, "name": "트리 순회", "pages": ["p.5", 5.0], "keywords": "순회", "has_example": None},
        {"id": "c4", "pages": [2]},                                                   # 이름 없음 → 버림
        "개념 아님",                                                                    # 형식이 아예 다름 → 버림
        {"id": "c6", "name": "힙 정렬", "pages": [2], "in_objectives": "모름"},          # 읽을 수 없는 값 → 버림
    ]}
    r = validate_concepts(raw, _material())
    assert [c.name for c in r.concepts] == ["힙 삽입", "힙 삭제", "트리 순회"]
    assert r.concepts[1].id == "c2" and r.concepts[1].pages == [3, 4]
    assert r.concepts[2].id == "7" and r.concepts[2].pages == [5] and r.concepts[2].keywords == ["순회"]
    assert {1, 6} <= set(r.meta_pages)
    with pytest.raises(NoConceptsError):          # 쓸 개념이 하나도 없으면 '알 수 없는 오류'가 아니라 E-09
        validate_concepts({"concepts": [{"id": "c1"}, "x"]}, _material())
    with pytest.raises(NoConceptsError):
        validate_concepts({"개념": []}, _material())
    assert to_int_list(["3~5", "p.7", True, None, "없음", 2.5]) == [3, 4, 5, 7]


def test_t43_one_bad_utterance_does_not_stop_analysis():
    transcript = "이건 꼭 알아두세요. 시험에 나옵니다."
    raw = {"utterances": [
        {"concept_id": 1, "concept_name": "힙", "quote": "이건 꼭 알아두세요.", "type": "emphasis", "strength": "3"},
        {"concept_id": "c1", "concept_name": None, "quote": None, "type": "exam_hint"},   # 인용 없음 → 버림
        {"concept_id": "c1", "quote": "시험에 나옵니다.", "type": "exam_hint", "strength": 2},
        ["형식", "다름"],
    ]}
    out = validate_utterances(raw, transcript, [Concept(id="1", name="힙"), Concept(id="c1", name="트리")])
    assert [(u.concept_id, u.type) for u in out] == [("1", "emphasis"), ("c1", "exam_hint")]
    assert validate_utterances("JSON 아님", transcript, []) == []


# ----------------------------------------------------------------- T-44 '내가 놓친 점'


def test_t44_my_gap_matches_diagnosis(monkeypatch):
    fix = explain_mod.fix_gap
    dont_know = empty_grading(REASON_DONT_KNOW)
    wrong = Grading(score=2, reason="절차가 빠짐")
    assert fix("아직 확인하지 않은 개념", STATUS_UNKNOWN, dont_know) == explain_mod.NO_ANSWER_GAPS[REASON_DONT_KNOW]
    assert fix("", STATUS_UNKNOWN, empty_grading()) == explain_mod.NO_ANSWER_GAPS[REASON_BLANK]
    assert fix("순회 순서를 거꾸로 썼다.", STATUS_UNKNOWN, wrong) == "순회 순서를 거꾸로 썼다."   # AI의 구체적인 말은 둔다
    assert fix("아직 확인하지 않은 개념", STATUS_UNKNOWN, wrong) == explain_mod.OTHER_GAP
    assert fix("아무 말", STATUS_NOT_DIAGNOSED, None) == explain_mod.NOT_CHECKED_GAP

    monkeypatch.setattr(explain_mod, "ask_json", lambda prompt, **kw: {
        "my_gap": "아직 확인하지 않은 개념", "explanation": "e (p.1)", "source_pages": [1]})
    e = explain_mod.explain(Concept(id="c1", name="힙", pages=[1]), _material(1), set(), STATUS_UNKNOWN,
                            Question(question="q", answer="a"), "", dont_know)
    assert e.my_gap == explain_mod.NO_ANSWER_GAPS[REASON_DONT_KNOW]


# ----------------------------------------------------------------- T-45 교재 오류 단정 금지


def test_t45_prompts_do_not_blame_material_for_example_figures():
    """문제 그림은 AI가 새로 만든 예시라 자료의 그림과 다를 수 있다. 그 차이로 '교재 오기'라고 쓰지 않게 한다."""
    for name in ("03B", "04"):
        assert "강의자료에 오기나 오류가 있다고 쓰지 않습니다" in prompts.load(name)
    assert '"진단 안 함"일 때만' in prompts.load("04")


# ----------------------------------------------------------------- T-46 기다리는 안내


def test_t46_waiting_notice_visible_wherever_scrolled():
    """'…만드는 중' 안내가 페이지 맨 위에만 있으면 아래로 내려 둔 사람은 못 본다. 화면 아래에 고정해 띄운다."""
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    rule = app_src.split('[data-testid="stSpinner"] {', 1)[1].split("}", 1)[0]
    assert "position: fixed" in rule and "bottom:" in rule
