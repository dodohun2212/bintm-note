# -*- coding: utf-8 -*-
"""코드와 AI가 주고받는 데이터 형식 (개발기획안 6장). AI 응답은 모두 이 형식으로 검사한다."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

# AI 답 다듬기 (v1.8) -----------------------------------------------------------
# AI가 형식을 조금 틀리게 줘도(쪽 번호 "3-4", id null 등) 분석 전체가 멈추지 않게, 읽을 수 있는 것은 고쳐 받는다.

_INT = re.compile(r"\d+")
_RANGE = re.compile(r"\d+\s*[-~–]\s*\d+")


def to_int_list(v) -> list[int]:
    """쪽 번호 목록을 정수로. 5.0, "5", "p.5", "3-4", "3, 5"를 읽고, 읽지 못하는 것은 버린다."""
    if v is None:
        return []
    if not isinstance(v, (list, tuple, set)):
        v = [v]
    out: list[int] = []
    for x in v:
        if x is None or isinstance(x, bool):
            continue
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, float):
            if x.is_integer():
                out.append(int(x))
        else:
            s = str(x)
            nums = [int(n) for n in _INT.findall(s)]
            if len(nums) == 2 and _RANGE.search(s) and nums[0] <= nums[1] <= nums[0] + 30:
                out.extend(range(nums[0], nums[1] + 1))   # "3-4" → 3, 4
            else:
                out.extend(nums)
    return out


def to_opt_int(v) -> Optional[int]:
    """쪽 번호 하나. 읽지 못하면 None."""
    nums = to_int_list(v)
    return nums[0] if nums else None


def to_text(v) -> str:
    return "" if v is None else str(v)


def keep_valid(model: type[BaseModel], items) -> list:
    """AI가 준 목록에서 형식이 맞는 항목만 남긴다. 하나가 틀려도 나머지는 쓴다."""
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(model.model_validate(item))
        except ValidationError:
            continue
    return out


# 6.1 페이지별 텍스트 ---------------------------------------------------------


class Page(BaseModel):
    n: int
    text: str


class Material(BaseModel):
    name: str
    kind: Literal["pdf", "pptx"]
    n_pages: int
    chars: int
    pages: list[Page]

    def page_text(self, n: int) -> str:
        for p in self.pages:
            if p.n == n:
                return p.text
        return ""


# 6.2 개념 목록 -----------------------------------------------------------------


class Concept(BaseModel):
    id: str
    name: str
    summary: str = ""
    pages: list[int] = Field(default_factory=list)
    in_objectives: bool = False
    objective_quote: Optional[str] = None
    has_example: bool = False
    has_exercise: bool = False
    exercise_numbers: list[int] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("id", "name", "summary", mode="before")
    @classmethod
    def _text(cls, v):
        return to_text(v)   # id가 null이면 ""로 받고, validate_concepts가 c1, c2…를 붙인다

    @field_validator("pages", "exercise_numbers", mode="before")
    @classmethod
    def _ints(cls, v):
        return to_int_list(v)

    @field_validator("in_objectives", "has_example", "has_exercise", mode="before")
    @classmethod
    def _flag(cls, v):
        return False if v is None else v

    @field_validator("keywords", mode="before")
    @classmethod
    def _words(cls, v):
        if v is None:
            return []
        return [str(x) for x in v if x is not None] if isinstance(v, (list, tuple)) else [str(v)]


class ConceptsResult(BaseModel):
    objectives_page: Optional[int] = None
    exercise_page: Optional[int] = None
    meta_pages: list[int] = Field(default_factory=list)
    concepts: list[Concept]

    @field_validator("objectives_page", "exercise_page", mode="before")
    @classmethod
    def _page(cls, v):
        return to_opt_int(v)

    @field_validator("meta_pages", mode="before")
    @classmethod
    def _pages(cls, v):
        return to_int_list(v)


# 6.3 강조 발화 -----------------------------------------------------------------

UTTERANCE_TYPES = ("emphasis", "exam_hint", "mistake_warning", "exercise_hint", "deferral", "skip", "question")


class Utterance(BaseModel):
    concept_id: Optional[str] = None
    concept_name: str = ""
    quote: str
    type: str
    strength: int = 2

    @field_validator("concept_id", mode="before")
    @classmethod
    def _id(cls, v):
        return None if v is None else str(v)

    @field_validator("concept_name", mode="before")
    @classmethod
    def _name(cls, v):
        return to_text(v)

    @field_validator("strength", mode="before")
    @classmethod
    def _clamp_strength(cls, v):
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            v = 2
        return max(1, min(3, v))


class UtterancesResult(BaseModel):
    utterances: list[Utterance]


# 6.4 점수 ----------------------------------------------------------------------


class Reason(BaseModel):
    kind: str
    points: float
    label: str
    strength: Optional[int] = None


class ScoreRow(BaseModel):
    concept_id: str
    name: str
    raw: float
    pct: int
    body_pages: list[int]
    reasons: list[Reason]


class ScoresResult(BaseModel):
    max_raw: float
    scores: list[ScoreRow]


# 6.5 진단 문제와 채점 ------------------------------------------------------------


class RubricItem(BaseModel):
    point: str
    score: int


QTYPE_ESSAY = "서술형"
QTYPE_MCQ = "객관식"

FIG_TREE = "tree"     # 이진 트리. nodes = 레벨 순서(배열 표현) 노드 값, 빈자리는 null
FIG_ARRAY = "array"   # 배열. items = 값, start = 첫 인덱스(0 또는 1)
FIG_TABLE = "table"   # 표. header = 열 이름, rows = 행
FIGURE_KINDS = (FIG_TREE, FIG_ARRAY, FIG_TABLE)


class Figure(BaseModel):
    """문제에 붙는 그림. AI는 데이터만 주고 그림은 코드가 그린다 (core/figure.py)."""
    kind: str
    caption: str = ""
    nodes: list[Optional[str]] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    start: int = 0
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class Question(BaseModel):
    question: str
    answer: str                        # 서술형: 모범 답안 / 객관식: 정답 보기 글
    rubric: list[RubricItem] = Field(default_factory=list)   # 서술형만
    source_pages: list[int] = Field(default_factory=list)
    kind: str = QTYPE_ESSAY
    choices: list[str] = Field(default_factory=list)        # 객관식 보기 4개 (섞은 뒤 순서)
    answer_index: Optional[int] = None                      # 객관식 정답 위치 (0부터)
    explanation: str = ""                                   # 객관식 해설 (왜 정답인지, 오답은 왜 틀렸는지)
    figure: Optional[Figure] = None                         # 문제에 필요한 트리·배열·표 (없으면 None)

    @property
    def is_mcq(self) -> bool:
        return self.kind == QTYPE_MCQ


STATUS_KNOWN = "앎"
STATUS_UNSURE = "헷갈림"
STATUS_UNKNOWN = "모름"
STATUS_NOT_DIAGNOSED = "진단 안 함"


class Grading(BaseModel):
    score: int
    max: int = 10
    rubric_scores: list[int] = Field(default_factory=list)
    status: str = ""
    error_type: Optional[str] = None
    reason: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, v):
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            v = 0
        return max(0, min(10, v))

    @field_validator("rubric_scores", mode="before")
    @classmethod
    def _int_scores(cls, v):
        """AI가 부분 점수(2.5)나 null을 줘도 채점이 깨지지 않게 정수로 바꾼다 (v1.3)."""
        if not isinstance(v, (list, tuple)):
            return []
        out = []
        for x in v:
            try:
                out.append(max(0, int(round(float(x)))))
            except (TypeError, ValueError):
                out.append(0)
        return out

    @field_validator("reason", mode="before")
    @classmethod
    def _reason_text(cls, v):
        return "" if v is None else str(v)

    @field_validator("error_type", mode="before")
    @classmethod
    def _error_text(cls, v):
        t = "" if v is None else str(v).strip()
        return None if not t or t.lower() in ("null", "none") else t


# 6.6 우선순위 -------------------------------------------------------------------


class PriorityRow(BaseModel):
    concept_id: str
    name: str
    exam_pct: int
    status: str
    understanding: float
    priority: int
    action: str


# 6.7 보완 설명 ------------------------------------------------------------------


class Explanation(BaseModel):
    my_gap: str = ""
    explanation: str
    check_pages: list[int] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    not_found: bool = False
    not_found_note: Optional[str] = None
    confusion_reply: Optional[str] = None   # 학생이 적은 "헷갈린 점"에 대한 답 (v1.4). 적지 않았으면 None


# 6.9 시험 대비 요약 노트 ----------------------------------------------------------

DETAIL_FULL = "자세히"
DETAIL_MID = "보통"
DETAIL_SHORT = "짧게"


class NoteSection(BaseModel):
    concept_id: str = ""
    detail: str = DETAIL_SHORT
    summary: str
    key_points: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    from_ai: bool = True
