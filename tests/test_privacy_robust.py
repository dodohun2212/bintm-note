# T-42 ~ T-50 (v1.8~v1.10): 대본도 가리기, 형식이 틀린 AI 항목은 그것만 버리기, '내가 놓친 점' 바로잡기,
# 문제 그림 때문에 교재에 오류가 있다고 단정하지 않기, 기다리는 안내가 어디서든 보이기, 서술형 크기 줄이기
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


# ----------------------------------------------------------------- T-47, T-48 서술형 부담 줄이기 (v1.9)


def test_t47_essay_question_asks_at_most_two_things():
    """서술형 한 문제에 3~4가지를 한꺼번에 묻지 않게: 최대 2가지, 2~3문장, 채점 요소 2~4개."""
    p = prompts.load("03A")
    assert "최대 2가지" in p and "2~3문장" in p and "2~4개 요소" in p
    assert "2~5" not in p and "시간 복잡도와 이유를 쓰시오" not in p      # 예전 크기·여러 개를 묻는 예시가 없음
    assert "아는 만큼 2~3문장으로" in (ROOT / "app.py").read_text(encoding="utf-8")


def _app_function(name: str):
    """app.py를 import하지 않고(streamlit 없이) 함수 하나만 꺼내 실행한다."""
    import ast
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), ns)
    return ns[name]


def test_t48_prompt_change_reloads_prompts_and_sample_questions():
    """프롬프트 파일만 바뀌어도 배포 뒤 예전 프롬프트·예전 샘플 문제를 버린다."""
    changed = _app_function("_mtimes_changed")
    seen = {"core.diagnose": 1.0, "prompts/03A.md": 2.0}
    assert not changed(seen, {"core.diagnose": 1.0, "core": 9.0, "prompts/03A.md": 2.0})   # 그대로면 아무것도 안 함
    assert changed(seen, {"core.diagnose": 1.0, "prompts/03A.md": 3.0})                    # 프롬프트가 바뀜
    assert changed(seen, {"core.diagnose": 1.5, "prompts/03A.md": 2.0})                    # 모듈이 바뀜
    assert changed({"core.diagnose": 1.0}, {"core.diagnose": 1.0, "prompts/03A.md": 2.0})  # 프롬프트 기록이 없던 첫 배포
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "now.update(_prompt_mtimes())" in app_src and "sys._bintm_mtimes.update(_prompt_mtimes())" in app_src


# ----------------------------------------------------------------- T-50 README 안내·정확한 문구, 채점 말투 (v1.10)


def test_t50_readme_wake_note_and_exact_wording():
    """앱이 잠들었을 때 안내, '같은 입력 → 같은 점수'를 'AI가 찾은 신호가 같으면'으로, 채점 이유는 '~다' 말투."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Yes, get this app back up!" in readme and "같은 입력이면 항상 같은 점수" not in readme
    assert "AI가 찾은 신호" in readme and "scripts/" in readme
    p = prompts.load("03B")
    assert '문장 끝은 "~다"로' in p and "맞음." not in p
