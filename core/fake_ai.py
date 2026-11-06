# -*- coding: utf-8 -*-
"""BINTM_FAKE_AI=1 일 때 쓰는 가짜 응답. 실제 AI를 부르지 않고 tests/fixtures의 저장된 결과를 돌려준다.

개발·테스트·화면 확인용이다. 샘플 자료가 아닌 자료를 넣으면 내용이 맞지 않는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _between(text: str, tag: str) -> str:
    """마지막 <tag> … </tag> 사이. (프롬프트 설명문에도 `<tag>`가 나오므로 마지막 것을 쓴다.)"""
    start = text.rfind(f"<{tag}>")
    end = text.rfind(f"</{tag}>")
    if start < 0 or end < 0 or end < start:
        return ""
    return text[start + len(tag) + 2 : end].strip("\n")


def _concept_name(prompt_text: str) -> str:
    m = re.search(r'개념 "([^"]+)"', prompt_text)
    return m.group(1) if m else "이 개념"


def _pages_in(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"=== 페이지 (\d+) ===", text)]


def respond(name: str, prompt_text: str) -> dict:
    if name == "01":
        d = _load("01_개념추출_결과.json")
        d.setdefault("meta_pages", [1, 2, 3, 19, 20])
        return d
    if name == "02":
        return _load("02_강조발화_결과.json")
    if name == "03A":
        concept = _concept_name(prompt_text)
        pages = _pages_in(_between(prompt_text, "pages"))[:2]
        return {
            "question": f"'{concept}'의 핵심 내용을 자료에 나온 대로 설명하고, 그 과정이나 성질이 왜 그렇게 되는지 이유를 쓰시오.",
            "answer": f"(가짜 AI 모드) {concept}에 대한 자료의 설명을 요약한 모범 답안.",
            "rubric": [
                {"point": "정의 또는 절차를 바르게 말함", "score": 4},
                {"point": "핵심 용어를 자료와 같게 씀", "score": 2},
                {"point": "이유 또는 성질을 설명함", "score": 2},
                {"point": "예 또는 복잡도를 언급함", "score": 2},
            ],
            "source_pages": pages or [1],
        }
    if name == "03B":
        answer = _between(prompt_text, "answer").strip()
        if not answer or "모르" in answer:
            return {"score": 0, "max": 10, "rubric_scores": [0, 0, 0, 0], "status": "모름",
                    "error_type": "무응답", "reason": "(가짜 AI 모드) 답이 비어 있음."}
        if len(answer) >= 60:
            return {"score": 8, "max": 10, "rubric_scores": [4, 2, 2, 0], "status": "앎",
                    "error_type": None, "reason": "(가짜 AI 모드) 길이로만 판정한 결과이며 실제 채점이 아님."}
        return {"score": 5, "max": 10, "rubric_scores": [3, 1, 1, 0], "status": "헷갈림",
                "error_type": "절차 누락", "reason": "(가짜 AI 모드) 길이로만 판정한 결과이며 실제 채점이 아님."}
    if name == "04":
        concept = _concept_name(prompt_text)
        pages = _pages_in(_between(prompt_text, "pages"))[:2]
        p = pages[0] if pages else 1
        return {
            "my_gap": f"(가짜 AI 모드) {concept}의 진단 결과를 바탕으로 한 보완 지점.",
            "explanation": f"(가짜 AI 모드) 실제 AI를 켜면 자료 p.{p}의 문장을 인용한 설명이 여기에 나옵니다 (p.{p}).",
            "check_pages": pages or [1],
            "source_pages": pages or [1],
            "not_found": False,
            "not_found_note": None,
        }
    raise KeyError(name)
