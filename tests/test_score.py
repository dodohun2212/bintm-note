# T-01 ~ T-07, T-14, T-15: 점수·우선순위·상태·인용 검사·페이지 범위
import json
from pathlib import Path

from core.diagnose import status_from_score
from core.extract import extract_material, meta_pages_heuristic
from core.priority import compute_priorities, priority_of
from core.schemas import Concept, Grading, ScoreRow, ScoresResult, Utterance
from core.score import compute_scores
from core.utterances import quote_in_transcript, validate_utterances
from core.concepts import validate_concepts

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
SAMPLE_PDF = HERE.parent / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
SAMPLE_SCRIPT = HERE.parent / "samples" / "강의녹음_대본_8장_트리와힙.md"


def _fixture_run():
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concepts = validate_concepts(json.loads((FIX / "01_개념추출_결과.json").read_text(encoding="utf-8")), material)
    transcript = SAMPLE_SCRIPT.read_text(encoding="utf-8")
    utts = validate_utterances(json.loads((FIX / "02_강조발화_결과.json").read_text(encoding="utf-8")), transcript,
                               concepts.concepts)
    scores = compute_scores(concepts.concepts, utts, set(concepts.meta_pages))
    return material, concepts, utts, scores


def test_t01_top3_matches_answer_key():
    _, concepts, utts, scores = _fixture_run()
    assert len(utts) >= 15, "대본에 실제로 있는 발화가 대부분 남아야 함"
    top3 = {s.name for s in scores.scores[:3]}
    assert top3 == {"이진 트리의 순회", "힙의 삭제 연산", "힙의 삽입 연산"}
    assert scores.scores[-1].name == "이진 탐색 트리의 삭제"
    assert scores.scores[0].pct == 100
    # 같은 입력 → 같은 결과
    again = compute_scores(concepts.concepts, utts, set(concepts.meta_pages))
    assert [s.pct for s in again.scores] == [s.pct for s in scores.scores]


def _concept(cid="c1", **kw):
    base = dict(id=cid, name="개념 " + cid, pages=[5], in_objectives=False, has_example=False, has_exercise=False)
    base.update(kw)
    return Concept(**base)


def test_t02_negative_clamped_to_zero():
    c = _concept(pages=[5])
    utts = [Utterance(concept_id="c1", quote="다음 주에", type="deferral", strength=3)] * 3
    s = compute_scores([c], utts, set())
    assert s.scores[0].raw == 0.0 and s.scores[0].pct == 0


def test_t03_meta_pages_excluded_from_body_count():
    c = _concept(pages=[2, 3, 15, 20])
    s = compute_scores([c], [], {2, 3, 20})
    assert s.scores[0].body_pages == [15]
    assert s.scores[0].raw == 1.0


def test_t04_repeated_utterance_counts_twice():
    c = _concept(pages=[5])
    one = compute_scores([c], [Utterance(concept_id="c1", quote="꼭", type="emphasis", strength=3)], set())
    two = compute_scores([c], [Utterance(concept_id="c1", quote="꼭", type="emphasis", strength=3)] * 2, set())
    assert two.scores[0].raw - 1.0 == 2 * (one.scores[0].raw - 1.0)


def test_t05_unknown_type_ignored():
    c = _concept(pages=[5])
    s = compute_scores([c], [Utterance(concept_id="c1", quote="x", type="foo", strength=3)], set())
    assert s.scores[0].raw == 1.0


def test_t06_priority_examples():
    assert priority_of(97, "모름") == 97
    assert priority_of(100, "헷갈림") == 50
    assert priority_of(96, "앎") == 0
    assert priority_of(50, "진단 안 함") == 25
    scores = ScoresResult(max_raw=10, scores=[
        ScoreRow(concept_id="a", name="힙 삭제", raw=9.7, pct=97, body_pages=[], reasons=[]),
        ScoreRow(concept_id="b", name="순회", raw=10, pct=100, body_pages=[], reasons=[]),
        ScoreRow(concept_id="c", name="힙 삽입", raw=9.6, pct=96, body_pages=[], reasons=[]),
        ScoreRow(concept_id="d", name="우선순위 큐", raw=5, pct=50, body_pages=[], reasons=[]),
    ])
    grading = {"a": Grading(score=0, status="모름"), "b": Grading(score=5, status="헷갈림"), "c": Grading(score=9, status="앎")}
    rows = compute_priorities(scores, grading)
    assert [(r.name, r.priority, r.action) for r in rows] == [
        ("힙 삭제", 97, "지금 당장"), ("순회", 50, "지금 당장"), ("우선순위 큐", 25, "다음"), ("힙 삽입", 0, "복습만")]
    assert rows[2].status == "진단 안 함"


def test_t07_status_thresholds():
    assert [status_from_score(s) for s in (8, 7, 4, 3, 0)] == ["앎", "헷갈림", "헷갈림", "모름", "모름"]


def test_t14_quote_must_exist_in_transcript():
    transcript = "오늘은 힙을 배웁니다. 이건 꼭   알아두세요."
    assert quote_in_transcript("이건 꼭 알아두세요.", transcript)
    assert not quote_in_transcript("시험에 나옵니다.", transcript)
    raw = {"utterances": [
        {"concept_id": "c1", "concept_name": "개념 c1", "quote": "이건 꼭 알아두세요.", "type": "emphasis", "strength": 3},
        {"concept_id": "c1", "concept_name": "개념 c1", "quote": "지어낸 문장", "type": "emphasis", "strength": 3},
        {"concept_id": "zz", "concept_name": "개념 c1", "quote": "오늘은 힙을 배웁니다.", "type": "skip", "strength": 5},
    ]}
    out = validate_utterances(raw, transcript, [_concept("c1")])
    assert len(out) == 2
    assert out[1].concept_id == "c1" and out[1].strength == 3


def test_t15_page_range_check():
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    raw = {"objectives_page": 3, "exercise_page": 19, "concepts": [
        {"id": "c1", "name": "A", "pages": [3, 99, 0, 15]},
        {"id": "c1", "name": "B", "pages": [4]},
        {"id": "c3", "name": "A", "pages": [5]},
    ]}
    r = validate_concepts(raw, material)
    assert [c.id for c in r.concepts] == ["c1", "c1_2"]
    assert r.concepts[0].pages == [3, 15]
    assert set(r.meta_pages) >= {1, 2, 3, 19, 20}
