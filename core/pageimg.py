# -*- coding: utf-8 -*-
"""강의자료 PDF 한 쪽을 그림(JPEG)으로. 보완 설명·요약 노트 옆에 원본 페이지(그림·표 포함)를 보여 준다.

AI에게는 보내지 않는다(화면에만 쓴다). PPTX는 그림으로 바꿀 수 없어 None을 돌려준다.
"""
from __future__ import annotations

import base64
from typing import Optional

PAGE_IMG_WIDTH = 900      # 화면용 가로 픽셀
EXPORT_IMG_WIDTH = 720    # 내려받기 HTML용 (파일 크기를 줄인다)


def render_page(pdf_bytes: Optional[bytes], n: int, width: int = PAGE_IMG_WIDTH, quality: int = 80) -> Optional[bytes]:
    """n쪽(1부터)을 JPEG 바이트로. PDF가 아니거나 쪽이 없으면 None."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return None
    import pymupdf

    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            if not 1 <= n <= doc.page_count:
                return None
            page = doc[n - 1]
            zoom = width / max(1.0, page.rect.width)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return pix.tobytes("jpeg", jpg_quality=quality)
    except Exception:  # noqa: BLE001 - 깨진 PDF면 그림 없이 진행
        return None


def data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
