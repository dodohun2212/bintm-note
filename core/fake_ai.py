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
        if "순회" in concept:   # 그림(트리)이 붙는 문제 예
            return {
                "question": "(가짜 AI 모드) 아래 트리를 전위·중위·후위로 순회한 결과를 각각 쓰고, 세 순회가 무엇이 다른지 설명하시오.",
                "answer": "(가짜 AI 모드) 전위는 + * a b - c d, 중위는 a * b + c - d, 후위는 a b * c d - +이다. 루트를 방문하는 시점이 다르다.",
                "rubric": [
                    {"point": "전위 순회 결과", "score": 3},
                    {"point": "중위 순회 결과", "score": 3},
                    {"point": "후위 순회 결과", "score": 2},
                    {"point": "루트 방문 시점 차이", "score": 2},
                ],
                "source_pages": pages or [1],
                "figure": {"kind": "tree", "nodes": ["+", "*", "-", "a", "b", "c", "d"], "caption": "수식 트리"},
            }
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
    if name == "03C":
        concept = _concept_name(prompt_text)
        pages = _pages_in(_between(prompt_text, "pages"))[:2]
        if "배열" in concept:   # 그림(배열)이 붙는 문제 예
            return {
                "question": "(가짜 AI 모드) 아래 배열로 저장한 완전 이진 트리에서 값 75인 노드의 왼쪽 자식은?",
                "choices": ["30", "60", "80", "40"],
                "answer_index": 0,
                "explanation": "(가짜 AI 모드) 75는 인덱스 2이고 왼쪽 자식은 2i = 4번, 값 30이다 (p.7).",
                "source_pages": pages or [1],
                "figure": {"kind": "array", "items": ["90", "75", "80", "30", "60", "40"], "start": 1,
                           "caption": "인덱스 1부터 저장"},
            }
        return {
            "question": f"(가짜 AI 모드) '{concept}'에 대한 설명으로 옳은 것은?",
            "choices": [
                f"{concept}의 정의와 절차를 자료에 나온 대로 적은 보기 (정답)",
                f"{concept}의 절차 순서를 반대로 적은 보기",
                f"{concept}과 비슷한 다른 개념의 절차를 적은 보기",
                f"{concept}의 시간 복잡도를 틀리게 적은 보기",
            ],
            "answer_index": 0,
            "explanation": f"(가짜 AI 모드) 실제 AI를 켜면 자료 p.{pages[0] if pages else 1}을 근거로 한 해설이 나옵니다.",
            "source_pages": pages or [1],
        }
    if name == "03B":
        answer = _between(prompt_text, "answer").strip()
        if "#채점실패" in answer:   # 화면 확인용: 채점 실패를 일부러 낸다 (실패한 문제만 다시 채점하는 흐름 확인)
            from core.llm import LLMJsonError
            raise LLMJsonError("(가짜 AI 모드) 일부러 낸 채점 실패")
        if not answer or "모르" in answer:
            return {"score": 0, "max": 10, "rubric_scores": [0, 0, 0, 0], "status": "모름",
                    "error_type": "무응답", "reason": "(가짜 AI 모드) 답이 비어 있음."}
        if len(answer) >= 60:
            return {"score": 8, "max": 10, "rubric_scores": [4, 2, 2, 0], "status": "앎",
                    "error_type": None, "reason": "(가짜 AI 모드) 길이로만 판정한 결과이며 실제 채점이 아님."}
        return {"score": 5, "max": 10, "rubric_scores": [3, 1.5, 0.5, 0], "status": "헷갈림",   # 부분 점수 (v1.3)
                "error_type": "절차 누락", "reason": "(가짜 AI 모드) 길이로만 판정한 결과이며 실제 채점이 아님."}
    if name == "04":
        concept = _concept_name(prompt_text)
        pages = _pages_in(_between(prompt_text, "pages"))[:2]
        p = pages[0] if pages else 1
        return {
            "my_gap": f"(가짜 AI 모드) {concept}의 진단 결과를 바탕으로 한 보완 지점.",
            "explanation": (f"(가짜 AI 모드) 실제 AI를 켜면 자료 p.{p}의 문장을 인용한 설명이 여기에 나옵니다 (p.{p})."
                            f"\n\n설명은 2~4개의 짧은 문단으로 나뉘어 나옵니다. 정의, 절차, 이유를 차례로 짚습니다 (p.{p})."),
            "check_pages": pages or [1],
            "source_pages": pages or [1],
            "not_found": False,
            "not_found_note": None,
        }
    if name == "05":
        concept = _concept_name(prompt_text)
        pages = _pages_in(_between(prompt_text, "pages"))[:2]
        p = pages[0] if pages else 1
        full = "**자세히**" in prompt_text
        summary = (f"(가짜 AI 모드) 실제 AI를 켜면 {concept}의 정의를 자료 문장으로 정리한 요약이 나온다 (p.{p}).")
        if full:
            summary += (f"\n\n(가짜 AI 모드) 절차와 과정을 순서대로 짚는다 (p.{p})."
                        f"\n\n(가짜 AI 모드) 왜 그런지와 시간 복잡도를 정리한다 (p.{p}).")
        return {
            "summary": summary,
            "key_points": [f"(가짜) {concept} 핵심 1", f"(가짜) {concept} 핵심 2"] + ([f"(가짜) {concept} 핵심 3"] if full else []),
            "pitfalls": [f"(가짜) {concept}에서 자주 하는 실수"] if full else [],
            "source_pages": pages or [1],
        }
    raise KeyError(name)
