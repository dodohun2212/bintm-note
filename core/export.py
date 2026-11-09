# -*- coding: utf-8 -*-
"""F10 결과 내려받기 (6.8 구조). HTML 파일 두 개를 만든다 (v1.3).

- study_html: 공부 순서 + 오답노트. 오답노트 카드 하나에 문제·내 답·채점·정답·보완 설명이 함께 들어간다.
- notes_html: 시험 대비 요약 노트만.

파일마다 글꼴·색·표를 모두 넣는다(외부 파일·인터넷 연결 없이 열림). 강의자료 페이지 그림은 넣지 않는다(화면에서만 봄).
화면 글은 모두 html.escape로 처리한다.
"""
from __future__ import annotations

import html
import re
from datetime import date
from typing import Optional

from core.diagnose import CIRCLED
from core.figure import FIGURE_CSS, figure_html
from core.schemas import (DETAIL_FULL, DETAIL_MID, STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, STATUS_UNSURE,
                          Explanation, Grading, NoteSection, PriorityRow, Question, ScoresResult)

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
.ask{border-left:4px solid var(--accent);background:var(--accent-soft);padding:8px 12px;border-radius:0 8px 8px 0;
margin:0 0 12px}
.ask b{display:block;font-size:13px;color:var(--accent)}
.ask .my{display:block;color:var(--sub);margin:2px 0 6px}
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
.note h3 small{font-weight:400;color:var(--sub);font-size:14px;margin-left:6px}
.note ul{margin:4px 0 10px;padding-left:20px}
.note.short p{margin:0 0 6px}
.quote{font-size:14px;color:var(--sub);margin:2px 0}
details.card summary{cursor:pointer;font-weight:600}
details.card[open] summary{margin-bottom:10px}
.sec{font-size:15px;font-weight:700;margin:14px 0 4px;padding-top:10px;border-top:1px dashed var(--line)}
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


def _pg(pages: list[int]) -> str:
    return " ".join(f'<span class="pg">p.{n}</span>' for n in pages)


def _head(title: str, h1: str, material_name: str, today: date, transcript_used: bool) -> list[str]:
    return [f"<h1>{_e(h1)}</h1>",
            f'<p class="meta">{_e(material_name)} · {today.isoformat()} · 녹음/대본 '
            + ("포함" if transcript_used else "없음 (자료만으로 계산)") + "</p>",
            f'<div class="notice">{_e(NOTICE)}</div>']


def _doc(title: str, body: list[str]) -> str:
    body = body + [f"<footer>{_e(NOTICE)}<br>빈틈노트 · KOREATECH Build for Students</footer>"]
    return ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{_CSS}{FIGURE_CSS}</style></head>\n<body><main>\n"
            + "\n".join(body) + "\n</main></body></html>\n")


def _priority_section(priorities: list[PriorityRow], reasons: dict[str, list[str]]) -> str:
    """공부 순서. 출제 근거(학습목표, 강조 등)도 줄마다 붙여 출제 포인트 순위를 따로 두지 않는다."""
    out = []
    rank = {p.concept_id: i for i, p in enumerate(priorities, start=1)}
    for tier in TIERS:
        rows = [p for p in priorities if p.action == tier]
        if not rows:
            continue
        out.append(f'<div class="tier">{_e(tier)} · {len(rows)}개<small>{_e(TIER_NOTE[tier])}</small></div>')
        for p in rows:
            chips = "".join(f'<span class="chip">{_e(r)}</span>' for r in reasons.get(p.concept_id, []))
            out.append(
                f'<div class="row"><div class="rank">{rank[p.concept_id]}</div>'
                f'<div><div class="name">{_e(p.name)}</div>'
                f'<div class="small">출제 가능성 점수 {p.exam_pct}점 · 우선순위 점수 {p.priority}</div>'
                f'<div class="bar"><i style="width:{max(0, min(100, p.exam_pct))}%"></i></div>'
                + (f'<div class="chips" style="margin-top:6px">{chips}</div>' if chips else "")
                + f'</div><div class="right-col">{_status_badge(p.status)}</div></div>'
            )
    out.append('<p class="small">우선순위 점수 = 출제 점수 × (1 − 이해도). 이해도: 앎 1.0 · 헷갈림 0.5 · 모름 0.0 · '
               '진단 안 함 0.5</p>')
    return "\n".join(out)


def _explanation_part(e: Explanation, confusion: str = "") -> str:
    out = []
    if e.my_gap:
        out.append(f'<div class="gap"><b>내가 놓친 점</b>{_e(e.my_gap)}</div>')
    if confusion and e.confusion_reply:   # 학생이 적은 '헷갈린 점'에 대한 답 (v1.4)
        out.append(f'<div class="ask"><b>내가 헷갈린 점에 대한 답</b><span class="my">“{_e(confusion)}”</span>'
                   f"{_with_page_chips(_e(e.confusion_reply))}</div>")
    out.append(_paragraphs(e.explanation))
    if e.not_found:
        out.append(f'<div class="warn">올린 자료에서 찾지 못함 · {_e(e.not_found_note or "")} '
                   '교재 다른 장이나 수업 노트를 확인하세요.</div>')
    if e.check_pages:
        out.append(f'<div class="pages">다시 볼 페이지: {_pg(e.check_pages)}</div>')
    return "".join(out)


def review_card(rank: int, p: PriorityRow, q: Optional[Question], g: Optional[Grading], answer_text: str,
                chosen: Optional[int], e: Optional[Explanation], confusion: str = "") -> str:
    """오답노트 카드 하나: 문제 → 내 답 → 채점 → 정답·해설 → 보완 설명. 진단 결과와 보완 설명을 한곳에 모은다.

    confusion: 객관식에서 '확신 없이 골랐어요'와 함께 학생이 적은 헷갈린 점 (v1.4).
    """
    badges = [_status_badge(p.status)]
    if g is not None:
        badges.append(f'<span class="badge none">{g.score}/10</span>')
    if q is not None:
        badges.append(f'<span class="badge kind">{_e(q.kind)}</span>')
    if g is not None and g.error_type:
        badges.append(f'<span class="badge none">{_e(g.error_type)}</span>')
    badges.append(f'<span class="badge none">출제 점수 {p.exam_pct} · {_e(p.action)}</span>')
    out = [f'<h3>{rank}. {_e(p.name)}</h3><div class="badges">{"".join(badges)}</div>']
    if q is not None:
        out.append(f'<p class="q">{_e(q.question)}</p>')
        out.append(figure_html(q.figure))
        if q.is_mcq:
            items = []
            for i, c in enumerate(q.choices):
                cls = " ".join(x for x in ("right" if i == q.answer_index else "",
                                           "picked" if i == chosen else "") if x)
                tag = (" ✓ 정답 (내 답)" if i == q.answer_index and i == chosen else " ✓ 정답" if i == q.answer_index
                       else " ← 내 답" if i == chosen else "")
                items.append(f'<li class="{cls}">{CIRCLED[i]} {_e(c)}{_e(tag)}</li>')
            out.append(f'<ol class="choices">{"".join(items)}</ol>')
            if chosen is None:
                out.append('<p class="small">내 답: 모르겠어요</p>')
            if confusion and not (e is not None and e.confusion_reply):   # 답이 있으면 보완 설명 칸에서 함께 보여 준다
                out.append(f'<span class="lbl">내가 헷갈린 점</span><p class="ans">“{_e(confusion)}”</p>')
        else:
            out.append(f'<span class="lbl">내 답</span><p class="ans">{_e(answer_text or "모르겠어요")}</p>')
    if g is not None:
        out.append(f'<span class="lbl">채점</span><p class="ans">{_with_page_chips(_e(g.reason))}</p>')
    if q is not None:
        if q.is_mcq and q.explanation:
            out.append(f'<span class="lbl">해설</span><p class="ans">{_with_page_chips(_e(q.explanation))}</p>')
        elif not q.is_mcq and q.answer:
            out.append(f'<span class="lbl">모범 답안</span><p class="ans">{_with_page_chips(_e(q.answer))}</p>')
    if e is not None:
        out.append('<div class="sec">보완 설명</div>' + _explanation_part(e, confusion))
    elif q is not None and q.source_pages:
        out.append(f'<div class="pages">근거 페이지: {_pg(q.source_pages)}</div>')
    return "".join(out)


def study_html(material_name: str, scores: ScoresResult, grading: dict[str, Grading], priorities: list[PriorityRow],
               explanations: dict[str, Explanation], transcript_used: bool,
               questions: Optional[dict[str, Question]] = None, answer_texts: Optional[dict[str, str]] = None,
               choices: Optional[dict[str, Optional[int]]] = None, today: Optional[date] = None,
               confusions: Optional[dict[str, str]] = None) -> str:
    """내려받기 ① 공부 순서·오답노트.

    1. 공부 순서(출제 근거 포함) 2. 오답노트(틀림·헷갈림, 공부 순서대로) 3. 맞힌 문제(접어 둠)
    4. 진단하지 않은 개념의 보완 설명(있을 때만). choices의 None은 '모르겠어요'. confusions는 학생이 적은 헷갈린 점.
    """
    today = today or date.today()
    questions = questions or {}
    answer_texts = answer_texts or {}
    choices = choices or {}
    confusions = confusions or {}
    reasons = {s.concept_id: [r.label for r in s.reasons] for s in scores.scores}
    rank = {p.concept_id: i for i, p in enumerate(priorities, start=1)}
    tier_count = {t: sum(1 for p in priorities if p.action == t) for t in TIERS}

    def card(p: PriorityRow) -> str:
        cid = p.concept_id
        return review_card(rank[cid], p, questions.get(cid), grading.get(cid), answer_texts.get(cid, ""),
                           choices.get(cid), explanations.get(cid), confusions.get(cid, ""))

    body = _head(f"빈틈노트 공부 순서·오답노트 · {material_name}", "빈틈노트 공부 순서·오답노트", material_name, today,
                 transcript_used)
    body.append('<div class="tiles">'
                f'<div class="tile now"><b>{tier_count["지금 당장"]}</b><span>지금 당장</span></div>'
                f'<div class="tile next"><b>{tier_count["다음"]}</b><span>다음</span></div>'
                f'<div class="tile review"><b>{tier_count["복습만"]}</b><span>복습만</span></div></div>')

    body.append("<h2>1. 공부 순서</h2>")
    body.append(_priority_section(priorities, reasons) if priorities else "<p>우선순위 없음</p>")

    wrong = [p for p in priorities if p.concept_id in grading and grading[p.concept_id].status != STATUS_KNOWN]
    right = [p for p in priorities if p.concept_id in grading and grading[p.concept_id].status == STATUS_KNOWN]
    extra = [p for p in priorities if p.concept_id not in grading and p.concept_id in explanations]

    body.append("<h2>2. 오답노트</h2>")
    if wrong:
        body.append('<p class="small">진단에서 틀리거나 헷갈린 문제를 공부 순서대로 모았어요. 카드 하나에 문제, 내 답, 채점, '
                    '정답, 보완 설명이 함께 있어요.</p>')
        body.extend(f'<div class="card">{card(p)}</div>' for p in wrong)
    else:
        body.append("<p>틀리거나 헷갈린 문제가 없어요.</p>" if grading else "<p>진단하지 않음</p>")

    if right:
        body.append(f"<h2>3. 맞힌 문제 · {len(right)}개</h2>")
        body.append('<p class="small">눌러서 펼치면 문제와 정답을 다시 볼 수 있어요.</p>')
        body.extend(f'<details class="card"><summary>{rank[p.concept_id]}. {_e(p.name)} · {_e(p.status)} '
                    f'{grading[p.concept_id].score}/10</summary>{card(p)}</details>' for p in right)

    if extra:
        body.append(f"<h2>{4 if right else 3}. 진단하지 않은 개념 설명</h2>")
        body.extend(f'<div class="card">{card(p)}</div>' for p in extra)

    return _doc(f"빈틈노트 공부 순서·오답노트 · {material_name}", body)


def _note_card(p: PriorityRow, sec: NoteSection, quotes: list[tuple[str, str]]) -> str:
    short = sec.detail not in (DETAIL_FULL, DETAIL_MID)
    out = [f'<div class="card note{" short" if short else ""}"><h3>{_e(p.name)}<small>{_e(sec.detail)}</small></h3>',
           f'<div class="badges"><span class="badge kind">{_e(p.action)}</span>'
           f'<span class="badge none">출제 점수 {p.exam_pct}</span>{_status_badge(p.status)}</div>',
           _paragraphs(sec.summary)]
    if sec.key_points:
        out.append('<span class="lbl">핵심</span><ul>' + "".join(f"<li>{_with_page_chips(_e(k))}</li>"
                                                              for k in sec.key_points) + "</ul>")
    if sec.pitfalls:
        out.append('<span class="lbl">자주 하는 실수</span><ul>' + "".join(f"<li>{_with_page_chips(_e(k))}</li>"
                                                                     for k in sec.pitfalls) + "</ul>")
    for label, quote in quotes:
        out.append(f'<p class="quote">교수님 · {_e(label)}: “{_e(quote)}”</p>')
    if sec.source_pages:
        out.append(f'<div class="pages">근거 페이지: {_pg(sec.source_pages)}</div>')
    out.append("</div>")
    return "".join(out)


def notes_html(material_name: str, priorities: list[PriorityRow], notes: dict[str, NoteSection],
               note_order: Optional[list[str]] = None, quotes: Optional[dict[str, list[tuple[str, str]]]] = None,
               transcript_used: bool = False, today: Optional[date] = None) -> str:
    """내려받기 ② 시험 대비 요약 노트만. note_order: 강의 순서, quotes: 개념별 교수님 말 (유형, 인용)."""
    today = today or date.today()
    quotes = quotes or {}
    by_pid = {p.concept_id: p for p in priorities}
    order = [cid for cid in (note_order or list(notes)) if cid in notes and cid in by_pid]
    n = {d: sum(1 for cid in order if notes[cid].detail == d) for d in (DETAIL_FULL, DETAIL_MID)}
    body = _head(f"빈틈노트 시험 대비 요약 노트 · {material_name}", "빈틈노트 시험 대비 요약 노트", material_name, today,
                 transcript_used)
    body.append('<div class="tiles">'
                f'<div class="tile now"><b>{n[DETAIL_FULL]}</b><span>자세히</span></div>'
                f'<div class="tile next"><b>{n[DETAIL_MID]}</b><span>보통</span></div>'
                f'<div class="tile review"><b>{len(order) - n[DETAIL_FULL] - n[DETAIL_MID]}</b><span>짧게</span></div>'
                "</div>")
    if order:
        body.append('<p class="small" style="margin-top:16px">강의 순서대로 정리했어요. 시험에 나올 가능성이 높거나 진단에서 '
                    '틀린 개념일수록 자세히 썼어요.</p>')
        body.extend(_note_card(by_pid[cid], notes[cid], quotes.get(cid, [])) for cid in order)
    else:
        body.append("<p>요약 노트 없음</p>")
    return _doc(f"빈틈노트 시험 대비 요약 노트 · {material_name}", body)
