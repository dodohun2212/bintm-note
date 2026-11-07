# -*- coding: utf-8 -*-
"""F10 결과를 HTML 파일 한 개로 (6.8 구조). 브라우저로 바로 열리고, 인쇄해도 보기 좋게 만든다.

파일 하나에 글꼴·색·표를 모두 넣는다(외부 파일·인터넷 연결 없이 열림). 화면 글은 모두 html.escape로 처리한다.
"""
from __future__ import annotations

import html
import re
from datetime import date
from typing import Optional

from core.diagnose import CIRCLED
from core.schemas import (STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, STATUS_UNSURE, Explanation, Grading,
                          PriorityRow, Question, ScoresResult)

NOTICE = "이 결과는 자료와 녹음의 신호를 규칙대로 더한 것으로, 실제 출제를 보장하지 않습니다."
TIERS = ("지금 당장", "다음", "복습만")
TIER_NOTE = {
    "지금 당장": "시험에 나올 가능성이 높은데 아직 잘 모르는 개념",
    "다음": "지금 당장 목록을 끝낸 뒤 볼 개념",
    "복습만": "이미 알거나 출제 가능성이 낮은 개념",
}
STATUS_CLASS = {STATUS_KNOWN: "known", STATUS_UNSURE: "unsure", STATUS_UNKNOWN: "unknown",
                STATUS_NOT_DIAGNOSED: "none"}
_PAGE_CITE = re.compile(r"\(p\.\s?\d+(?:\s?[,~\-–]\s?(?:p\.)?\s?\d+)*\)")

_CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1f2328;--sub:#59636e;--line:#e3e6ea;--accent:#2563eb;--accent-soft:#e8efff;
--known:#1a7f37;--known-bg:#dcf5e3;--unsure:#9a6700;--unsure-bg:#fff4cc;--unknown:#cf222e;--unknown-bg:#ffe3e3;
--none:#59636e;--none-bg:#eef0f2;--bar:#c9d6f5}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--ink:#e6e8eb;--sub:#a0a8b2;--line:#323843;
--accent:#7aa2ff;--accent-soft:#22304d;--known:#4ac26b;--known-bg:#173323;--unsure:#e3b341;--unsure-bg:#3a2f12;
--unknown:#ff7b7b;--unknown-bg:#3d1c1f;--none:#a0a8b2;--none-bg:#2a2f37;--bar:#34456b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",
"Noto Sans KR",system-ui,sans-serif;word-break:keep-all;overflow-wrap:anywhere}
main{max-width:820px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:28px;line-height:1.3;margin:0 0 6px}
h2{font-size:21px;margin:40px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:18px;margin:0 0 6px;line-height:1.4}
.meta{color:var(--sub);font-size:14px;margin:0}
.notice{margin:16px 0 0;padding:10px 14px;border-radius:10px;background:var(--accent-soft);font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:20px 0 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tile b{display:block;font-size:26px;line-height:1.2}
.tile span{color:var(--sub);font-size:13px}
.tile.now b{color:var(--unknown)}.tile.next b{color:var(--unsure)}.tile.review b{color:var(--known)}
.tier{margin:18px 0 6px;font-weight:700}
.tier small{font-weight:400;color:var(--sub);margin-left:6px}
.row{display:grid;grid-template-columns:36px 1fr auto;gap:10px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0}
.rank{font-weight:700;color:var(--sub);text-align:center}
.name{font-weight:600}
.bar{height:6px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.small{font-size:13px;color:var(--sub)}
.badge{display:inline-block;font-size:12.5px;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap}
.known{color:var(--known);background:var(--known-bg)}.unsure{color:var(--unsure);background:var(--unsure-bg)}
.unknown{color:var(--unknown);background:var(--unknown-bg)}.none{color:var(--none);background:var(--none-bg)}
.kind{color:var(--accent);background:var(--accent-soft)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0;
page-break-inside:avoid}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.gap{border-left:4px solid var(--unknown);background:var(--unknown-bg);padding:8px 12px;border-radius:0 8px 8px 0;
margin:0 0 12px}
.gap b{display:block;font-size:13px;color:var(--unknown)}
.card p{margin:0 0 10px}
.pg{display:inline-block;font-size:12px;font-weight:600;color:var(--accent);background:var(--accent-soft);
border-radius:6px;padding:0 6px;margin:0 2px;white-space:nowrap}
.warn{background:var(--unsure-bg);color:var(--ink);border-radius:8px;padding:8px 12px;font-size:14px;margin:0 0 10px}
.pages{font-size:14px;color:var(--sub)}
.q{font-weight:600;margin:0 0 8px}
ol.choices{list-style:none;padding:0;margin:0 0 10px}
ol.choices li{padding:6px 10px;border:1px solid var(--line);border-radius:8px;margin:4px 0}
ol.choices li.right{border-color:var(--known);background:var(--known-bg)}
ol.choices li.picked:not(.right){border-color:var(--unknown);background:var(--unknown-bg)}
.lbl{font-size:13px;color:var(--sub);font-weight:600;display:block;margin-top:8px}
.ans{white-space:pre-wrap;margin:0}
table{width:100%;border-collapse:collapse;font-size:14.5px;background:var(--card);border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:13px;color:var(--sub);font-weight:600;background:var(--none-bg)}
td.num{text-align:right;white-space:nowrap}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{font-size:12.5px;background:var(--none-bg);border-radius:6px;padding:1px 7px}
footer{margin-top:40px;color:var(--sub);font-size:13px;border-top:1px solid var(--line);padding-top:12px}
@media (max-width:560px){.tiles{grid-template-columns:1fr 1fr 1fr}.tile b{font-size:22px}h1{font-size:24px}
.row{grid-template-columns:28px 1fr}.row .right-col{grid-column:2}}
@media print{body{background:#fff}main{padding:0}.card,.row,.tile{border-color:#ccc}h2{page-break-after:avoid}}
"""


def _e(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _with_page_chips(escaped: str) -> str:
    return _PAGE_CITE.sub(lambda m: f'<span class="pg">{m.group(0)[1:-1]}</span>', escaped)


def _paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{_with_page_chips(_e(p)).replace(chr(10), '<br>')}</p>" for p in parts)


def _status_badge(status: str) -> str:
    return f'<span class="badge {STATUS_CLASS.get(status, "none")}">{_e(status)}</span>'


def _pages(pages: list[int]) -> str:
    return ", ".join(f"p.{p}" for p in pages)


def _priority_section(priorities: list[PriorityRow]) -> str:
    out = []
    rank = {p.concept_id: i for i, p in enumerate(priorities, start=1)}
    for tier in TIERS:
        rows = [p for p in priorities if p.action == tier]
        if not rows:
            continue
        out.append(f'<div class="tier">{_e(tier)} · {len(rows)}개<small>{_e(TIER_NOTE[tier])}</small></div>')
        for p in rows:
            out.append(
                f'<div class="row"><div class="rank">{rank[p.concept_id]}</div>'
                f'<div><div class="name">{_e(p.name)}</div>'
                f'<div class="small">출제 가능성 {p.exam_pct}% · 우선순위 점수 {p.priority}</div>'
                f'<div class="bar"><i style="width:{max(0, min(100, p.exam_pct))}%"></i></div></div>'
                f'<div class="right-col">{_status_badge(p.status)}</div></div>'
            )
    out.append('<p class="small">우선순위 점수 = 출제 가능성 × (1 − 이해도). 이해도: 앎 1.0 · 헷갈림 0.5 · 모름 0.0 · '
               '진단 안 함 0.5</p>')
    return "\n".join(out)


def _explanation_card(p: PriorityRow, e: Explanation) -> str:
    out = [f'<div class="card"><h3>{_e(p.name)}</h3>',
           f'<div class="badges">{_status_badge(p.status)}<span class="badge none">출제 {p.exam_pct}%</span>'
           f'<span class="badge kind">{_e(p.action)}</span></div>']
    if e.my_gap:
        out.append(f'<div class="gap"><b>내가 놓친 점</b>{_e(e.my_gap)}</div>')
    out.append(_paragraphs(e.explanation))
    if e.not_found:
        out.append(f'<div class="warn">올린 자료에서 찾지 못함 · {_e(e.not_found_note or "")} '
                   '교재 다른 장이나 수업 노트를 확인하세요.</div>')
    if e.check_pages:
        out.append(f'<div class="pages">다시 볼 페이지: {_e(_pages(e.check_pages))}</div>')
    out.append("</div>")
    return "".join(out)


def _diagnosis_card(name: str, q: Optional[Question], answer_text: str, g: Grading, chosen: Optional[int]) -> str:
    kind = q.kind if q is not None else ""
    out = [f'<div class="card"><h3>{_e(name)}</h3><div class="badges">{_status_badge(g.status)}'
           f'<span class="badge none">{g.score}/10</span>'
           + (f'<span class="badge kind">{_e(kind)}</span>' if kind else "")
           + (f'<span class="badge none">{_e(g.error_type)}</span>' if g.error_type else "") + "</div>"]
    if q is not None:
        out.append(f'<p class="q">{_e(q.question)}</p>')
        if q.is_mcq:
            items = []
            for i, c in enumerate(q.choices):
                cls = " ".join(x for x in ("right" if i == q.answer_index else "",
                                           "picked" if i == chosen else "") if x)
                tag = (" ✓ 정답 (내 답)" if i == q.answer_index and i == chosen else " ✓ 정답" if i == q.answer_index
                       else " ← 내 답" if i == chosen else "")
                items.append(f'<li class="{cls}">{CIRCLED[i]} {_e(c)}{_e(tag)}</li>')
            out.append(f'<ol class="choices">{"".join(items)}</ol>')
        else:
            out.append(f'<span class="lbl">내 답</span><p class="ans">{_e(answer_text or "(비워 둠)")}</p>')
    out.append(f'<span class="lbl">채점 이유</span><p class="ans">{_with_page_chips(_e(g.reason))}</p>')
    if q is not None:
        if q.is_mcq:
            if q.explanation:
                out.append(f'<span class="lbl">해설</span><p class="ans">{_with_page_chips(_e(q.explanation))}</p>')
        else:
            out.append(f'<span class="lbl">모범 답안</span><p class="ans">{_e(q.answer)}</p>')
        if q.source_pages:
            out.append(f'<div class="pages">근거: {_e(_pages(q.source_pages))}</div>')
    out.append("</div>")
    return "".join(out)


def to_html(material_name: str, scores: ScoresResult, grading: dict[str, Grading], priorities: list[PriorityRow],
            explanations: dict[str, Explanation], transcript_used: bool,
            questions: Optional[dict[str, Question]] = None, answer_texts: Optional[dict[str, str]] = None,
            choices: Optional[dict[str, Optional[int]]] = None, today: Optional[date] = None) -> str:
    """세션 결과를 HTML 문서 하나로. questions/answer_texts/choices가 없으면 진단 카드에 문제를 빼고 보여준다."""
    today = today or date.today()
    questions = questions or {}
    answer_texts = answer_texts or {}
    choices = choices or {}
    names = {s.concept_id: s.name for s in scores.scores}
    tier_count = {t: sum(1 for p in priorities if p.action == t) for t in TIERS}
    title = f"빈틈노트 결과 · {material_name}"

    body = ["<h1>빈틈노트 결과</h1>",
            f'<p class="meta">{_e(material_name)} · {today.isoformat()} · 녹음/대본 '
            + ("포함" if transcript_used else "없음 (자료만으로 계산)") + "</p>",
            f'<div class="notice">{_e(NOTICE)}</div>',
            '<div class="tiles">'
            f'<div class="tile now"><b>{tier_count["지금 당장"]}</b><span>지금 당장</span></div>'
            f'<div class="tile next"><b>{tier_count["다음"]}</b><span>다음</span></div>'
            f'<div class="tile review"><b>{tier_count["복습만"]}</b><span>복습만</span></div></div>']

    body.append("<h2>1. 공부 순서</h2>")
    body.append(_priority_section(priorities) if priorities else "<p>우선순위 없음</p>")

    body.append("<h2>2. 보완 설명</h2>")
    shown = [p for p in priorities if p.concept_id in explanations]
    if shown:
        body.extend(_explanation_card(p, explanations[p.concept_id]) for p in shown)
    else:
        body.append("<p>생성된 설명 없음</p>")

    body.append("<h2>3. 진단 결과</h2>")
    if grading:
        g_counts = {s: sum(1 for g in grading.values() if g.status == s) for s in (STATUS_KNOWN, STATUS_UNSURE, STATUS_UNKNOWN)}
        body.append('<p class="small">' + " · ".join(f"{k} {v}" for k, v in g_counts.items()) + "</p>")
        order = [p.concept_id for p in priorities if p.concept_id in grading] + [c for c in grading if c not in names]
        for cid in order:
            body.append(_diagnosis_card(names.get(cid, cid), questions.get(cid), answer_texts.get(cid, ""),
                                        grading[cid], choices.get(cid)))
    else:
        body.append("<p>진단하지 않음</p>")

    body.append("<h2>4. 출제 포인트 순위</h2>")
    if scores.scores:
        trs = []
        for i, s in enumerate(scores.scores, start=1):
            chips = "".join(f'<span class="chip">{_e(r.label)}</span>' for r in s.reasons) or "-"
            trs.append(f"<tr><td class=\"num\">{i}</td><td>{_e(s.name)}</td><td class=\"num\">{s.pct}%</td>"
                       f"<td><div class=\"chips\">{chips}</div></td></tr>")
        body.append("<table><thead><tr><th>순위</th><th>개념</th><th>출제 가능성</th><th>근거</th></tr></thead>"
                    f"<tbody>{''.join(trs)}</tbody></table>")
    else:
        body.append("<p>개념 없음</p>")

    body.append(f"<footer>{_e(NOTICE)}<br>빈틈노트 · KOREATECH Build for Students</footer>")
    return ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head>\n<body><main>\n"
            + "\n".join(body) + "\n</main></body></html>\n")
