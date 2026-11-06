# T-16 내보내기, T-17 전체 흐름 (BINTM_FAKE_AI=1 로 저장된 결과 사용)
import os
from pathlib import Path

os.environ["BINTM_FAKE_AI"] = "1"

from core.concepts import extract_concepts
from core.diagnose import grade_answer, make_question
from core.explain import explain
from core.export import NOTICE, to_markdown
from core.extract import extract_material
from core.llm import Usage
from core.priority import compute_priorities
from core.score import compute_scores
from core.utterances import find_utterances

HERE = Path(__file__).resolve().parent
SAMPLE_PDF = HERE.parent / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
SAMPLE_SCRIPT = HERE.parent / "samples" / "강의녹음_대본_8장_트리와힙.md"


def test_t17_full_flow_without_real_ai():
    usage = Usage()
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concepts = extract_concepts(material, usage)
    transcript = SAMPLE_SCRIPT.read_text(encoding="utf-8")
    utts = find_utterances(concepts.concepts, transcript, usage)
    meta = set(concepts.meta_pages)
    scores = compute_scores(concepts.concepts, utts, meta)
    assert {s.name for s in scores.scores[:3]} == {"이진 트리의 순회", "힙의 삭제 연산", "힙의 삽입 연산"}

    by_id = {c.id: c for c in concepts.concepts}
    top = [by_id[s.concept_id] for s in scores.scores[:3]]
    questions = {c.id: make_question(c, material, meta, usage) for c in top}
    assert all(sum(r.score for r in q.rubric) == 10 for q in questions.values())
    assert all(q.source_pages for q in questions.values())

    answers = {top[0].id: "x" * 80, top[1].id: "", top[2].id: "짧은 답"}
    grading = {cid: grade_answer(by_id[cid], questions[cid], ans, material, meta, usage) for cid, ans in answers.items()}
    assert grading[top[1].id].status == "모름" and grading[top[1].id].error_type == "무응답"
    assert grading[top[0].id].status == "앎"

    priorities = compute_priorities(scores, grading)
    assert len(priorities) == len(concepts.concepts)
    assert priorities[0].priority >= priorities[-1].priority

    exps = {}
    for p in priorities[:2]:
        c = by_id[p.concept_id]
        exps[c.id] = explain(c, material, meta, p.status, questions.get(c.id), answers.get(c.id), grading.get(c.id), usage)
    assert all(e.source_pages for e in exps.values())

    md = to_markdown(material.name, scores, grading, priorities, exps, transcript_used=True)
    assert md.startswith("# 빈틈노트 결과")
    assert md.count("\n## ") == 4 and NOTICE in md


def test_t16_export_with_empty_sections():
    from core.schemas import ScoresResult

    md = to_markdown("x.pdf", ScoresResult(max_raw=0, scores=[]), {}, [], {}, transcript_used=False)
    assert "진단하지 않음" in md and "생성된 설명 없음" in md and NOTICE in md and "자료만으로" in md
