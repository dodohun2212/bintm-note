# -*- coding: utf-8 -*-
"""7번 기출 비교 (개발기획안 8.7). 자료(+대본)를 분석해 상위 N개와 실제 출제 개념표를 맞춰 본다.

사용법:
  python scripts/compare_exam.py --material 자료.pdf [--transcript 대본.md] --exam tests/기출_개념표.json [--top 10]
  BINTM_FAKE_AI=1 을 켜면 AI 없이 저장된 샘플 결과로 돈다 (샘플 자료일 때만 의미 있음).

출력: 상위 N개 중 실제 출제 개념과 맞은 개수, 전체 순위 표, 맞춘 쌍. README에는 이 출력을 그대로 적는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.concepts import extract_concepts  # noqa: E402
from core.extract import extract_material  # noqa: E402
from core.llm import Usage  # noqa: E402
from core.score import WEIGHTS_VERSION, compute_scores  # noqa: E402
from core.utterances import find_utterances  # noqa: E402


def _norm(s: str) -> str:
    s = re.sub(r"[\s·\-_()\[\]/,.]", "", s or "").lower()
    return s.replace("의", "")  # '힙의 삽입' = '힙 삽입'


def match(concept_name: str, concept_keywords: list[str], concept_summary: str, exam: dict) -> bool:
    """이름이 서로 포함되거나, 한쪽 키워드가 다른 쪽 이름·키워드·요약에 들어 있으면 같은 개념으로 본다."""
    a = _norm(concept_name)
    b = _norm(exam.get("name", ""))
    if a and b and (a in b or b in a):
        return True
    concept_blob = _norm(" ".join([concept_name, concept_summary] + list(concept_keywords)))
    exam_blob = _norm(" ".join([exam.get("name", "")] + list(exam.get("keywords", []))))
    ekeys = [_norm(k) for k in exam.get("keywords", []) if len(_norm(k)) >= 2]
    ckeys = [_norm(k) for k in concept_keywords if len(_norm(k)) >= 2]
    if any(k in concept_blob for k in ekeys):
        return True
    if any(k in exam_blob for k in ckeys):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", required=True)
    ap.add_argument("--transcript", default=None)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    material = extract_material(Path(args.material).read_bytes(), Path(args.material).name)
    transcript = Path(args.transcript).read_text(encoding="utf-8") if args.transcript else ""
    exam = json.loads(Path(args.exam).read_text(encoding="utf-8"))
    exam_concepts = [e for e in exam.get("exam_concepts", []) if not str(e.get("name", "")).startswith("예시")]
    if not exam_concepts:
        print("기출_개념표.json에 실제 출제 개념을 먼저 적어 주세요 (예시 항목은 무시됩니다).")
        return 2

    usage = Usage()
    concepts = extract_concepts(material, usage)
    utts = find_utterances(concepts.concepts, transcript, usage) if transcript.strip() else []
    scores = compute_scores(concepts.concepts, utts, set(concepts.meta_pages))
    by_id = {c.id: c for c in concepts.concepts}

    top = scores.scores[: args.top]
    hits = []
    for s in top:
        c = by_id[s.concept_id]
        for e in exam_concepts:
            if match(c.name, c.keywords, c.summary, e):
                hits.append((s.name, e["name"]))
                break
    covered = {ename for _, ename in hits}

    print(f"자료: {material.name} ({material.n_pages}쪽) · 대본: {'있음' if transcript.strip() else '없음'} · 가중치 {WEIGHTS_VERSION}")
    print(f"개념 {len(concepts.concepts)}개 · 발화 {len(utts)}개 · AI 호출 {usage['calls']}회, 입력 {usage['input_tokens']} 출력 {usage['output_tokens']} 토큰, {usage['seconds']:.1f}초")
    print(f"\n상위 {len(top)}개 중 실제 출제 개념과 맞은 것: {len(hits)}개 / 출제 개념 {len(exam_concepts)}개 중 상위 {len(top)}개에 들어온 것: {len(covered)}개\n")
    print("| 순위 | 개념 | 출제 점수 | 실제 출제 |")
    print("|---|---|---|---|")
    hit_names = {h[0] for h in hits}
    for i, s in enumerate(scores.scores, start=1):
        mark = "O" if s.name in hit_names else ""
        print(f"| {i} | {s.name} | {s.pct} | {mark} |")
    missed = [e["name"] for e in exam_concepts if e["name"] not in covered]
    if missed:
        print("\n상위 밖이거나 못 찾은 출제 개념: " + ", ".join(missed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
