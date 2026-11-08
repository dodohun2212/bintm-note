# -*- coding: utf-8 -*-
"""prompts/*.md 파일을 읽고 {{자리}}를 채운다 (BR-10). 프롬프트 문장은 코드에 두지 않는다."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

# 프롬프트 버전을 바꾸려면 이 표의 파일명만 바꾼다.
PROMPT_FILES = {
    "01": "01_개념추출_v1.md",
    "02": "02_강조발화_v1.md",
    "03A": "03A_진단문제_v1.md",
    "03B": "03B_채점_v1.md",
    "03C": "03C_객관식_v1.md",
    "04": "04_보완설명_v1.md",
    "05": "05_요약노트_v1.md",
}

_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


@lru_cache(maxsize=None)
def load(name: str) -> str:
    path = PROMPT_DIR / PROMPT_FILES[name]
    return path.read_text(encoding="utf-8")


def placeholders(name: str) -> set[str]:
    return set(_PLACEHOLDER.findall(load(name)))


def fill(name: str, **values: str) -> str:
    """{{KEY}} 자리를 values로 채운다. 채우지 못한 자리가 남으면 오류."""
    text = load(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    left = _PLACEHOLDER.findall(text)
    if left:
        raise KeyError(f"프롬프트 {name}에 채우지 못한 자리: {sorted(set(left))}")
    return text
