# T-16 내보내기(HTML), T-17 전체 흐름 (BINTM_FAKE_AI=1 로 저장된 결과 사용)
import os
from pathlib import Path

os.environ["BINTM_FAKE_AI"] = "1"

from core.concepts import extract_concepts
from core.diagnose import diag_targets, grade_answer, grade_mcq, make_question, mcq_answer_text, question_kind
from core.explain import explain
from core.export import NOTICE, to_html
from core.extract import extract_material
from core.llm import Usage
from core.priority import compute_priorities
from core.schemas import QTYPE_ESSAY, QTYPE_MCQ
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
    pct = {s.concept_id: s.pct for s in scores.scores}
    targets = diag_targets(scores)
    assert targets and all(pct[cid] >= 20 for cid in targets)
    assert all(pct[s.concept_id] < 20 for s in scores.scores if s.concept_id not in targets)

    # 섞어서: 출제 가능성 50% 이상 서술형, 미만 객관식
    questions = {cid: make_question(by_id[cid], material, meta, usage, kind=question_kind(pct[cid])) for cid in targets}
    essays = [cid for cid in targets if questions[cid].kind == QTYPE_ESSAY]
    mcqs = [cid for cid in targets if questions[cid].kind == QTYPE_MCQ]
    assert essays and mcqs
    assert all(pct[cid] >= 50 for cid in essays) and all(pct[cid] < 50 for cid in mcqs)
    assert all(sum(r.score for r in questions[cid].rubric) == 10 for cid in essays)
    assert all(len(questions[cid].choices) == 4 and questions[cid].answer_index is not None for cid in mcqs)
    assert all(q.source_pages for q in questions.values())

    answers = {essays[0]: "x" * 80, essays[1]: "", essays[2]: "짧은 답"}
    grading = {cid: grade_answer(by_id[cid], questions[cid], ans, material, meta, usage) for cid, ans in answers.items()}
    assert grading[essays[1]].status == "모름" and grading[essays[1]].error_type == "무응답"
    assert grading[essays[0]].status == "앎"
    q = questions[mcqs[0]]
    grading[mcqs[0]] = grade_mcq(q, (q.answer_index + 1) % 4)
    answers[mcqs[0]] = mcq_answer_text(q, (q.answer_index + 1) % 4)
    assert grading[mcqs[0]].status == "모름" and grading[mcqs[0]].error_type == "오답"

    priorities = compute_priorities(scores, grading)
    assert len(priorities) == len(concepts.concepts)
    assert priorities[0].priority >= priorities[-1].priority

    exps = {}
    for p in priorities[:2] + [r for r in priorities if r.concept_id == mcqs[0]]:
        c = by_id[p.concept_id]
        exps[c.id] = explain(c, material, meta, p.status, questions.get(c.id), answers.get(c.id), grading.get(c.id), usage)
    assert all(e.source_pages for e in exps.values())

    doc = to_html(material.name, scores, grading, priorities, exps, transcript_used=True, questions=questions,
                  answer_texts=answers, choices={mcqs[0]: (q.answer_index + 1) % 4})
    assert doc.startswith("<!doctype html>") and doc.rstrip().endswith("</html>")
    assert doc.count("<h2>") == 4 and NOTICE in doc
    assert "객관식" in doc and "서술형" in doc and "내 답" in doc
    assert 'class="pg"' in doc  # (p.n) 인용이 페이지 배지로


def test_t16_export_with_empty_sections():
    from core.schemas import ScoresResult

    doc = to_html("x.pdf", ScoresResult(max_raw=0, scores=[]), {}, [], {}, transcript_used=False)
    assert "진단하지 않음" in doc and "생성된 설명 없음" in doc and NOTICE in doc and "자료만으로" in doc


def test_export_escapes_html():
    from core.schemas import Explanation, PriorityRow, Reason, ScoreRow, ScoresResult

    name = "<script>alert(1)</script>"
    scores = ScoresResult(max_raw=1, scores=[ScoreRow(concept_id="c1", name=name, raw=1, pct=100, body_pages=[1],
                                                      reasons=[Reason(kind="emphasis", points=1, label="<b>강조</b>")])])
    pri = [PriorityRow(concept_id="c1", name=name, exam_pct=100, status="진단 안 함", understanding=0.5, priority=50,
                       action="지금 당장")]
    exps = {"c1": Explanation(explanation="<img src=x onerror=alert(1)> 설명 (p.3)", source_pages=[3])}
    doc = to_html("<a.pdf>", scores, {}, pri, exps, transcript_used=False)
    assert "<script>" not in doc and "<img" not in doc and "<b>강조" not in doc
    assert "&lt;script&gt;" in doc and '<span class="pg">p.3</span>' in doc
