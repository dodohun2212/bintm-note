# T-08 ~ T-11: 텍스트 추출, 스캔본 감지, 마스킹
import io
from pathlib import Path

from core.extract import extract_material, is_scanned, mask_pii, meta_pages_heuristic, evidence_pages

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"


def test_t08_sample_pdf_20_pages():
    m = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    assert m.kind == "pdf"
    assert m.n_pages == 20
    assert all(len(p.text.strip()) > 0 for p in m.pages)
    assert "업힙" in m.page_text(15)
    assert meta_pages_heuristic(m) == {1, 2, 3, 19, 20}


def test_t09_pptx_three_slides_with_table():
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    layout = prs.slide_layouts[5]
    for i in range(3):
        s = prs.slides.add_slide(layout)
        s.shapes.title.text = f"슬라이드 {i + 1} 제목"
        if i == 1:
            tbl = s.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
            tbl.cell(0, 0).text = "연산"
            tbl.cell(0, 1).text = "복잡도"
            tbl.cell(1, 0).text = "삽입"
            tbl.cell(1, 1).text = "O(log n)"
    buf = io.BytesIO()
    prs.save(buf)
    m = extract_material(buf.getvalue(), "test.pptx")
    assert m.kind == "pptx" and m.n_pages == 3
    assert "슬라이드 2 제목" in m.page_text(2)
    assert "삽입 | O(log n)" in m.page_text(2)


def test_t10_scanned_pdf_detected():
    import pymupdf

    doc = pymupdf.open()
    for _ in range(5):
        doc.new_page()
    data = doc.tobytes()
    m = extract_material(data, "scan.pdf")
    assert is_scanned(m)


def test_t11_masking():
    text = "학번 2021136001, 전화 010-1234-5678, 메일 a@b.ac.kr, 이름 홍길동"
    out = mask_pii(text)
    assert "2021136001" not in out and "010-1234-5678" not in out and "a@b.ac.kr" not in out
    assert out.count("[마스킹]") == 3
    assert "홍길동" in out


def test_unsupported_format():
    import pytest
    from core.extract import ExtractError

    with pytest.raises(ExtractError) as e:
        extract_material(b"xx", "a.hwp")
    assert e.value.code == "E-01"


def test_evidence_pages_prefers_body():
    assert evidence_pages([2, 3, 15, 16, 17, 20], {1, 2, 3, 20}) == [15, 16, 17]
    assert evidence_pages([2, 3], {1, 2, 3}) == [2, 3]
    assert evidence_pages(list(range(4, 20)), set(), limit=8) == list(range(4, 12))
