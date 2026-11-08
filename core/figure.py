# -*- coding: utf-8 -*-
"""문제에 붙는 그림(트리·배열·표). AI는 데이터만 JSON으로 주고, 그림은 코드가 그린다.

강의자료의 그림은 글자 조각으로만 추출되어 AI가 모양을 볼 수 없다. 그래서 문제에 그림이 필요하면
AI가 작은 예를 데이터로 만들고(figure), 이 파일이 화면과 내려받기 HTML에 같은 모양으로 그린다.
"""
from __future__ import annotations

import base64
import html
import math
import re
from typing import Optional

from core.schemas import FIG_ARRAY, FIG_TABLE, FIG_TREE, Figure

MAX_TREE_NODES = 31     # 깊이 0~4 (단말 최대 16개)
MAX_ARRAY_ITEMS = 20
MAX_TABLE_COLS = 6
MAX_TABLE_ROWS = 10
MAX_LABEL = 8           # 트리 노드 글자 수

# 화면(app.py)과 내려받기(export.py)가 같이 쓰는 모양. 밝은/어두운 화면 모두에서 보이도록 반투명 색.
FIGURE_CSS = """
.bf{margin:10px 0 6px}
.bf-cap{font-size:.86rem;color:#6e7781;margin:0 0 4px}
.bf-tree{display:block;width:100%;height:auto}
.bf-scroll{overflow-x:auto;max-width:100%}
.bf table{border-collapse:collapse;font-size:.95rem;margin:0;width:auto}
.bf th,.bf td{border:1px solid rgba(128,128,128,.45);padding:5px 10px;text-align:center;white-space:nowrap}
.bf th{background:rgba(128,128,128,.12);font-weight:700}
.bf-arr th{font-size:.8rem;font-weight:600;color:#6e7781;background:none}
"""


def _label(v: object) -> Optional[str]:
    if v is None:
        return None
    t = str(v).strip()
    if not t or t.lower() in ("null", "none"):
        return None
    return t[:MAX_LABEL]


def _cell(v: object) -> str:
    return "" if v is None else str(v).strip()


def check_figure(raw: object) -> Optional[Figure]:
    """AI가 준 figure를 검사한다. 형식이 틀리면 None (그림 없이 문제만 쓴다)."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind", "")).strip().lower()
    caption = _cell(raw.get("caption"))[:80]
    if kind == FIG_TREE:
        nodes = [_label(v) for v in (raw.get("nodes") or [])]
        while nodes and nodes[-1] is None:
            nodes.pop()
        if not nodes or len(nodes) > MAX_TREE_NODES or nodes[0] is None:
            return None
        if any(nodes[i] is not None and nodes[(i - 1) // 2] is None for i in range(1, len(nodes))):
            return None   # 부모 없는 노드
        return Figure(kind=FIG_TREE, caption=caption, nodes=nodes)
    if kind == FIG_ARRAY:
        items = [_cell(v) for v in (raw.get("items") or [])]
        if not items or len(items) > MAX_ARRAY_ITEMS:
            return None
        try:
            start = int(raw.get("start", 0))
        except (TypeError, ValueError):
            start = 0
        return Figure(kind=FIG_ARRAY, caption=caption, items=items, start=1 if start == 1 else 0)
    if kind == FIG_TABLE:
        header = [_cell(v) for v in (raw.get("header") or [])]
        rows = [[_cell(v) for v in r] for r in (raw.get("rows") or []) if isinstance(r, list)]
        if not header or len(header) > MAX_TABLE_COLS or not rows or len(rows) > MAX_TABLE_ROWS:
            return None
        if any(len(r) != len(header) for r in rows):
            return None
        return Figure(kind=FIG_TABLE, caption=caption, header=header, rows=rows)
    return None


# ----------------------------------------------------------------- 그리기


def tree_svg(nodes: list[Optional[str]]) -> tuple[str, int]:
    """트리 SVG 글과 가로 크기. 화면에서는 <img>로 넣는다(Streamlit이 HTML 안의 <svg>를 지우기 때문).
    <img> 안의 SVG는 화면 글자색을 물려받지 못하므로, 밝은/어두운 화면 모두에서 보이는 고정 색을 쓴다."""
    levels = int(math.log2(len(nodes))) + 1
    slot, gap_y, r = 48, 58, 17
    width = max(2 ** (levels - 1) * slot, 140)
    height = levels * gap_y + 4

    def pos(i: int) -> tuple[float, float]:
        d = int(math.log2(i + 1))
        k = i - (2 ** d - 1)
        return (k + 0.5) * width / 2 ** d, 24 + d * gap_y

    lines, circles = [], []
    for i, v in enumerate(nodes):
        if v is None:
            continue
        x, y = pos(i)
        if i > 0:
            px, py = pos((i - 1) // 2)
            lines.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#8b949e" '
                         'stroke-width="1.8"/>')
        size = 14 if len(v) <= 3 else 11 if len(v) <= 5 else 9
        circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#e8efff" stroke="#2563eb" stroke-width="1.8"/>'
                       f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="700" fill="#1f2328" '
                       f'text-anchor="middle" dominant-baseline="central">{html.escape(v)}</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'font-family="Pretendard, Apple SD Gothic Neo, Malgun Gothic, Noto Sans KR, sans-serif">'
           f'{"".join(lines)}{"".join(circles)}</svg>')
    return svg, width


def _array_table(fig: Figure) -> str:
    idx = "".join(f"<th>{fig.start + i}</th>" for i in range(len(fig.items)))
    val = "".join(f"<td>{html.escape(v)}</td>" for v in fig.items)
    return (f'<div class="bf-scroll"><table class="bf-arr"><tr><th>인덱스</th>{idx}</tr>'
            f"<tr><th>값</th>{val}</tr></table></div>")


def _table(fig: Figure) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in fig.header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in fig.rows)
    return f'<div class="bf-scroll"><table><tr>{head}</tr>{body}</table></div>'


def figure_html(fig: Optional[Figure]) -> str:
    """그림을 HTML 조각으로. 화면과 내려받기 HTML이 같이 쓴다. 글은 모두 이스케이프한다."""
    if fig is None:
        return ""
    if fig.kind == FIG_TREE and fig.nodes:
        svg, width = tree_svg(fig.nodes)
        src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
        alt = html.escape(figure_text(fig), quote=True)
        body = f'<img class="bf-tree" src="{src}" alt="{alt}" style="max-width:{width}px">' 
    elif fig.kind == FIG_ARRAY and fig.items:
        body = _array_table(fig)
    elif fig.kind == FIG_TABLE and fig.header:
        body = _table(fig)
    else:
        return ""
    cap = f'<div class="bf-cap">{html.escape(fig.caption)}</div>' if fig.caption else ""
    return f'<div class="bf">{cap}{body}</div>'


def figure_text(fig: Optional[Figure]) -> str:
    """그림을 글로 (채점·설명 프롬프트에 넣는 용도)."""
    if fig is None:
        return ""
    if fig.kind == FIG_TREE:
        return "트리(레벨 순서, 빈자리는 -): " + ", ".join(v if v is not None else "-" for v in fig.nodes)
    if fig.kind == FIG_ARRAY:
        return f"배열(인덱스 {fig.start}부터): [" + ", ".join(fig.items) + "]"
    if fig.kind == FIG_TABLE:
        return "표: " + " | ".join(fig.header) + " / " + " / ".join(" | ".join(r) for r in fig.rows)
    return ""


# ----------------------------------------------------------------- 문제 글 검사

_PAGE_REF = re.compile(r"p\.\s?\d+|\d+\s?(?:쪽|페이지)|슬라이드")
_FIG_WORD = re.compile(r"그림|도표|도식|다이어그램")
_SIDE_REF = re.compile(r"(?:위|아래|오른쪽|왼쪽|다음)\s?(?:의\s?)?(?:트리|표|그래프)")


def figure_problem(question: str, fig: Optional[Figure]) -> Optional[str]:
    """학생이 볼 수 없는 것을 가리키는 문제면 이유를, 괜찮으면 None.

    학생은 강의자료를 펴지 않고 문제 화면만 본다. 페이지 번호를 가리키면 안 되고,
    그림·표를 가리키려면 figure가 있어야 한다.
    """
    q = question or ""
    if _PAGE_REF.search(q):
        return "강의자료 페이지를 가리켰습니다"
    if fig is None and (_FIG_WORD.search(q) or _SIDE_REF.search(q)):
        return "그림이나 표를 가리켰지만 figure가 없습니다"
    return None
