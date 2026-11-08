# T-25~T-30: 문제 그림(트리·배열·표), 그림·페이지를 가리키는 문제 다시 만들기, 원본 페이지 그림, 시험 대비 요약 노트
import os
from pathlib import Path

os.environ["BINTM_FAKE_AI"] = "1"

from core import diagnose, note, prompts
from core.extract import extract_material
from core.figure import check_figure, figure_html, figure_problem, figure_text, tree_svg
from core.note import lecture_order, make_note_section, note_detail, professor_quotes, short_section
from core.pageimg import data_uri, render_page
from core.schemas import (DETAIL_FULL, DETAIL_MID, DETAIL_SHORT, QTYPE_ESSAY, QTYPE_MCQ, Concept, Figure, Grading,
                          PriorityRow, Utterance)

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"


def _row(cid="c1", pct=60, status="진단 안 함", priority=30, action="다음"):
    return PriorityRow(concept_id=cid, name=cid, exam_pct=pct, status=status, understanding=0.5, priority=priority,
                       action=action)


# ----------------------------------------------------------------- T-25 그림 검사


def test_t25_check_figure():
    t = check_figure({"kind": "tree", "nodes": ["+", "*", "-", "a", "b", None, "d", None, None], "caption": "수식"})
    assert t is not None and t.nodes == ["+", "*", "-", "a", "b", None, "d"] and t.caption == "수식"
    a = check_figure({"kind": "array", "items": [90, 75, 80], "start": 1})
    assert a is not None and a.items == ["90", "75", "80"] and a.start == 1
    tb = check_figure({"kind": "table", "header": ["연산", "복잡도"], "rows": [["삽입", "O(log n)"]]})
    assert tb is not None and tb.rows == [["삽입", "O(log n)"]]
    for bad in (None, "tree", {"kind": "graph"}, {"kind": "tree", "nodes": []},
                {"kind": "tree", "nodes": [None, "a"]},                 # 루트 없음
                {"kind": "tree", "nodes": ["a", None, "b", "c"]},       # 3번(c)의 부모 1번이 빈자리
                {"kind": "tree", "nodes": [str(i) for i in range(32)]},  # 31칸 넘음
                {"kind": "array", "items": []}, {"kind": "array", "items": list(range(21))},
                {"kind": "table", "header": ["a", "b"], "rows": [["1"]]}, {"kind": "table", "header": [], "rows": []}):
        assert check_figure(bad) is None


# ----------------------------------------------------------------- T-26 그림 그리기


def test_t26_figure_html_and_text():
    tree = Figure(kind="tree", nodes=["<b>", "B", "C", None, "D"])
    svg, width = tree_svg(tree.nodes)
    assert svg.count("<circle") == 4 and svg.count("<line") == 3 and "&lt;b&gt;" in svg and "<b>" not in svg
    img = figure_html(tree)   # Streamlit이 <svg>를 지우므로 <img>(data URI)로 넣는다
    assert img.startswith('<div class="bf">') and "data:image/svg+xml;base64," in img and "<svg" not in img
    assert "&lt;b&gt;" in img and "<b>" not in img   # alt 글도 이스케이프
    arr = figure_html(Figure(kind="array", items=["90", "75"], start=1))
    assert "<th>1</th><th>2</th>" in arr and "<td>90</td>" in arr
    table = figure_html(Figure(kind="table", header=["연산"], rows=[["<i>삽입</i>"]], caption="표 설명"))
    assert "&lt;i&gt;" in table and "표 설명" in table
    assert figure_html(None) == "" and figure_text(None) == ""
    assert figure_text(tree) == "트리(레벨 순서, 빈자리는 -): <b>, B, C, -, D"
    assert figure_text(Figure(kind="array", items=["9", "7"], start=1)) == "배열(인덱스 1부터): [9, 7]"


# ----------------------------------------------------------------- T-27 그림·페이지를 가리키는 문제


def test_t27_figure_problem_rules():
    tree = Figure(kind="tree", nodes=["a"])
    assert figure_problem("p.9의 트리를 후위 순회하시오.", tree)          # 페이지 번호는 그림이 있어도 안 됨
    assert figure_problem("9쪽 예제를 보고 답하시오.", None)
    assert figure_problem("그림의 트리를 중위 순회한 결과를 쓰시오.", None)
    assert figure_problem("오른쪽 트리의 높이는?", None)
    assert figure_problem("아래 트리를 중위 순회한 결과를 쓰시오.", tree) is None
    assert figure_problem("힙의 삽입 절차를 설명하시오.", None) is None


def test_t27_question_is_remade_when_it_points_to_figure(monkeypatch):
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concept = Concept(id="c5", name="이진 트리의 순회", pages=[8, 9])
    prompts_seen = []
    bad_essay = {"question": "p.9 그림의 트리를 후위 순회하시오.", "answer": "a b * c d - +다.",
                 "rubric": [{"point": "결과", "score": 10}], "source_pages": [9]}
    good_essay = {**bad_essay, "question": "아래 트리를 후위 순회한 결과를 쓰시오.",
                  "figure": {"kind": "tree", "nodes": ["+", "*", "-", "a", "b", "c", "d"]}}

    def fake(prompt, **kw):
        prompts_seen.append(prompt)
        return bad_essay if len(prompts_seen) == 1 else good_essay

    monkeypatch.setattr(diagnose, "ask_json", fake)
    q = diagnose.make_question(concept, material, set(), kind=QTYPE_ESSAY)
    assert len(prompts_seen) == 2 and "## 다시 만들기" in prompts_seen[1] and "페이지" in prompts_seen[1]
    assert q.figure is not None and q.figure.nodes[0] == "+" and q.question.startswith("아래 트리")

    # 객관식이 두 번 다 그림을 가리키면 서술형으로 대신 만든다
    bad_mcq = {"question": "그림의 트리를 중위 순회한 결과는?", "choices": ["a", "b", "c", "d"], "answer_index": 0,
               "explanation": "x", "source_pages": [9]}
    calls = []

    def fake2(prompt, **kw):
        calls.append(kw["name"])
        return bad_mcq if kw["name"] == "03C" else good_essay

    monkeypatch.setattr(diagnose, "ask_json", fake2)
    q = diagnose.make_question(concept, material, set(), kind=QTYPE_MCQ)
    assert calls == ["03C", "03C", "03A"] and q.kind == QTYPE_ESSAY and q.figure is not None


def test_t27_fake_mode_questions_carry_figures():
    """가짜 AI 모드: 순회 서술형에는 트리, 배열 표현 객관식에는 배열이 붙는다 (화면 확인용)."""
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    q1 = diagnose.make_question(Concept(id="c5", name="이진 트리의 순회", pages=[8, 9]), material, set())
    q2 = diagnose.make_question(Concept(id="c4", name="완전 이진 트리의 배열 표현", pages=[7]), material, set(),
                                kind=QTYPE_MCQ)
    assert q1.figure.kind == "tree" and q2.figure.kind == "array" and q2.choices[q2.answer_index] == "30"
    # 채점·설명 프롬프트에는 그림이 글로 들어간다
    d = diagnose.question_for_prompt(q1)
    assert d["figure"].startswith("트리(레벨 순서")


# ----------------------------------------------------------------- T-28 원본 페이지 그림


def test_t28_render_page():
    data = SAMPLE_PDF.read_bytes()
    jpg = render_page(data, 9, width=400)
    assert jpg is not None and jpg[:2] == b"\xff\xd8" and len(jpg) < 200_000
    assert render_page(data, 0) is None and render_page(data, 21) is None
    assert render_page(b"PK\x03\x04 pptx", 1) is None and render_page(None, 1) is None
    assert data_uri(b"\xff\xd8").startswith("data:image/jpeg;base64,")


# ----------------------------------------------------------------- T-29 시험 대비 요약 노트


def test_t29_note_detail_rules():
    assert note_detail(_row(pct=90, status="앎", priority=0, action="복습만")) == DETAIL_FULL     # 출제 가능성 높음
    assert note_detail(_row(pct=40, status="모름", priority=40, action="다음")) == DETAIL_FULL    # 틀린 개념
    assert note_detail(_row(pct=60, status="모름", priority=60, action="지금 당장")) == DETAIL_FULL
    assert note_detail(_row(pct=30, status="헷갈림", priority=15, action="복습만")) == DETAIL_MID
    assert note_detail(_row(pct=44, status="진단 안 함", priority=22, action="다음")) == DETAIL_MID
    assert note_detail(_row(pct=30, status="앎", priority=0, action="복습만")) == DETAIL_SHORT
    assert note_detail(_row(pct=10, status="진단 안 함", priority=5, action="복습만")) == DETAIL_SHORT


def test_t29_lecture_order_and_quotes():
    cs = [Concept(id="b", name="b", pages=[2, 15]), Concept(id="a", name="a", pages=[2, 7]),
          Concept(id="c", name="c", pages=[2])]
    assert [c.id for c in lecture_order(cs, {2})] == ["a", "b", "c"]
    utts = [Utterance(concept_id="a", quote="q1", type="emphasis", strength=1),
            Utterance(concept_id="a", quote="q2", type="exam_hint", strength=3),
            Utterance(concept_id="a", quote="q2", type="exam_hint", strength=3),
            Utterance(concept_id="b", quote="q3", type="emphasis", strength=3)]
    assert [u.quote for u in professor_quotes("a", utts)] == ["q2", "q1"]


def test_t29_note_sections(monkeypatch):
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    concept = Concept(id="c11", name="힙의 삭제 연산", summary="루트를 꺼내고 내려간다.", pages=[3, 16, 17])
    calls = []
    real = note.ask_json

    def spy(prompt, **kw):
        calls.append(prompt)
        return real(prompt, **kw)

    monkeypatch.setattr(note, "ask_json", spy)
    # 짧게: AI 호출 없이 개념 추출의 한 줄 요약
    short = make_note_section(concept, material, {3}, _row("c11", 10, "앎", 0, "복습만"))
    assert not calls and short.detail == DETAIL_SHORT and short.summary == concept.summary and not short.from_ai
    assert short_section(concept, {3}).source_pages == [16, 17]
    # 자세히: 프롬프트 05에 정도·진단·교수님 말이 들어가고, 근거 쪽은 자료 범위 안으로
    g = Grading(score=0, status="모름", error_type="개념 혼동", reason="삽입과 혼동")
    utts = [Utterance(concept_id="c11", quote="더 큰 자식과 비교한다, 이 부분에서 실수가 많아요.",
                      type="mistake_warning", strength=3)]
    full = make_note_section(concept, material, {3}, _row("c11", 88, "모름", 88, "지금 당장"), utts, g)
    assert len(calls) == 1 and "**자세히**" in calls[0] and "삽입과 혼동" in calls[0] and "실수가 많아요" in calls[0]
    assert full.detail == DETAIL_FULL and full.from_ai and full.pitfalls and len(full.key_points) <= 5
    assert full.summary.count("\n\n") >= 1 and set(full.source_pages) <= {16, 17}
    mid = make_note_section(concept, material, {3}, _row("c11", 44, "진단 안 함", 22, "다음"))
    assert "**보통**" in calls[-1] and mid.detail == DETAIL_MID
    assert prompts.placeholders("05") == {"CONCEPT_NAME", "DETAIL", "CONCEPT_JSON", "PAGES"}


# ----------------------------------------------------------------- T-30 내보내기에 요약 노트·그림


def test_t30_export_has_notes_figures_and_pages():
    from core.export import to_html
    from core.schemas import Explanation, NoteSection, Question, ScoreRow, ScoresResult

    scores = ScoresResult(max_raw=1, scores=[ScoreRow(concept_id="c1", name="순회", raw=1, pct=80, body_pages=[9],
                                                      reasons=[])])
    pri = [_row("c1", 80, "모름", 80, "지금 당장").model_copy(update={"name": "순회"})]
    q = Question(question="아래 트리를 후위 순회하시오.", answer="a b * 다.", source_pages=[9],
                 figure=Figure(kind="tree", nodes=["+", "a", "b"]))
    g = {"c1": Grading(score=0, status="모름", reason="틀림")}
    exps = {"c1": Explanation(explanation="설명 (p.9)", check_pages=[9, 8], source_pages=[9])}
    notes = {"c1": NoteSection(concept_id="c1", detail="자세히", summary="<b>요약</b> (p.9)", key_points=["핵심"],
                               pitfalls=["실수"], source_pages=[9])}
    img = data_uri(render_page(SAMPLE_PDF.read_bytes(), 9, width=300))
    doc = to_html("s.pdf", scores, g, pri, exps, transcript_used=True, questions={"c1": q}, answer_texts={"c1": "x"},
                  notes=notes, note_order=["c1"], quotes={"c1": [("시험 힌트", "이건 시험에 내기 좋죠")]},
                  page_images={9: img})
    assert doc.count("<h2>") == 6 and "3. 시험 대비 요약 노트" in doc and "6. 강의자료 페이지" in doc
    assert doc.count("data:image/svg+xml;base64,") == 1                # 문제 그림 (트리)
    assert 'id="pg-9"' in doc and doc.count("data:image/jpeg") == 1     # 같은 쪽 그림은 한 번만
    assert 'href="#pg-9"' in doc and '<span class="pg">p.8</span>' in doc
    assert "&lt;b&gt;요약" in doc and "<b>요약" not in doc and "이건 시험에 내기 좋죠" in doc
