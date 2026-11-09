# -*- coding: utf-8 -*-
"""F08 진단 문제 생성(서술형 3-A, 객관식 3-C)과 채점(서술형 3-B, 객관식은 코드). 상태 판정은 코드가 한다."""
from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Optional, Sequence

from config import AI_MAX_TOKENS, DIAG_MIN_PCT, ESSAY_MIN_PCT
from core import prompts
from core.extract import evidence_pages, pages_to_text
from core.figure import check_figure, figure_problem, figure_text
from core.llm import LLMJsonError, Usage, ask_json
from core.schemas import (QTYPE_ESSAY, QTYPE_MCQ, STATUS_KNOWN, STATUS_UNKNOWN, STATUS_UNSURE, Concept, Grading,
                          Material, Question, RubricItem, ScoresResult)

# 객관식 채점 (코드, AI 호출 없음). 확신하고 맞힘 = 앎, 찍어서 맞힘 = 헷갈림, 틀림 = 모름.
MCQ_SCORE_SURE = 10
MCQ_SCORE_GUESS = 5
MCQ_SCORE_WRONG = 0
MCQ_DONT_KNOW = -1                # 객관식 "모르겠어요"를 고른 값 (안 고름은 None)

# 답이 없을 때 채점 이유 (AI 호출 없이 0점 모름)
REASON_BLANK = "답을 비워 두어 모름으로 표시했어요."
REASON_DONT_KNOW = "'모르겠어요'를 골라 모름으로 표시했어요."
REASON_NOT_PICKED = "보기를 고르지 않아 모름으로 표시했어요."


# 문제가 학생이 볼 수 없는 페이지·그림을 가리키면 이 말을 붙여 한 번 더 만든다 (F08)
FIX_NOTE = (
    "\n\n## 다시 만들기\n방금 만든 문제는 {why}. 학생은 강의자료를 펴지 않고 이 문제 화면만 봅니다. "
    "문제 글에 페이지 번호나 '그림 참고' 같은 말을 쓰지 말고, 트리·배열·표가 필요하면 `figure`에 데이터로 넣으세요. "
    "같은 출력 형식의 JSON으로 다시 만드세요."
)


# 문제 형식 고르기 (S02)
MODE_MIX = "섞어서"
MODE_MCQ = "모두 객관식"
MODE_ESSAY = "모두 서술형"
QUESTION_MODES = (MODE_MIX, MODE_MCQ, MODE_ESSAY)


def diag_targets(scores: ScoresResult, min_pct: int = DIAG_MIN_PCT, top: Optional[int] = None) -> list[str]:
    """진단할 개념 = 출제 가능성이 min_pct 이상인 개념 전부 (순위 순서).

    우선순위 = 출제 가능성 × (1 − 이해도) 이므로 출제 가능성이 20 미만이면 진단 결과와 상관없이 우선순위가
    20 미만("복습만")이다. 결과가 바뀌지 않는 문제는 내지 않는다.
    top: "빠른 진단"일 때 그중 출제 가능성 상위 top개만 (v1.5). 나머지는 '진단 안 함'(이해도 0.5)으로 계산된다.
    """
    ids = [s.concept_id for s in scores.scores if s.pct >= min_pct]
    return ids[:top] if top is not None and top > 0 else ids


def question_kind(exam_pct: int, mode: str = MODE_MIX, essay_min_pct: int = ESSAY_MIN_PCT) -> str:
    """섞어서: 출제 가능성 점수가 높은 개념(50점 이상)은 서술형으로 깊게, 나머지는 객관식으로 빠르게."""
    if mode == MODE_MCQ:
        return QTYPE_MCQ
    if mode == MODE_ESSAY:
        return QTYPE_ESSAY
    return QTYPE_ESSAY if exam_pct >= essay_min_pct else QTYPE_MCQ


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


def other_concepts_text(names: Sequence[str]) -> str:
    """프롬프트 03-A/03-C의 {{OTHER_CONCEPTS}} 자리. 따로 문제가 나가는 개념 목록."""
    names = [n for n in names if n]
    return "\n".join(f"- {n}" for n in names) if names else "(없음)"


def make_question(concept: Concept, material: Material, meta_pages: set[int], usage: Optional[Usage] = None,
                  kind: str = QTYPE_ESSAY, others: Sequence[str] = ()) -> Question:
    """kind가 객관식이면 3-C, 아니면 3-A. 객관식 응답이 형식에 안 맞으면 서술형으로 대신 만든다.

    others: 함께 진단하는 다른 개념 이름. 개념마다 문제를 동시에 만들기 때문에, 이 목록을 프롬프트에 넣어
    다른 개념의 핵심(예: 배열 인덱스 계산)을 이 문제에서 다시 묻지 않게 한다.
    """
    if kind == QTYPE_MCQ:
        try:
            return make_mcq(concept, material, meta_pages, usage, others)
        except (LLMJsonError, ValueError):
            pass
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("03A", CONCEPT_NAME=concept.name, PAGES=pages_to_text(material, pages),
                          OTHER_CONCEPTS=other_concepts_text(others))

    def parse(raw: dict) -> Question:
        raw = dict(raw)
        fig = check_figure(raw.pop("figure", None))
        q = Question.model_validate(raw)
        src = [p for p in q.source_pages if p in pages] or pages[:2]
        return q.model_copy(update={"rubric": _normalize_rubric(q.rubric), "source_pages": src, "kind": QTYPE_ESSAY,
                                    "figure": fig})

    q = parse(ask_json(prompt, name="03A", max_tokens=AI_MAX_TOKENS, usage=usage))
    why = figure_problem(q.question, q.figure)
    if why:   # 한 번 더 만든다. 그래도 안 되면 두 번째 문제를 쓴다.
        q = parse(ask_json(prompt + FIX_NOTE.format(why=why), name="03A", max_tokens=AI_MAX_TOKENS, usage=usage))
    return q


_CHOICE_PREFIX = re.compile(r"^\s*(?:[①②③④⑤]\s*|(?:[1-5A-Ea-e][.)]|\([1-5A-Ea-e]\))\s+)")


def _clean_choice(text: str) -> str:
    return _CHOICE_PREFIX.sub("", str(text)).strip()


def check_mcq(raw: dict) -> tuple[str, list[str], int, str, list[int]]:
    """AI 응답 검사: 보기 4개, 서로 다름, 정답 위치 0~3. 어긋나면 ValueError."""
    question = str(raw.get("question", "")).strip()
    choices = [_clean_choice(c) for c in (raw.get("choices") or [])]
    try:
        idx = int(raw.get("answer_index"))
    except (TypeError, ValueError) as e:
        raise ValueError("answer_index 없음") from e
    if not question:
        raise ValueError("문제 없음")
    if len(choices) != 4 or any(not c for c in choices) or len(set(choices)) != 4:
        raise ValueError(f"보기는 서로 다른 4개여야 함: {choices}")
    if not 0 <= idx < 4:
        raise ValueError(f"answer_index 범위 밖: {idx}")
    pages = [int(p) for p in (raw.get("source_pages") or []) if str(p).isdigit()]
    return question, choices, idx, str(raw.get("explanation", "")).strip(), pages


def shuffle_choices(choices: list[str], answer_index: int, seed: str) -> tuple[list[str], int]:
    """AI가 정답을 한쪽 위치에 몰아 두는 버릇을 없앤다. 같은 문제는 늘 같은 순서(seed 고정)."""
    order = list(range(len(choices)))
    random.Random(int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)).shuffle(order)
    return [choices[i] for i in order], order.index(answer_index)


def make_mcq(concept: Concept, material: Material, meta_pages: set[int], usage: Optional[Usage] = None,
             others: Sequence[str] = ()) -> Question:
    """그림 검사에 두 번 걸리면 ValueError (make_question이 서술형으로 대신 만든다)."""
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("03C", CONCEPT_NAME=concept.name, PAGES=pages_to_text(material, pages),
                          OTHER_CONCEPTS=other_concepts_text(others))
    raw = ask_json(prompt, name="03C", max_tokens=AI_MAX_TOKENS, usage=usage)
    question, choices, idx, explanation, src = check_mcq(raw)
    fig = check_figure(raw.get("figure"))
    why = figure_problem(question, fig)
    if why:
        raw = ask_json(prompt + FIX_NOTE.format(why=why), name="03C", max_tokens=AI_MAX_TOKENS, usage=usage)
        question, choices, idx, explanation, src = check_mcq(raw)
        fig = check_figure(raw.get("figure"))
        why = figure_problem(question, fig)
        if why:
            raise ValueError(f"그림 검사 실패: {why}")
    choices, idx = shuffle_choices(choices, idx, concept.id + question)
    src = [p for p in src if p in pages] or pages[:2]
    return Question(question=question, answer=choices[idx], rubric=[], source_pages=src, kind=QTYPE_MCQ,
                    choices=choices, answer_index=idx, explanation=explanation, figure=fig)


CIRCLED = "①②③④⑤⑥⑦⑧"


def mcq_answer_text(question: Question, chosen: Optional[int], guessed: bool = False) -> str:
    """객관식 답을 사람이 읽는 글로 (보완 설명 호출과 내보내기에 씀). 무응답은 빈 글."""
    if chosen is None or not 0 <= chosen < len(question.choices):
        return ""
    return f"{CIRCLED[chosen]} {question.choices[chosen]}" + (" (확신 없이 고름)" if guessed else "")


def grade_mcq(question: Question, chosen: Optional[int], guessed: bool = False) -> Grading:
    """객관식 채점은 코드가 한다 (AI 호출 없음). chosen: None = 안 고름, -1 = "모르겠어요"."""
    if chosen == MCQ_DONT_KNOW:
        return empty_grading(REASON_DONT_KNOW)
    if chosen is None or not 0 <= chosen < len(question.choices):
        return empty_grading(REASON_NOT_PICKED)
    if chosen == question.answer_index:
        if guessed:
            return Grading(score=MCQ_SCORE_GUESS, status=STATUS_UNSURE, error_type="찍어서 맞힘",
                           reason="정답을 골랐지만 확신이 없다고 표시해서 헷갈림으로 봤어요.")
        return Grading(score=MCQ_SCORE_SURE, status=STATUS_KNOWN, reason="정답을 확신하고 골랐어요.")
    return Grading(score=MCQ_SCORE_WRONG, status=STATUS_UNKNOWN, error_type="오답",
                   reason=f"{CIRCLED[chosen]}번을 골랐는데 정답은 {CIRCLED[question.answer_index or 0]}번이에요.")


def is_answered(question: Question, choice: Optional[int] = None, answer: str = "", dont_know: bool = False) -> bool:
    """채점해도 되는지. 객관식은 보기나 '모르겠어요'를 골라야, 서술형은 답을 쓰거나 '모르겠어요'를 체크해야 한다 (v1.3)."""
    if question.is_mcq:
        return choice is not None and (choice == MCQ_DONT_KNOW or 0 <= choice < len(question.choices))
    return bool(dont_know) or bool((answer or "").strip())


def empty_grading(reason: str = REASON_BLANK) -> Grading:
    return Grading(score=0, max=10, rubric_scores=[], status=STATUS_UNKNOWN, error_type="무응답", reason=reason)


EXAMPLE_CONFUSION = "두 보기 사이에서 고민했어요. 둘이 어떻게 다른지 모르겠어요."


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?。])\s+", (text or "").strip(), maxsplit=1)
    return parts[0]


def example_answers(questions: Sequence[Question]) -> list[dict]:
    """샘플 체험용 예시 답 (v1.6). 문제를 다 풀지 않아도 채점과 ④ 결과를 볼 수 있게 한다.

    앎·헷갈림·모름이 골고루 나오도록 순서대로 돌려 가며 채운다. 채점은 그대로 코드(객관식)와 AI(서술형)가 한다.
    서술형: 모범 답안 전체 → 모범 답안 첫 문장만 → '모르겠어요'
    객관식: 확신하고 정답 → 찍어서 정답(헷갈린 점 적음) → 오답
    """
    out, n_essay, n_mcq = [], 0, 0
    for q in questions:
        if q.is_mcq:
            k, n_mcq = n_mcq % 3, n_mcq + 1
            right = q.answer_index or 0
            if k == 0:
                out.append(dict(choice=right, guessed=False, confusion=""))
            elif k == 1:
                out.append(dict(choice=right, guessed=True, confusion=EXAMPLE_CONFUSION))
            else:
                out.append(dict(choice=(right + 1) % max(1, len(q.choices)), guessed=False, confusion=""))
        else:
            k, n_essay = n_essay % 3, n_essay + 1
            if k == 0:
                out.append(dict(answer=q.answer, dont_know=False))
            elif k == 1:
                out.append(dict(answer=_first_sentence(q.answer), dont_know=False))
            else:
                out.append(dict(answer="", dont_know=True))
    return out


def question_for_prompt(question: Question) -> dict:
    """채점·설명 프롬프트에 넣을 문제. 그림은 글로 바꿔 넣는다."""
    d = question.model_dump(exclude={"figure"})
    if question.figure is not None:
        d["figure"] = figure_text(question.figure)
    return d


def grade_answer(concept: Concept, question: Question, answer: str, material: Material, meta_pages: set[int],
                 usage: Optional[Usage] = None) -> Grading:
    """빈 답은 AI 호출 없이 0점 (E-11). 상태는 코드가 점수로 정한다."""
    if not answer or not answer.strip():
        return empty_grading()
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill(
        "03B",
        CONCEPT_NAME=concept.name,
        QUESTION_JSON=json.dumps(question_for_prompt(question), ensure_ascii=False, indent=1),
        PAGES=pages_to_text(material, pages),
        ANSWER=answer.strip(),
    )
    raw = ask_json(prompt, name="03B", max_tokens=AI_MAX_TOKENS, usage=usage)
    g = Grading.model_validate(raw)
    rubric_scores = g.rubric_scores
    if question.rubric and len(rubric_scores) == len(question.rubric):   # 요소 만점을 넘지 않게
        rubric_scores = [min(s, it.score) for s, it in zip(rubric_scores, question.rubric)]
    return g.model_copy(update={"max": 10, "status": status_from_score(g.score), "rubric_scores": rubric_scores})
