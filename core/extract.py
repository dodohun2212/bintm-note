# -*- coding: utf-8 -*-
"""F02 페이지별 텍스트 추출, F04 개인정보 마스킹, 근거 쪽 고르기 (RAG 규칙 4.2)."""
from __future__ import annotations

import hashlib
import io
import re
from typing import Iterable, Optional

from config import MAX_EVIDENCE_PAGES, MAX_PAGES
from core.schemas import Material, Page

SUPPORTED_MATERIAL = ("pdf", "pptx")
SUPPORTED_AUDIO = ("m4a", "mp3", "wav")


class ExtractError(Exception):
    """E-01 지원하지 않는 형식, E-03 글자 없음 등."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def file_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def run_id(data: bytes) -> str:
    """파일 내용 해시 12자. 캐시 키로 쓴다."""
    return hashlib.sha256(data).hexdigest()[:12]


# ----------------------------------------------------------------- F04 마스킹

_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # 이메일
    re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"),  # 휴대전화
    re.compile(r"0\d{1,2}[-\s.]\d{3,4}[-\s.]\d{4}"),  # 일반 전화
    re.compile(r"(?<!\d)\d{8,10}(?!\d)"),  # 학번 (숫자 8~10자리)
]


def mask_pii(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub("[마스킹]", text)
    return text


# ----------------------------------------------------------------- F02 추출


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf(data: bytes) -> list[Page]:
    import pymupdf

    pages: list[Page] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            if i > MAX_PAGES:
                break
            pages.append(Page(n=i, text=_clean(page.get_text("text"))))
    return pages


def _extract_pptx(data: bytes) -> list[Page]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    pages: list[Page] = []
    for i, slide in enumerate(prs.slides, start=1):
        if i > MAX_PAGES:
            break
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text
                if t.strip():
                    parts.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text
            if notes.strip():
                parts.append("(노트) " + notes)
        pages.append(Page(n=i, text=_clean("\n".join(parts))))
    return pages


def extract_material(data: bytes, filename: str, mask: bool = True) -> Material:
    """PDF/PPTX 바이트 → Material. 지원하지 않는 형식이면 ExtractError('E-01')."""
    ext = file_ext(filename)
    if ext not in SUPPORTED_MATERIAL:
        raise ExtractError("E-01", f"지원하지 않는 형식: .{ext}")
    pages = _extract_pdf(data) if ext == "pdf" else _extract_pptx(data)
    if mask:
        pages = [Page(n=p.n, text=mask_pii(p.text)) for p in pages]
    chars = sum(len(p.text) for p in pages)
    return Material(name=filename, kind=ext, n_pages=len(pages), chars=chars, pages=pages)


def is_scanned(material: Material, empty_ratio: float = 0.8) -> bool:
    """글자 없는 쪽이 80% 이상이면 스캔본으로 본다 (E-03)."""
    if material.n_pages == 0:
        return True
    empty = sum(1 for p in material.pages if len(p.text.strip()) < 20)
    return empty / material.n_pages >= empty_ratio


# ------------------------------------------------------- AI에 보낼 텍스트 만들기


def pages_to_text(material: Material, pages: Optional[Iterable[int]] = None) -> str:
    """'=== 페이지 n ===' 구분으로 이어 붙인 텍스트. pages가 None이면 전체."""
    wanted = None if pages is None else set(pages)
    chunks = []
    for p in material.pages:
        if wanted is not None and p.n not in wanted:
            continue
        body = p.text if p.text.strip() else "(글자 없음)"
        chunks.append(f"=== 페이지 {p.n} ===\n{body}")
    return "\n\n".join(chunks)


_META_KEYWORDS = ("목차", "학습 목표", "학습목표", "연습문제", "연습 문제", "요약", "참고문헌", "참고 문헌", "차례")


_SECTION_LINE = re.compile(r"^\s*\d+\.\d+\s*\S")


def meta_pages_heuristic(material: Material) -> set[int]:
    """8.3 보정 규칙: 첫 80자에 목차·학습목표·연습문제·요약·참고문헌이 있거나, 앞 12줄 중 3줄 이상이
    '8.1 …'처럼 절 번호로 시작하면(목차) 메타 페이지. 1쪽(표지)은 항상."""
    meta = {1}
    for p in material.pages:
        head = p.text[:80]
        if any(k in head for k in _META_KEYWORDS):
            meta.add(p.n)
            continue
        lines = p.text.splitlines()[:12]
        if sum(1 for ln in lines if _SECTION_LINE.match(ln)) >= 3:
            meta.add(p.n)
    return meta


def evidence_pages(concept_pages: list[int], meta_pages: set[int], limit: int = MAX_EVIDENCE_PAGES) -> list[int]:
    """근거 쪽 고르기: 본문 쪽(메타 제외)을 앞에서부터, 최대 limit쪽. 본문 쪽이 없으면 전체에서."""
    body = [p for p in concept_pages if p not in meta_pages]
    chosen = body[:limit]
    if not chosen:
        chosen = concept_pages[:limit]
    return sorted(set(chosen))
