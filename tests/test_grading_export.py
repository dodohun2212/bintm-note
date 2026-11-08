# T-31 부분 점수 채점, T-32 모든 문제에 답해야 채점, T-33 답이 잘리면 길이 상한을 늘려 다시 받기 (v1.3)
import types

import anthropic
import pytest

from core import diagnose, llm
from core.diagnose import MCQ_DONT_KNOW, grade_answer, is_answered
from core.schemas import QTYPE_MCQ, Concept, Grading, Material, Page, Question, RubricItem


# ----------------------------------------------------------------- T-31 부분 점수


def test_t31_grading_accepts_partial_and_null_scores():
    g = Grading.model_validate({"score": 6.5, "rubric_scores": [2.5, None, "1", 0.4], "error_type": "null",
                                "reason": None})
    assert g.rubric_scores == [2, 0, 1, 0] and g.error_type is None and g.reason == "" and g.score == 6
    assert Grading.model_validate({"score": 3, "rubric_scores": "없음"}).rubric_scores == []


def test_t31_grade_answer_clamps_rubric_to_item_max(monkeypatch):
    concept = Concept(id="c1", name="힙 삽입", pages=[1])
    text = "힙 삽입은 끝에 넣고 부모와 비교한다."
    material = Material(name="m.pdf", kind="pdf", n_pages=1, chars=len(text), pages=[Page(n=1, text=text)])
    q = Question(question="힙 삽입 과정을 쓰시오.", answer="끝에 넣고 부모와 비교", source_pages=[1],
                 rubric=[RubricItem(point="위치", score=4), RubricItem(point="비교", score=3),
                         RubricItem(point="복잡도", score=3)])
    monkeypatch.setattr(diagnose, "ask_json", lambda *a, **k: {
        "score": 8.5, "rubric_scores": [4.6, 3, 2.5], "status": "앎", "error_type": None, "reason": "대체로 맞음 (p.1)"})
    g = grade_answer(concept, q, "끝에 넣고 부모와 비교해 바꾼다.", material, set())
    assert g.rubric_scores == [4, 3, 2] and g.score == 8 and g.status == "앎"


# ----------------------------------------------------------------- T-32 답해야 채점


def test_t32_is_answered():
    mcq = Question(question="q", answer="a", kind=QTYPE_MCQ, choices=["a", "b", "c", "d"], answer_index=0)
    essay = Question(question="q", answer="a")
    assert not is_answered(mcq, None) and not is_answered(mcq, 7)
    assert is_answered(mcq, MCQ_DONT_KNOW) and is_answered(mcq, 2)
    assert not is_answered(essay, answer="") and not is_answered(essay, answer="   ")
    assert is_answered(essay, answer="", dont_know=True) and is_answered(essay, answer="끝에 넣는다")


# ----------------------------------------------------------------- T-33 잘린 답 다시 받기


class _FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def _message(text, stop_reason):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                                 usage=types.SimpleNamespace(input_tokens=10, output_tokens=20))


def test_t33_ask_json_retries_with_bigger_limit_when_cut(monkeypatch):
    sent = []
    replies = [_message('{"score": 7, "reas', "max_tokens"), _message('{"score": 7}', "end_turn")]

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = types.SimpleNamespace(stream=self.stream)

        def stream(self, **params):
            sent.append(dict(params))
            return _FakeStream(replies[len(sent) - 1])

    monkeypatch.setenv("BINTM_FAKE_AI", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    usage = llm.Usage()
    assert llm.ask_json("p", name="03B", max_tokens=4000, usage=usage) == {"score": 7}
    assert [p["max_tokens"] for p in sent] == [4000, 8000]
    assert "thinking" not in sent[0] and usage["calls"] == 2


def test_t33_ask_json_gives_up_after_two_bad_answers(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = types.SimpleNamespace(stream=lambda **p: _FakeStream(_message("JSON 아님", "end_turn")))

    monkeypatch.setenv("BINTM_FAKE_AI", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(llm.LLMJsonError):
        llm.ask_json("p", name="04")
