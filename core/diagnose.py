# -*- coding: utf-8 -*-
"""F08 진단 문제 생성(서술형 3-A, 객관식 3-C)과 채점(서술형 3-B, 객관식은 코드). 상태 판정은 코드가 한다."""
from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Optional

from config import DIAG_MIN_PCT, ESSAY_MIN_PCT
from core import prompts
from core.extract import evidence_pages, pages_to_text
from core.llm import LLMJsonError, Usage, ask_json
from core.schemas import (QTYPE_ESSAY, QTYPE_MCQ, STATUS_KNOWN, STATUS_UNKNOWN, STATUS_UNSURE, Concept, Grading,
                          Material, Question, RubricItem, ScoresResult)

# 객관식 채점 (코드, AI 호출 없음). 확신하고 맞힘 = 앎, 찍어서 맞힘 = 헷갈림, 틀림 = 모름.
MCQ_SCORE_SURE = 10
MCQ_SCORE_GUESS = 5
MCQ_SCORE_WRONG = 0


# 문제 형식 고르기 (S02)
MODE_MIX = "섞어서"
MODE_MCQ = "모두 객관식"
MODE_ESSAY = "모두 서술형"
QUESTION_MODES = (MODE_MIX, MODE_MCQ, MODE_ESSAY)


def diag_targets(scores: ScoresResult, min_pct: int = DIAG_MIN_PCT) -> list[str]:
    """진단할 개념 = 출제 가능성이 min_pct 이상인 개념 전부 (순위 순서).

    우선순위 = 출제 가능성 × (1 − 이해도) 이므로 출제 가능성이 20 미만이면 진단 결과와 상관없이 우선순위가
    20 미만("복습만")이다. 결과가 바뀌지 않는 문제는 내지 않는다.
    """
    return [s.concept_id for s in scores.scores if s.pct >= min_pct]


def question_kind(exam_pct: int, mode: str = MODE_MIX, essay_min_pct: int = ESSAY_MIN_PCT) -> str:
    """섞어서: 출제 가능성이 높은 개념(50% 이상)은 서술형으로 깊게, 나머지는 객관식으로 빠르게."""
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


def make_question(concept: Concept, material: Material, meta_pages: set[int], usage: Optional[Usage] = None,
                  kind: str = QTYPE_ESSAY) -> Question:
    """kind가 객관식이면 3-C, 아니면 3-A. 객관식 응답이 형식에 안 맞으면 서술형으로 대신 만든다."""
    if kind == QTYPE_MCQ:
        try:
            return make_mcq(concept, material, meta_pages, usage)
        except (LLMJsonError, ValueError):
            pass
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("03A", CONCEPT_NAME=concept.name, PAGES=pages_to_text(material, pages))
    raw = ask_json(prompt, name="03A", max_tokens=2000, usage=usage)
    q = Question.model_validate(raw)
    src = [p for p in q.source_pages if p in pages] or pages[:2]
    return q.model_copy(update={"rubric": _normalize_rubric(q.rubric), "source_pages": src, "kind": QTYPE_ESSAY})


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


def make_mcq(concept: Concept, material: Material, meta_pages: set[int], usage: Optional[Usage] = None) -> Question:
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill("03C", CONCEPT_NAME=concept.name, PAGES=pages_to_text(material, pages))
    raw = ask_json(prompt, name="03C", max_tokens=2000, usage=usage)
    question, choices, idx, explanation, src = check_mcq(raw)
    choices, idx = shuffle_choices(choices, idx, concept.id + question)
    src = [p for p in src if p in pages] or pages[:2]
    return Question(question=question, answer=choices[idx], rubric=[], source_pages=src, kind=QTYPE_MCQ,
                    choices=choices, answer_index=idx, explanation=explanation)


CIRCLED = "①②③④⑤⑥⑦⑧"


def mcq_answer_text(question: Question, chosen: Optional[int], guessed: bool = False) -> str:
    """객관식 답을 사람이 읽는 글로 (보완 설명 호출과 내보내기에 씀). 무응답은 빈 글."""
    if chosen is None or not 0 <= chosen < len(question.choices):
        return ""
    return f"{CIRCLED[chosen]} {question.choices[chosen]}" + (" (확신 없이 고름)" if guessed else "")


def grade_mcq(question: Question, chosen: Optional[int], guessed: bool = False) -> Grading:
    """객관식 채점은 코드가 한다 (AI 호출 없음). chosen=None이면 무응답."""
    if chosen is None:
        return empty_grading("'모르겠어요'를 골랐거나 답을 고르지 않아 모름으로 표시했어요.")
    if chosen == question.answer_index:
        if guessed:
            return Grading(score=MCQ_SCORE_GUESS, status=STATUS_UNSURE, error_type="찍어서 맞힘",
                           reason="정답을 골랐지만 확신이 없다고 표시해서 헷갈림으로 봤어요.")
        return Grading(score=MCQ_SCORE_SURE, status=STATUS_KNOWN, reason="정답을 확신하고 골랐어요.")
    return Grading(score=MCQ_SCORE_WRONG, status=STATUS_UNKNOWN, error_type="오답",
                   reason=f"{CIRCLED[chosen]}번을 골랐는데 정답은 {CIRCLED[question.answer_index or 0]}번이에요.")


def empty_grading(reason: str = "답을 비워두어 모름으로 표시했어요.") -> Grading:
    return Grading(score=0, max=10, rubric_scores=[], status=STATUS_UNKNOWN, error_type="무응답", reason=reason)


def grade_answer(concept: Concept, question: Question, answer: str, material: Material, meta_pages: set[int],
                 usage: Optional[Usage] = None) -> Grading:
    """빈 답은 AI 호출 없이 0점 (E-11). 상태는 코드가 점수로 정한다."""
    if not answer or not answer.strip():
        return empty_grading()
    pages = evidence_pages(concept.pages, meta_pages)
    prompt = prompts.fill(
        "03B",
        CONCEPT_NAME=concept.name,
        QUESTION_JSON=json.dumps(question.model_dump(), ensure_ascii=False, indent=1),
        PAGES=pages_to_text(material, pages),
        ANSWER=answer.strip(),
    )
    raw = ask_json(prompt, name="03B", max_tokens=2000, usage=usage)
    g = Grading.model_validate(raw)
    return g.model_copy(update={"max": 10, "status": status_from_score(g.score)})
