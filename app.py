# -*- coding: utf-8 -*-
"""빈틈노트 화면 (S01~S05). 계산은 전부 core/ 에 있고, 이 파일은 화면만 다룬다."""
from __future__ import annotations

import html
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import streamlit as st


def _drop_stale_modules() -> None:
    """배포로 core/·config.py 파일이 바뀌었으면 메모리에 있던 예전 모듈을 버리고 새로 읽게 한다 (v1.6).

    Streamlit Cloud는 새 코드를 받아도 app.py만 다시 실행하고, 이미 불러온 core 모듈은 예전 것을 쓴다.
    그러면 새로 추가한 함수를 못 찾아 ImportError가 난다. 처음 실행이거나 파일 시각이 바뀌면 모두 버린다.
    예전 모듈의 객체를 들고 있을 수 있는 서버 공용 캐시(st.cache_resource)도 함께 비운다.
    """
    import sys
    names = [n for n in sys.modules if n == "config" or n == "core" or n.startswith("core.")]
    now = {n: os.path.getmtime(f) for n in names if (f := getattr(sys.modules[n], "__file__", None)) and os.path.exists(f)}
    seen = getattr(sys, "_bintm_mtimes", None)
    if seen is not None and all(seen.get(n, t) == t for n, t in now.items()):
        return
    if seen is not None or names:
        for n in names:
            del sys.modules[n]
        st.cache_resource.clear()
    sys._bintm_mtimes = None   # 아래에서 새로 불러온 뒤 기록한다


_drop_stale_modules()

from config import (AUTO_EXPLAIN_TOP, CONFUSION_MAX_CHARS, DIAG_MIN_PCT, ESSAY_MIN_PCT, LLM_MODEL,
                    MAX_ANALYSES_PER_DAY, MAX_ANALYSES_PER_SESSION, MAX_AUDIO_MB, MAX_MATERIAL_MB, MAX_PAGES,
                    QUICK_DIAG_TOP, STT_MODEL)
from core import stt
from core.concepts import NoConceptsError, extract_concepts
from core.diagnose import (CIRCLED, MODE_MIX, QUESTION_MODES, REASON_BLANK, REASON_DONT_KNOW, diag_targets,
                           empty_grading, example_answers, grade_answer, grade_mcq, is_answered, make_question,
                           mcq_answer_text, question_kind)
from core.explain import explain
from core.export import notes_html, study_html
from core.extract import (SUPPORTED_AUDIO, SUPPORTED_MATERIAL, ExtractError, extract_material, file_ext, is_scanned,
                          mask_pii, run_id)
from core.figure import FIGURE_CSS, figure_html
from core.guard import DailyCounter, ResultCache, session_left
from core.llm import LLMError, LLMJsonError, LLMKeyError, Usage, fake_mode, has_key
from core.note import lecture_order, make_note_section, note_detail, professor_quotes, short_section
from core.pageimg import PAGE_IMG_WIDTH, render_page
from core.priority import compute_priorities
from core.schemas import (DETAIL_FULL, DETAIL_MID, DETAIL_SHORT, STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN,
                          STATUS_UNSURE, Concept, ConceptsResult, Explanation, Grading, Material, NoteSection,
                          PriorityRow, Question, ScoreRow, Utterance)
from core.score import UTTERANCE_LABELS, WEIGHTS_VERSION, compute_scores
from core.stt import STTError
from core.utterances import find_utterances


def _record_module_mtimes() -> None:
    import sys
    sys._bintm_mtimes = {n: os.path.getmtime(m.__file__) for n, m in list(sys.modules.items())
                         if (n == "config" or n.startswith("core.")) and getattr(m, "__file__", None)}


_record_module_mtimes()

ROOT = Path(__file__).resolve().parent
SAMPLE_PDF = ROOT / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
SAMPLE_SCRIPT = ROOT / "samples" / "강의녹음_대본_8장_트리와힙.md"
NOTICE = "출제를 보장하지 않습니다. 공부 우선순위를 정하는 참고용입니다."
STEPS = ["① 자료 올리기", "② 출제 포인트", "③ 취약점 진단", "④ 공부 순서", "⑤ 안내·설정"]
STATUS_CLS = {STATUS_KNOWN: "known", STATUS_UNSURE: "unsure", STATUS_UNKNOWN: "unknown", STATUS_NOT_DIAGNOSED: "none"}
TIERS = [("지금 당장", "시험에 나올 가능성이 높은데 아직 잘 모르는 개념이에요. 여기부터 보세요."),
         ("다음", "지금 당장 목록을 끝낸 뒤에 볼 개념이에요."),
         ("복습만", "이미 알거나 출제 가능성이 낮은 개념이에요. 시간이 남으면 훑어보세요.")]

st.set_page_config(page_title="빈틈노트", page_icon="📝", layout="centered")

# 화면을 읽기 쉽게: 본문 폭을 좁히고 글자·줄 간격을 키운다. 색은 밝은/어두운 테마 모두에서 보이도록 반투명으로.
CSS = """
<style>
[data-testid="stMainBlockContainer"], .block-container {max-width: 860px; padding-top: 4.2rem; padding-bottom: 5rem;}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {font-size: 1.04rem; line-height: 1.75;}
h1 {word-break: keep-all;}
@media (max-width: 640px) {h1 {font-size: 2rem !important;}}
.bt {font-size: 1.04rem; line-height: 1.75; word-break: keep-all; overflow-wrap: anywhere;}
.bt-sub {color: #6e7781; font-size: 1.05rem; margin: -0.6rem 0 0.2rem;}
.bt-steps {display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 0 0 0.2rem;}
.bt-step {font-size: .86rem; padding: 3px 11px; border-radius: 999px; border: 1px solid rgba(128,128,128,.32);
  color: #6e7781; white-space: nowrap;}
.bt-step.on {background: #2563eb; border-color: #2563eb; color: #fff; font-weight: 700;}
.bt-step.done {color: #1a7f37; border-color: rgba(26,127,55,.45);}
.bt-arrow {color: rgba(128,128,128,.6); font-size: .9rem;}
.bt-badge {display: inline-block; font-size: .82rem; font-weight: 700; padding: 2px 10px; border-radius: 999px;
  margin: 0 4px 4px 0; white-space: nowrap;}
.bt-known {color: #1a7f37; background: rgba(26,127,55,.13);}
.bt-unsure {color: #9a6700; background: rgba(212,167,44,.2);}
.bt-unknown {color: #cf222e; background: rgba(207,34,46,.11);}
.bt-none {color: #6e7781; background: rgba(110,119,129,.13);}
.bt-kind {color: #2563eb; background: rgba(37,99,235,.11);}
.bt-tiles {display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 4px 0;}
.bt-tile {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 10px 14px;}
.bt-tile b {display: block; font-size: 1.75rem; line-height: 1.25;}
.bt-tile span {font-size: .88rem; color: #6e7781;}
.bt-tile.red b {color: #cf222e;} .bt-tile.amber b {color: #9a6700;} .bt-tile.green b {color: #1a7f37;}
.bt-tile.blue b {color: #2563eb;}
.bt-list {border-top: 1px solid rgba(128,128,128,.2);}
.bt-row {display: grid; grid-template-columns: 2.2rem 1fr 3.8rem; gap: 10px; align-items: center;
  padding: 10px 2px; border-bottom: 1px solid rgba(128,128,128,.2);}
.bt-row.dim {opacity: .55;}
.bt-rank {font-weight: 800; color: #6e7781; text-align: center; font-size: 1.05rem;}
.bt-name {font-weight: 700; font-size: 1.06rem; line-height: 1.45;}
.bt-pct {font-weight: 800; text-align: right; font-size: 1.1rem;}
.bt-pct small {font-size: .75rem; font-weight: 600; margin-left: 1px; color: #6e7781;}
.bt-bar {height: 7px; border-radius: 4px; background: rgba(128,128,128,.18); margin: 6px 0 6px; overflow: hidden;}
.bt-bar i {display: block; height: 100%; background: #2563eb; border-radius: 4px;}
.bt-chip {display: inline-block; font-size: .8rem; padding: 1px 8px; border-radius: 6px; margin: 2px 4px 0 0;
  background: rgba(128,128,128,.13);}
.bt-chip.neg {color: #6e7781; text-decoration: line-through;}
.bt-split {font-size: .9rem; color: #6e7781; padding: 14px 4px 6px;}
.bt-qhead {display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 4px;}
.bt-qno {font-weight: 800; color: #2563eb; font-size: 1.05rem; margin-right: 2px;}
.bt-q {font-size: 1.14rem; font-weight: 600; line-height: 1.65; margin: 4px 0 2px;}
.bt-gap {border-left: 4px solid #cf222e; background: rgba(207,34,46,.07); padding: 8px 12px;
  border-radius: 0 8px 8px 0; margin: 4px 0 12px;}
.bt-gap b {display: block; font-size: .82rem; color: #cf222e;}
.bt-ex p {margin: 0 0 12px;}
.bt-ask {border-left: 4px solid #2563eb; background: rgba(37,99,235,.07); padding: 8px 12px;
  border-radius: 0 8px 8px 0; margin: 4px 0 12px;}
.bt-ask b {display: block; font-size: .82rem; color: #2563eb;}
.bt-ask .bt-my {display: block; color: #6e7781; font-size: .95rem; margin: 2px 0 6px;}
.bt-pg {display: inline-block; font-size: .78rem; font-weight: 700; color: #2563eb; background: rgba(37,99,235,.11);
  border-radius: 6px; padding: 0 6px; margin: 0 2px; white-space: nowrap;}
.bt-warn {background: rgba(212,167,44,.16); border-radius: 8px; padding: 8px 12px; font-size: .95rem; margin: 0 0 10px;}
.bt-pages {font-size: .92rem; color: #6e7781;}
.bt-lbl {display: block; font-size: .82rem; font-weight: 700; color: #6e7781; margin-top: 10px;}
.bt .bt-choices {list-style: none; padding-left: 0 !important; margin: 6px 0 !important;}
.bt .bt-choices li {margin-left: 0 !important; padding: 7px 12px; border: 1px solid rgba(128,128,128,.28); border-radius: 8px; margin: 5px 0;}
.bt .bt-choices li.right {border-color: rgba(26,127,55,.6); background: rgba(26,127,55,.1);}
.bt .bt-choices li.picked:not(.right) {border-color: rgba(207,34,46,.6); background: rgba(207,34,46,.08);}
.bt-tier {font-size: 1.3rem; font-weight: 800; margin: 18px 0 0;}
.bt-tier small {display: block; font-size: .92rem; font-weight: 400; color: #6e7781;}
.bt-note ul {margin: 2px 0 8px; padding-left: 1.3rem;}
.bt-quote {font-size: .95rem; color: #6e7781; margin: 2px 0;}
.bt-miss {color: #cf222e; font-weight: 700; font-size: .95rem; margin: 6px 0 2px;}
/* AI를 기다리는 동안의 "…만드는 중" 안내는 화면 맨 위에 생겨서, 버튼을 누르려고 아래로 내려 둔 사람은 못 봤다.
   어디까지 내려 있든 보이게 화면 아래 가운데에 띄운다 (v1.8). */
[data-testid="stSpinner"] {position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 1000;
  background: #2563eb; padding: 10px 18px; border-radius: 999px; box-shadow: 0 4px 16px rgba(0,0,0,.2);
  max-width: calc(100vw - 32px); width: max-content;}
[data-testid="stSpinner"], [data-testid="stSpinner"] * {color: #fff !important;}
""" + FIGURE_CSS + """
</style>
"""


# ----------------------------------------------------------------- 준비


def load_secrets_into_env() -> None:
    """키는 st.secrets → 환경변수 순. core/는 환경변수만 읽는다 (BR-08)."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(key):
            continue
        try:
            value = st.secrets.get(key)  # type: ignore[attr-defined]
        except Exception:
            value = None
        if value:
            os.environ[key] = str(value)


DEFAULTS = dict(
    step=1, material=None, transcript=None, transcript_source=None, concepts=None, utterances=None, scores=None,
    questions={}, answers={}, dont_know={}, mcq_choice={}, guessed={}, confusion={}, grading={}, priorities=None,
    explanations={}, run_id=None, errors=[], usage=None, from_sample=False, diag_ids=[], q_mode=MODE_MIX, q_mode_used=None,
    material_bytes=None, notes={}, notes_failed=[], quick_diag=False,
    show_missing=False, grade_failed=[], grade_error=None, explain_failed=[], q_failed=[],
)


def init_state() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, (dict, list)) else type(v)()
    if st.session_state.usage is None:
        st.session_state.usage = Usage()
    st.session_state.setdefault("analyses_used", 0)   # reset_state()로 지우지 않는다 (v1.5)


def reset_state() -> None:
    for k in list(DEFAULTS):
        del st.session_state[k]
    init_state()


def go(step: int) -> None:
    st.session_state.step = step
    st.rerun()


def error_message(e: Exception) -> str:
    """9장 표의 문구로 바꾼다."""
    if isinstance(e, LLMKeyError):
        return "AI 키가 설정되지 않았어요. README의 설정 방법을 보세요. (E-06)"
    if isinstance(e, LLMJsonError):
        return "AI 답을 읽지 못했어요. 다시 시도해 주세요. (E-08)"
    if isinstance(e, LLMError):
        return "AI 서버와 연결이 어려워요. 잠시 후 다시 시도 버튼을 눌러 주세요. (E-07)"
    if isinstance(e, NoConceptsError):
        return "이 자료에서 개념을 찾지 못했어요. 강의 슬라이드나 교재 한 장인지 확인해 주세요. (E-09)"
    if isinstance(e, STTError):
        return "녹음을 글자로 바꾸지 못했어요. 대본 붙여넣기를 쓰거나, 녹음 없이 계속할 수 있어요. (E-05)"
    return "알 수 없는 오류가 났어요. 처음부터 다시 해 주세요."


def show_error(msg: str, detail: str | None = None) -> None:
    st.error(msg)
    if detail:
        with st.expander("기술 메시지"):
            st.code(detail)


# ----------------------------------------------------------------- 화면 조각 (HTML)

_PAGE_CITE = re.compile(r"\(p\.\s?\d+(?:\s?[,~\-–]\s?(?:p\.)?\s?\d+)*\)")


def h(text: object) -> str:
    """화면에 넣는 글은 모두 이스케이프. ~ 와 $ 도 바꿔 취소선·수식으로 읽히지 않게 한다."""
    return html.escape(str(text if text is not None else "")).replace("~", "&#126;").replace("$", "&#36;")


def show(fragment: str) -> None:
    st.html(f'<div class="bt">{fragment}</div>')


def badge(text: str, cls: str) -> str:
    return f'<span class="bt-badge bt-{cls}">{h(text)}</span>'


def status_badge(status: str) -> str:
    return badge(status, STATUS_CLS.get(status, "none"))


def tiles(items: list[tuple[str, object, str]]) -> str:
    return '<div class="bt-tiles">' + "".join(
        f'<div class="bt-tile {color}"><b>{h(value)}</b><span>{h(label)}</span></div>' for label, value, color in items
    ) + "</div>"


def page_chips(escaped: str) -> str:
    return _PAGE_CITE.sub(lambda m: f'<span class="bt-pg">{m.group(0)[1:-1]}</span>', escaped)


def paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{page_chips(h(p)).replace(chr(10), '<br>')}</p>" for p in parts)


def page_head(step: int, title: str, sub: str) -> None:
    has = [True, st.session_state.scores is not None, st.session_state.scores is not None,
           bool(st.session_state.grading)]
    parts = []
    for i, label in enumerate(STEPS[:4], start=1):
        cls = "on" if i == step else ("done" if has[i - 1] and i < step else "")
        parts.append(f'<span class="bt-step {cls}">{h(label)}</span>')
    show('<div class="bt-steps">' + '<span class="bt-arrow">›</span>'.join(parts) + "</div>")
    st.title(title, anchor=False)
    show(f'<div class="bt-sub">{h(sub)}</div>')


def reason_chips(reasons) -> str:
    """점수 근거를 짧은 배지로. 교수님 발화는 유형별로 묶어 '강조 ×3'처럼."""
    chips: list[tuple[str, bool]] = []
    grouped: dict[str, list[float]] = {}
    for r in reasons:
        if r.kind in ("objective", "page", "example", "exercise"):
            chips.append((r.label, r.points >= 0))
        else:
            grouped.setdefault(r.kind, []).append(r.points)
    for kind, pts in grouped.items():
        label = UTTERANCE_LABELS.get(kind, kind) + (f" ×{len(pts)}" if len(pts) > 1 else "")
        chips.append((label, sum(pts) >= 0))
    return "".join(f'<span class="bt-chip{"" if pos else " neg"}">{h(t)}</span>' for t, pos in chips)


def concept_row(rank: int, s: ScoreRow, dim: bool = False) -> str:
    return (f'<div class="bt-row{" dim" if dim else ""}"><div class="bt-rank">{rank}</div>'
            f'<div><div class="bt-name">{h(s.name)}</div>'
            f'<div class="bt-bar"><i style="width:{max(0, min(100, s.pct))}%"></i></div>'
            f'<div>{reason_chips(s.reasons)}</div></div><div class="bt-pct">{s.pct}<small>점</small></div></div>')


def confusion_html(confusion: str, reply: str | None = None) -> str:
    """학생이 적은 '헷갈린 점'과 (있으면) 그에 대한 답 (v1.4)."""
    if not confusion:
        return ""
    if reply:
        return (f'<div class="bt-ask"><b>💬 내가 헷갈린 점에 대한 답</b><span class="bt-my">“{h(confusion)}”</span>'
                f"{page_chips(h(reply))}</div>")
    return f'<span class="bt-lbl">💬 내가 헷갈린 점</span><div>“{h(confusion)}”</div>'


def explanation_html(e: Explanation, confusion: str = "") -> str:
    out = []
    if e.my_gap:
        out.append(f'<div class="bt-gap"><b>내가 놓친 점</b>{h(e.my_gap)}</div>')
    if confusion and e.confusion_reply:
        out.append(confusion_html(confusion, e.confusion_reply))
    out.append(f'<div class="bt-ex">{paragraphs(e.explanation)}</div>')
    if e.not_found:
        out.append(f'<div class="bt-warn">⚠️ 올린 자료에서 찾지 못함 · {h(e.not_found_note or "")} '
                   '교재 다른 장이나 수업 노트를 확인하세요.</div>')
    if e.check_pages:
        out.append(f'<div class="bt-pages">📖 다시 볼 페이지: {h(", ".join(f"p.{n}" for n in e.check_pages))}</div>')
    return "".join(out)


def choices_html(q: Question, chosen: int | None) -> str:
    items = []
    for i, c in enumerate(q.choices):
        cls = " ".join(x for x in ("right" if i == q.answer_index else "", "picked" if i == chosen else "") if x)
        mark = " ✓ 정답" if i == q.answer_index else (" ← 내 답" if i == chosen else "")
        if i == q.answer_index and i == chosen:
            mark = " ✓ 정답 (내 답)"
        items.append(f'<li class="{cls}">{CIRCLED[i]} {h(c)}<b>{h(mark)}</b></li>')
    return f'<ul class="bt-choices">{"".join(items)}</ul>'


# ----------------------------------------------------------------- 캐시 (4.4)


_cache_run = threading.local()   # 캐시 함수 본문이 실제로 돌았는지(=AI를 불렀는지) 표시 (v1.5)


@st.cache_data(show_spinner=False)
def cached_concepts(rid: str, material_json: str) -> tuple[str, dict]:
    _cache_run.ran = True
    usage = Usage()
    material = Material.model_validate_json(material_json)
    result = extract_concepts(material, usage)
    return result.model_dump_json(), dict(usage)


@st.cache_data(show_spinner=False)
def cached_utterances(rid: str, concepts_json: str, transcript: str) -> tuple[str, dict]:
    _cache_run.ran = True
    usage = Usage()
    concepts = ConceptsResult.model_validate_json(concepts_json)
    utts = find_utterances(concepts.concepts, transcript, usage)
    return "[" + ",".join(u.model_dump_json() for u in utts) + "]", dict(usage)


def add_usage(u: dict) -> None:
    st.session_state.usage.merge(u)


def call_cached(fn, *args) -> tuple[str, dict]:
    """캐시 함수를 부르고, 캐시에서 꺼냈으면(AI 호출 없음) 사용량을 더하지 않는다."""
    _cache_run.ran = False
    out, u = fn(*args)
    if _cache_run.ran:
        add_usage(u)
    return out, u


# ----------------------------------------------------------------- API 비용 보호 (v1.5)


@st.cache_resource
def daily_counter() -> DailyCounter:
    """서버 전체에서 하나. 하루 분석 횟수."""
    return DailyCounter(MAX_ANALYSES_PER_DAY)


@st.cache_resource
def sample_question_cache() -> ResultCache:
    """샘플 자료의 진단 문제. 모두 같은 파일이라 한 번 만든 문제를 다음 사람에게도 낸다(AI 호출 절약)."""
    return ResultCache()


def take_analysis() -> bool:
    """분석 1회를 쓴다. 세션 한도나 오늘 서버 한도가 다 찼으면 안내하고 False."""
    if session_left(st.session_state.analyses_used, MAX_ANALYSES_PER_SESSION) == 0:
        show_error(f"이 화면에서는 분석을 {MAX_ANALYSES_PER_SESSION}번까지 할 수 있어요. 지금 결과는 ②~④에서 계속 볼 수 "
                   "있어요. (E-16)")
        return False
    if not daily_counter().try_take():
        show_error("오늘 이 앱에서 쓸 수 있는 분석 횟수를 다 썼어요. 내일 다시 이용해 주세요. "
                   "직접 실행하려면 README의 로컬 실행 방법을 보세요. (E-17)")
        return False
    st.session_state.analyses_used += 1
    return True


def give_back_analysis() -> None:
    """분석이 실패하면 센 횟수를 돌려준다."""
    st.session_state.analyses_used = max(0, st.session_state.analyses_used - 1)
    daily_counter().give_back()


# ----------------------------------------------------------------- 분석 실행 (4.1 단계 1~7)


def run_analysis(material_bytes: bytes, material_name: str, audio_bytes: bytes | None, audio_name: str | None,
                 pasted: str | None, from_sample: bool) -> bool:
    st.session_state.errors = []
    with st.status("분석을 시작해요…", expanded=True) as status:
        try:
            status.update(label="텍스트 추출 중")
            material = extract_material(material_bytes, material_name)
            if material.n_pages == 0 or is_scanned(material):
                status.update(label="분석 실패", state="error")
                show_error("이 PDF는 글자가 그림으로 들어 있어 읽을 수 없어요. 글자가 선택되는 PDF를 올려 주세요. (E-03)")
                return False
            if material.n_pages >= MAX_PAGES:
                st.warning(f"앞 {MAX_PAGES}쪽만 분석해요. 한 장씩 올리면 더 정확해요. (E-13)")
            rid = run_id(material_bytes)

            transcript, source = None, None
            if pasted and pasted.strip():
                transcript, source = pasted.strip(), "paste"
            elif audio_bytes:
                status.update(label="녹음 받아쓰는 중 (몇 분 걸릴 수 있어요)")
                try:
                    transcript, source = stt.transcribe(audio_bytes, audio_name or "audio.m4a", st.session_state.usage), "audio"
                except STTError as e:
                    st.warning(error_message(e))
                    st.session_state.errors.append(str(e))
            if transcript:
                transcript = mask_pii(transcript)   # 대본도 강의자료처럼 AI에 보내기 전에 가린다 (v1.8)

            status.update(label="개념 찾는 중")
            concepts_json, _ = call_cached(cached_concepts, rid, material.model_dump_json())
            concepts = ConceptsResult.model_validate_json(concepts_json)

            utts: list[Utterance] = []
            if transcript:
                status.update(label="교수님 강조 찾는 중")
                utts_json, _ = call_cached(cached_utterances, rid, concepts_json, transcript)
                utts = [Utterance.model_validate(x) for x in json.loads(utts_json)]

            status.update(label="점수 계산 중")
            scores = compute_scores(concepts.concepts, utts, set(concepts.meta_pages))
        except ExtractError as e:
            status.update(label="분석 실패", state="error")
            show_error("PDF나 PPTX만 올릴 수 있어요. 한글(hwp)은 파일 → PDF로 저장해 주세요. (E-01)", str(e))
            return False
        except (LLMError, NoConceptsError) as e:
            status.update(label="분석 실패", state="error")
            show_error(error_message(e), str(e))
            return False
        except Exception as e:  # noqa: BLE001
            status.update(label="분석 실패", state="error")
            show_error(error_message(e), f"{type(e).__name__}: {e}")
            return False

        status.update(label="분석 완료", state="complete", expanded=False)

    st.session_state.update(material=material, transcript=transcript, transcript_source=source, concepts=concepts,
                            utterances=utts, scores=scores, run_id=rid, from_sample=from_sample, questions={},
                            answers={}, dont_know={}, mcq_choice={}, guessed={}, confusion={}, grading={},
                            priorities=None,
                            explanations={}, diag_ids=[], q_mode_used=None, notes={}, notes_failed=[],
                            material_bytes=material_bytes if material.kind == "pdf" else None)
    if transcript and not utts:
        st.info("녹음에서 강조한 말을 찾지 못했어요. 자료만으로 점수를 계산했어요. (E-10)")
    return True


# ----------------------------------------------------------------- 화면 S01


def screen_s01() -> None:
    page_head(1, "📝 빈틈노트", "강의자료와 교수님 강의 녹음 속 강조점, 메타인지 진단으로 시험 전 공부 우선순위를 정해주는 AI 서비스")

    if not has_key():
        st.warning("AI 키가 설정되지 않았어요. README의 설정 방법을 보세요. 키가 있어야 분석 버튼이 열려요. (E-06)")
    if fake_mode():
        st.warning("지금은 **가짜 AI 모드**(BINTM_FAKE_AI=1)예요. 실제 AI를 부르지 않고 저장된 샘플 결과를 보여줘요. 개발·테스트용이에요.")

    with st.container(border=True):
        st.subheader("1. 강의자료", anchor=False)
        material_file = st.file_uploader(f"PDF 또는 PPTX · 최대 {MAX_MATERIAL_MB}MB", type=list(SUPPORTED_MATERIAL),
                                         accept_multiple_files=False, max_upload_size=MAX_MATERIAL_MB)

    with st.container(border=True):
        st.subheader("2. 강의 녹음 (권장)", anchor=False)
        st.caption("녹음이 있으면 교수님이 강조한 곳을 찾아 순위가 더 정확해져요. 녹음 파일과 대본 중 하나만 넣으면 돼요.")
        tab_audio, tab_paste = st.tabs(["🎙️ 녹음 파일", "📝 대본 붙여넣기"])
        with tab_audio:
            if stt.stt_available() or fake_mode():
                # 업로더별 상한: 서버 기본값(30MB)이 아니라 녹음 상한(25MB)이 기본 안내("25MB per file")에도 보이게 (v1.5)
                audio_file = st.file_uploader(f"m4a · mp3 · wav · 최대 {MAX_AUDIO_MB}MB", type=list(SUPPORTED_AUDIO),
                                              max_upload_size=MAX_AUDIO_MB)
            else:
                audio_file = None
                st.info("음성 인식 키가 없어 녹음 파일은 받을 수 없어요. 대본 붙여넣기를 써 주세요.")
            st.caption("교수님 허락을 받은 녹음만, 개인 학습 목적으로만 올려 주세요.")
        with tab_paste:
            pasted = st.text_area("받아쓴 대본 (없으면 비워 두세요)", height=160, key="pasted_transcript")

    b1, b2 = st.columns(2)
    with b1:
        start = st.button("분석 시작", type="primary", disabled=(material_file is None or not has_key()), width="stretch")
    with b2:
        sample = st.button("샘플 자료로 체험하기", disabled=not has_key(), width="stretch",
                           help="우리가 만든 가상 강의자료(자료구조 8장, 20쪽)와 녹음 대본으로 바로 돌려 봅니다.")
    st.caption(NOTICE + " 올린 자료와 녹음은 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송돼요. 이 앱은 파일을 디스크에 "
               "저장하지 않고, 같은 파일을 다시 분석할 때를 위해 분석 결과만 서버가 켜져 있는 동안 메모리에 보관해요.")
    left = session_left(st.session_state.analyses_used, MAX_ANALYSES_PER_SESSION)
    if 0 <= left <= 2:
        st.caption(f"이 화면에서 분석은 {left}번 더 할 수 있어요 (모두가 함께 쓰는 AI 사용량을 아끼기 위한 제한).")

    if start and material_file is not None:
        if material_file.size > MAX_MATERIAL_MB * 1_000_000:
            show_error(f"파일이 너무 커요(최대 {MAX_MATERIAL_MB}MB). 한 장만 따로 저장해 올려 주세요. (E-02)")
            return
        if file_ext(material_file.name) not in SUPPORTED_MATERIAL:
            show_error("PDF나 PPTX만 올릴 수 있어요. 한글(hwp)은 파일 → PDF로 저장해 주세요. (E-01)")
            return
        audio_bytes, audio_name = None, None
        if audio_file is not None:
            if audio_file.size > MAX_AUDIO_MB * 1_000_000 or file_ext(audio_file.name) not in SUPPORTED_AUDIO:
                show_error(f"녹음은 m4a/mp3/wav {MAX_AUDIO_MB}MB까지예요. 길면 앞부분만 잘라 올리거나 대본 붙여넣기를 써 주세요. (E-04)")
                return
            audio_bytes, audio_name = audio_file.getvalue(), audio_file.name
        if not take_analysis():
            return
        if run_analysis(material_file.getvalue(), material_file.name, audio_bytes, audio_name, pasted, False):
            go(2)
        give_back_analysis()
    elif sample:
        if not take_analysis():
            return
        if run_analysis(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name, None, None,
                        SAMPLE_SCRIPT.read_text(encoding="utf-8"), True):
            go(2)
        give_back_analysis()


# ----------------------------------------------------------------- 화면 S02


def screen_s02() -> None:
    page_head(2, "② 출제 포인트 레이더", "강의자료와 교수님 말에서 시험에 나올 만한 곳을 찾아 순위를 매겼어요.")
    scores = st.session_state.scores
    concepts: list[Concept] = st.session_state.concepts.concepts
    by_id = {c.id: c for c in concepts}
    utts: list[Utterance] = st.session_state.utterances or []
    all_targets = diag_targets(scores)
    targets = all_targets

    show(tiles([("찾은 개념", len(concepts), "blue"), ("교수님 강조", len(utts), "amber"),
                ("진단할 개념", len(targets), "red")]))
    if st.session_state.from_sample:
        st.caption("샘플 자료로 분석한 결과예요.")
    if not st.session_state.transcript:
        st.info("녹음 없이 자료만으로 계산했어요. 녹음을 넣으면 순위가 더 정확해져요.")

    rows = []
    low = [s for s in scores.scores if s.concept_id not in targets]
    for i, s in enumerate(scores.scores, start=1):
        if low and s is low[0]:
            rows.append(f'<div class="bt-split">아래 {len(low)}개는 출제 가능성 점수가 {DIAG_MIN_PCT}점 미만이라 진단하지 않고 '
                        "'복습만'으로 둬요.</div>")
        rows.append(concept_row(i, s, dim=s.concept_id not in targets))
    show('<div class="bt-list">' + "".join(rows) + "</div>")
    st.caption(f"출제 가능성 점수는 자료와 녹음의 신호를 정해진 규칙(가중치 {WEIGHTS_VERSION})으로 더해, "
               "가장 높은 개념을 100점으로 맞춘 비교용 점수예요. 확률이 아니며 실제 출제를 보장하지 않습니다.")

    with st.expander("점수 내역과 교수님이 한 말 자세히 보기"):
        for i, s in enumerate(scores.scores, start=1):
            c = by_id[s.concept_id]
            st.markdown(f"**{i}. {c.name}** · {s.pct}점")
            lines = []
            if c.summary:
                lines.append(f"<p>{h(c.summary)}</p>")
            lines.append('<div class="bt-pages">등장 페이지: ' + h(", ".join(f"p.{p}" for p in c.pages) or "-") + "</div>")
            pts = " · ".join(f"{h(r.label.split(':')[0])} {'+' if r.points >= 0 else ''}{r.points:g}" for r in s.reasons)
            lines.append(f'<div class="bt-pages">점수 내역: {pts or "-"}</div>')
            for u in (u for u in utts if u.concept_id == c.id):
                lines.append(f'<div class="bt-pages">🎙️ {h(UTTERANCE_LABELS.get(u.type, u.type))}: “{h(u.quote)}”</div>')
            if c.objective_quote:
                lines.append(f'<div class="bt-pages">🎯 학습목표: {h(c.objective_quote)}</div>')
            show("".join(lines))

    st.divider()
    graded = bool(st.session_state.grading)
    if not targets:
        st.info("진단할 개념이 없어요. 자료에서 시험 신호를 찾지 못했어요.")
        return
    mode = st.radio("문제 형식", QUESTION_MODES, horizontal=True, disabled=graded,
                    index=QUESTION_MODES.index(st.session_state.q_mode), key="q_mode_radio",
                    captions=[f"출제 가능성 점수 {ESSAY_MIN_PCT}점 이상은 서술형, 나머지는 객관식", "빠르게 풀기", "깊게 확인하기"])
    st.session_state.q_mode = mode
    if len(all_targets) > QUICK_DIAG_TOP:   # 기본은 꺼짐: 20점 이상 전부 진단 (v1.5)
        quick = st.toggle(f"빠른 진단: 출제 가능성 상위 {QUICK_DIAG_TOP}개만 풀기", disabled=graded,
                          value=st.session_state.quick_diag, key="quick_diag_toggle",
                          help=f"시간이 없을 때 {len(all_targets)}문제 대신 {QUICK_DIAG_TOP}문제만 풀어요. 나머지 "
                               f"{len(all_targets) - QUICK_DIAG_TOP}개는 '진단 안 함'(이해도 0.5)으로 공부 순서를 계산해요.")
        st.session_state.quick_diag = quick
        if quick:
            targets = diag_targets(scores, top=QUICK_DIAG_TOP)
    label = "진단 결과 보기 →" if graded else f"{len(targets)}개 개념 진단하기 →"
    if st.button(label, type="primary", width="stretch"):
        if not graded and st.session_state.q_mode_used != mode:
            st.session_state.update(questions={}, answers={}, dont_know={}, mcq_choice={}, guessed={}, confusion={})
        st.session_state.q_mode_used = mode
        if not graded:
            st.session_state.diag_ids = targets
        go(3)


# ----------------------------------------------------------------- 화면 S03


def _make_questions(ids: list[str]) -> None:
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    pct = {s.concept_id: s.pct for s in st.session_state.scores.scores}
    mode = st.session_state.q_mode_used or st.session_state.q_mode
    todo = [cid for cid in ids if cid not in st.session_state.questions]
    cache = sample_question_cache() if st.session_state.from_sample else None

    def key(cid: str) -> tuple:
        return (st.session_state.run_id, cid, question_kind(pct[cid], mode), tuple(by_id[x].name for x in ids if x != cid))

    if cache is not None:   # 샘플 자료는 다른 사람이 이미 만든 같은 문제를 다시 쓴다 (v1.5)
        for cid in list(todo):
            hit = cache.get(key(cid))
            if hit is not None:
                st.session_state.questions[cid] = hit.model_copy(deep=True)
                todo.remove(cid)
    if not todo:
        return
    usage = Usage()

    def one(cid: str) -> tuple[str, Question | Exception]:
        others = [by_id[x].name for x in ids if x != cid]   # 다른 개념의 핵심을 다시 묻지 않게
        last: Exception | None = None
        for _ in range(2):   # 한 개념이 실패해도 나머지 문제는 살린다. 실패한 개념은 한 번 더 만든다
            try:
                return cid, make_question(by_id[cid], material, meta, usage, kind=question_kind(pct[cid], mode),
                                          others=others)
            except LLMKeyError:
                raise
            except Exception as e:   # AI 오류나 형식이 안 맞는 답
                last = e
        return cid, last

    with st.spinner(f"진단 문제 {len(todo)}개 만드는 중…"):
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(one, todo))
    add_usage(usage)
    failed = [(cid, out) for cid, out in results if isinstance(out, Exception)]
    if failed and len(failed) == len(results):
        err = failed[0][1]
        raise err if isinstance(err, LLMError) else LLMError(f"{type(err).__name__}: {err}")
    for cid, out in results:
        if not isinstance(out, Exception):
            st.session_state.questions[cid] = out
            if cache is not None:
                cache.put(key(cid), out.model_copy(deep=True))
    if failed:   # 문제를 못 만든 개념은 이번 진단에서 뺀다 (공부 순서에서는 '진단 안 함')
        st.session_state.q_failed = [by_id[cid].name for cid, _ in failed]
        st.session_state.diag_ids = [cid for cid in st.session_state.diag_ids if cid in st.session_state.questions]


def _is_answered(cid: str, q: Question) -> bool:
    """화면 입력칸의 지금 값으로 판단한다 (객관식: 보기나 '모르겠어요', 서술형: 답이나 '모르겠어요')."""
    ss = st.session_state   # 입력칸이 아직 안 그려졌으면(예시 답 채우기 직후) 저장된 값을 본다
    return is_answered(q, ss.get(f"mcq_{cid}", ss.mcq_choice.get(cid)),
                       str(ss.get(f"ans_{cid}", ss.answers.get(cid)) or ""),
                       bool(ss.get(f"dk_{cid}", ss.dont_know.get(cid))))


def _essay_input(cid: str) -> None:
    st.session_state.answers[cid] = st.text_area(
        "내 답", key=f"ans_{cid}", height=120, **_initial(f"ans_{cid}", value=st.session_state.answers.get(cid, "")),
        placeholder="아는 만큼 2~5문장으로 적어 주세요.", label_visibility="collapsed")
    st.session_state.dont_know[cid] = st.checkbox("모르겠어요", key=f"dk_{cid}",
                                                  **_initial(f"dk_{cid}", value=st.session_state.dont_know.get(cid, False)))


def _mcq_input(cid: str, q: Question) -> None:
    options = list(range(len(q.choices))) + [-1]
    prev = st.session_state.mcq_choice.get(cid)
    choice = st.radio("답 고르기", options, key=f"mcq_{cid}", label_visibility="collapsed",
                      **_initial(f"mcq_{cid}", index=options.index(prev) if prev in options else None),
                      format_func=lambda i: "모르겠어요" if i == -1 else f"{CIRCLED[i]} {q.choices[i]}")
    st.session_state.mcq_choice[cid] = choice
    if choice is not None and choice >= 0:
        guessed = st.checkbox("확신 없이 골랐어요 (찍었어요)", key=f"guess_{cid}",
                              **_initial(f"guess_{cid}", value=st.session_state.guessed.get(cid, False)))
        st.session_state.guessed[cid] = guessed
        if guessed:   # 설문의 '기타'처럼, 체크하면 아래에 입력칸이 생긴다 (v1.4). 비워 둬도 채점한다
            st.session_state.confusion[cid] = st.text_area(
                "어떤 점이 헷갈렸나요? (선택)", key=f"conf_{cid}", height=80, max_chars=CONFUSION_MAX_CHARS,
                **_initial(f"conf_{cid}", value=st.session_state.confusion.get(cid, "")),
                placeholder="예: ②와 ③ 중에 고민했어요. 두 방법이 어떻게 다른지 모르겠어요.",
                help="적어 주면 ④ 결과의 보완 설명에서 이 부분을 콕 집어 답해요. 비워 둬도 채점돼요.")
    else:
        st.session_state.guessed[cid] = False


def _confusion(cid: str) -> str:
    """객관식에서 보기를 고르고 '확신 없이 골랐어요'를 체크했을 때만 '헷갈린 점' 글을 쓴다 (v1.4)."""
    c = st.session_state.mcq_choice.get(cid)
    if c is None or c < 0 or not st.session_state.guessed.get(cid):
        return ""
    return " ".join(str(st.session_state.confusion.get(cid) or "").split())


def _result_view(cid: str, q: Question, g: Grading) -> None:
    head = status_badge(g.status) + badge(f"{g.score}/10", "none") + (badge(g.error_type, "none") if g.error_type else "")
    if q.is_mcq:
        chosen = st.session_state.mcq_choice.get(cid)
        body = choices_html(q, chosen if chosen is not None and chosen >= 0 else None)
        body += confusion_html(_confusion(cid))
        if q.explanation:
            body += f'<span class="bt-lbl">해설</span><div>{page_chips(h(q.explanation))}</div>'
        if q.source_pages:
            body += f'<div class="bt-pages">근거: {h(", ".join(f"p.{p}" for p in q.source_pages))}</div>'
        show(f"<div>{head}</div><div>{page_chips(h(g.reason))}</div>{body}")
        return
    mine = st.session_state.answers.get(cid, "") if not st.session_state.dont_know.get(cid) else ""
    show(f"<div>{head}</div><div>{page_chips(h(g.reason))}</div>"
         f'<span class="bt-lbl">내 답</span><div>{h(mine) or "(비워 둠)"}</div>')
    with st.expander("모범 답안과 채점 기준"):
        rubric = "".join(f"<li>{h(it.point)} ({'?' if sc is None else sc}/{it.score})</li>"
                         for it, sc in zip(q.rubric, g.rubric_scores or [None] * len(q.rubric)))
        show(f"<div>{h(q.answer)}</div><ul>{rubric}</ul>"
             f'<div class="bt-pages">근거: {h(", ".join(f"p.{p}" for p in q.source_pages))}</div>')


def _fill_examples(cids: list[str]) -> None:
    """샘플 체험용 예시 답을 입력칸에 넣는다 (v1.6). 입력칸이 그려지기 전에 불러야 한다."""
    ss, qs = st.session_state, st.session_state.questions
    for cid, ex in zip(cids, example_answers([qs[cid] for cid in cids])):
        if qs[cid].is_mcq:
            ss[f"mcq_{cid}"] = ss.mcq_choice[cid] = ex["choice"]
            ss[f"guess_{cid}"] = ss.guessed[cid] = ex["guessed"]
            ss[f"conf_{cid}"] = ss.confusion[cid] = ex["confusion"]
        else:
            ss[f"ans_{cid}"] = ss.answers[cid] = ex["answer"]
            ss[f"dk_{cid}"] = ss.dont_know[cid] = ex["dont_know"]
    ss.show_missing = False


def _initial(key: str, **default) -> dict:
    """입력칸 상태가 이미 있으면 기본값을 넘기지 않는다 (두 번 정하면 Streamlit이 경고를 남긴다)."""
    return {} if key in st.session_state else default


def screen_s03() -> None:
    page_head(3, "③ 내 취약점 진단", "정말 아는지 문제로 확인해요. 모르면 '모르겠어요'를 고르면 돼요. 솔직할수록 공부 순서가 정확해져요.")
    scores = st.session_state.scores
    pct = {s.concept_id: s.pct for s in scores.scores}
    ids = st.session_state.diag_ids or diag_targets(scores)
    st.session_state.diag_ids = ids
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    try:
        _make_questions(ids)
    except LLMError as e:
        show_error(error_message(e), str(e))
        if st.button("다시 시도"):
            st.rerun()
        return

    questions: dict[str, Question] = st.session_state.questions
    grading: dict[str, Grading] = st.session_state.grading
    shown = [cid for cid in ids if cid in questions]
    pending = [cid for cid in shown if cid not in grading]    # 아직 채점 안 됨 (처음, 또는 채점에 실패한 문제)
    failed = [cid for cid in st.session_state.grade_failed if cid in pending]
    if st.session_state.q_failed:
        st.warning(f"{', '.join(st.session_state.q_failed)}: 문제를 만들지 못해 이번 진단에서 뺐어요. "
                   "공부 순서에서는 '진단 안 함'으로 계산해요.")
    if not pending:
        n = {s: sum(1 for g in grading.values() if g.status == s) for s in (STATUS_KNOWN, STATUS_UNSURE, STATUS_UNKNOWN)}
        show(tiles([("앎", n[STATUS_KNOWN], "green"), ("헷갈림", n[STATUS_UNSURE], "amber"),
                    ("모름", n[STATUS_UNKNOWN], "red")]))
    elif failed:
        st.error(f"서술형 {len(failed)}문제를 채점하지 못했어요. 아래 빨간 표시가 있는 문제를 확인하고 "
                 "'채점 못한 문제 다시 채점'을 눌러 주세요. (E-08)")
        if st.session_state.grade_error:
            with st.expander("자세한 오류"):
                st.code(st.session_state.grade_error)
    else:
        n_mcq = sum(1 for cid in shown if questions[cid].is_mcq)
        done = sum(1 for cid in shown if _is_answered(cid, questions[cid]))
        st.progress(done / max(1, len(shown)), text=f"답한 문제 {done} / {len(shown)} · 객관식 {n_mcq} · 서술형 {len(shown) - n_mcq}")
        if st.session_state.from_sample and done < len(shown):
            if st.button("예시 답 채우기 (샘플 체험용)", width="stretch",
                         help="정답·반쯤 맞은 답·찍은 답·'모르겠어요'를 섞어 모든 문제를 채워요. 채점은 그대로 "
                              "객관식은 코드, 서술형은 AI가 해요. 채운 뒤 답을 고쳐도 돼요."):
                _fill_examples(shown)
                st.rerun()
            st.caption("샘플로 둘러보는 중이라면 '예시 답 채우기'로 바로 채점까지 가 볼 수 있어요.")

    number = {cid: i for i, cid in enumerate(shown, start=1)}
    for cid in shown:
        q = questions[cid]
        with st.container(border=True):
            show(f'<div class="bt-qhead"><span class="bt-qno">Q{number[cid]}</span><span class="bt-name">{h(by_id[cid].name)}</span></div>'
                 f'<div>{badge(q.kind, "kind")}{badge(f"출제 점수 {pct.get(cid, 0)}", "none")}</div>'
                 f'<div class="bt-q">{h(q.question)}</div>{figure_html(q.figure)}')
            g = grading.get(cid)
            if g is not None:
                _result_view(cid, q, g)
                continue
            if cid in failed:
                show('<div class="bt-miss">⚠️ 이 문제는 아직 채점하지 못했어요. 답을 그대로 두고 아래에서 다시 채점해 주세요.</div>')
            if q.is_mcq:
                _mcq_input(cid, q)
            else:
                _essay_input(cid)
            if st.session_state.show_missing and not _is_answered(cid, q):
                show('<div class="bt-miss">아직 답하지 않았어요. 모르면 \'모르겠어요\'를 골라 주세요.</div>')

    if pending:
        missing = [cid for cid in pending if not _is_answered(cid, questions[cid])]
        st.caption("모든 문제에 답해야 채점해요. 모르면 '모르겠어요'를 고르면 돼요. "
                   "객관식은 바로, 서술형은 AI가 자료를 근거로 채점해요.")
        label = "채점 못한 문제 다시 채점" if failed else "채점하기"
        if st.button(label, type="primary", width="stretch"):
            if missing:
                st.session_state.show_missing = True
                st.rerun()
            st.session_state.show_missing = False
            _grade_all(pending)
        if st.session_state.show_missing and missing:
            st.warning("아직 답하지 않은 문제: " + ", ".join(f"Q{number[cid]}" for cid in missing)
                       + ". 모르면 '모르겠어요'를 골라 주세요.")
        if failed and len(failed) < len(shown):
            if st.button("채점 못한 문제는 빼고 공부 순서 보기", width="stretch"):
                go(4)
    else:
        if st.button("공부 순서 보기 →", type="primary", width="stretch"):
            go(4)


def _answer_texts() -> dict[str, str]:
    """개념별 내 답을 글로 (보완 설명 호출과 내보내기에 씀)."""
    out = {}
    for cid, q in st.session_state.questions.items():
        if q.is_mcq:
            c = st.session_state.mcq_choice.get(cid)
            out[cid] = mcq_answer_text(q, None if c in (None, -1) else c, st.session_state.guessed.get(cid, False))
        else:
            out[cid] = "" if st.session_state.dont_know.get(cid) else st.session_state.answers.get(cid, "")
    return out


def _grade_all(ids: list[str]) -> None:
    """세션 상태는 메인 스레드에서만 읽고 쓴다. 스레드에는 순수 인자만 넘긴다. 객관식은 코드가 바로 채점."""
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    questions = dict(st.session_state.questions)
    answers = dict(st.session_state.answers)
    dont_know = dict(st.session_state.dont_know)
    usage = Usage()

    jobs: list[tuple[str, str]] = []
    for cid in ids:
        q = questions[cid]
        if q.is_mcq:
            c = st.session_state.mcq_choice.get(cid)
            st.session_state.grading[cid] = grade_mcq(q, c, st.session_state.guessed.get(cid, False))
        elif dont_know.get(cid):
            st.session_state.grading[cid] = empty_grading(REASON_DONT_KNOW)
        elif not answers.get(cid, "").strip():
            st.session_state.grading[cid] = empty_grading(REASON_BLANK)
        else:
            jobs.append((cid, answers[cid]))

    def one(job: tuple[str, str]) -> tuple[str, Grading | Exception]:
        # 한 문제가 실패해도 나머지 채점은 살린다. 실패한 문제는 화면에 표시하고 다시 채점하게 한다 (v1.3)
        cid, ans = job
        try:
            return cid, grade_answer(by_id[cid], questions[cid], ans, material, meta, usage)
        except Exception as e:
            return cid, e

    with st.spinner(f"서술형 채점 중… ({len(jobs)}개)"):
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(one, jobs))
    add_usage(usage)
    failed = [(cid, out) for cid, out in results if isinstance(out, Exception)]
    for cid, out in results:
        if not isinstance(out, Exception):
            st.session_state.grading[cid] = out
    st.session_state.grade_failed = [cid for cid, _ in failed]
    st.session_state.grade_error = (f"{type(failed[0][1]).__name__}: {failed[0][1]}"[:800] if failed else None)
    st.session_state.priorities = compute_priorities(st.session_state.scores, st.session_state.grading)
    st.session_state.update(explanations={}, notes={}, notes_failed=[], explain_failed=[])
    st.rerun()


# ----------------------------------------------------------------- 화면 S04


def _build_s04(explain_ids: list[str], note_ids: list[str]) -> list[str]:
    """보완 설명(호출 4)과 요약 노트(호출 5)를 한꺼번에 만든다. 세션 상태는 메인 스레드에서만 읽고 쓴다.

    한 개념이 실패해도 나머지는 보여 준다. 실패한 개념은 explain_failed / notes_failed에 적고(자동으로 다시 부르지 않음),
    실패한 개념 id 목록을 돌려준다. 키 오류(LLMKeyError)만 그대로 올린다.
    """
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    prow = {p.concept_id: p for p in st.session_state.priorities}
    status = {cid: p.status for cid, p in prow.items()}
    questions = dict(st.session_state.questions)
    answers = _answer_texts()
    confusions = {cid: _confusion(cid) for cid in explain_ids}
    grading = dict(st.session_state.grading)
    utts = list(st.session_state.utterances or [])
    usage = Usage()

    def one(job: tuple[str, str]):
        kind, cid = job
        try:
            if kind == "ex":
                return job, explain(by_id[cid], material, meta, status.get(cid, STATUS_NOT_DIAGNOSED),
                                    questions.get(cid), answers.get(cid) if cid in grading else None,
                                    grading.get(cid), usage, confusion=confusions.get(cid, ""))
            return job, make_note_section(by_id[cid], material, meta, prow[cid], utts, grading.get(cid), usage)
        except LLMKeyError:
            raise
        except Exception as e:   # AI 오류나 형식이 안 맞는 답
            return job, e

    jobs = [("ex", cid) for cid in explain_ids] + [("note", cid) for cid in note_ids]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, jobs))
    failed_ex, failed_note = [], []
    for (kind, cid), out in results:
        if isinstance(out, Exception):
            (failed_ex if kind == "ex" else failed_note).append(cid)
        elif kind == "ex":
            st.session_state.explanations[cid] = out
        else:
            st.session_state.notes[cid] = out
    st.session_state.explain_failed = sorted(set(st.session_state.explain_failed) | set(failed_ex))
    st.session_state.notes_failed = sorted(set(st.session_state.notes_failed) | set(failed_note))
    add_usage(usage)
    return failed_ex + failed_note


def _explain_many(ids: list[str]) -> list[str]:
    st.session_state.explain_failed = [c for c in st.session_state.explain_failed if c not in ids]
    return _build_s04(ids, [])


@st.cache_data(show_spinner=False, max_entries=400)
def cached_page_image(rid: str, n: int, width: int, _data: bytes) -> bytes | None:
    """강의자료 n쪽 그림. _data(파일 바이트)는 캐시 키에 넣지 않는다(rid가 파일 해시)."""
    return render_page(_data, n, width, quality=80 if width >= PAGE_IMG_WIDTH else 70)


def _page_expander(pages: list[int]) -> None:
    """원본 페이지 그림(그림·표 포함)을 접어서 보여 준다. PDF일 때만."""
    data = st.session_state.material_bytes
    pages = list(dict.fromkeys(pages))[:2]
    if not data or not pages:
        return
    with st.expander("🖼️ 강의자료 원본 보기 · " + ", ".join(f"p.{n}" for n in pages)):
        for n in pages:
            img = cached_page_image(st.session_state.run_id, n, PAGE_IMG_WIDTH, data)
            if img:
                st.image(img, caption=f"p.{n}", width="stretch")


def _concept_block(rank: int, p: PriorityRow) -> None:
    e: Explanation | None = st.session_state.explanations.get(p.concept_id)
    with st.container(border=True):
        show(f'<div class="bt-qhead"><span class="bt-qno">{rank}</span><span class="bt-name">{h(p.name)}</span></div>'
             f"<div>{status_badge(p.status)}{badge(f'출제 점수 {p.exam_pct}', 'none')}{badge(f'우선순위 {p.priority}', 'kind')}</div>")
        _review_expander(p.concept_id)
        if e is None:
            if p.concept_id in st.session_state.explain_failed:
                show('<div class="bt-miss">⚠️ 이 개념의 설명을 만들지 못했어요. 아래 버튼으로 다시 만들어 주세요. (E-07)</div>')
            if st.button("설명 보기" if p.concept_id not in st.session_state.explain_failed else "설명 다시 만들기",
                         key=f"ex_{p.concept_id}"):
                try:
                    with st.spinner("설명 만드는 중…"):
                        _explain_many([p.concept_id])
                    st.rerun()
                except LLMError as err:
                    show_error(error_message(err), str(err))
            return
        show(explanation_html(e, _confusion(p.concept_id)))
        _page_expander(e.check_pages)


def diagnosis_html(cid: str, q: Question, g: Grading) -> str:
    """S04 오답노트 카드 안에서 보여 줄 진단 결과 (문제, 그림, 내 답, 채점, 정답·해설)."""
    out = [f'<div class="bt-q">{h(q.question)}</div>{figure_html(q.figure)}',
           f"<div>{status_badge(g.status)}{badge(f'{g.score}/10', 'none')}"
           + (badge(g.error_type, "none") if g.error_type else "") + "</div>"]
    if q.is_mcq:
        chosen = st.session_state.mcq_choice.get(cid)
        out.append(choices_html(q, chosen if chosen is not None and chosen >= 0 else None))
        if chosen == -1:
            out.append('<div class="bt-pages">내 답: 모르겠어요</div>')
        e = st.session_state.explanations.get(cid)
        if not (e is not None and e.confusion_reply):   # 답이 있으면 보완 설명 칸에서 질문과 함께 보여 준다
            out.append(confusion_html(_confusion(cid)))
    else:
        mine = "" if st.session_state.dont_know.get(cid) else st.session_state.answers.get(cid, "")
        out.append(f'<span class="bt-lbl">내 답</span><div>{h(mine) or "모르겠어요"}</div>')
    out.append(f'<span class="bt-lbl">채점</span><div>{page_chips(h(g.reason))}</div>')
    if q.is_mcq and q.explanation:
        out.append(f'<span class="bt-lbl">해설</span><div>{page_chips(h(q.explanation))}</div>')
    elif not q.is_mcq and q.answer:
        out.append(f'<span class="bt-lbl">모범 답안</span><div>{page_chips(h(q.answer))}</div>')
    return "".join(out)


def _review_expander(cid: str) -> None:
    """진단한 개념이면 문제와 내 답을 오답노트 카드 안에서 다시 본다 (진단 결과와 보완 설명을 한곳에)."""
    q = st.session_state.questions.get(cid)
    g = st.session_state.grading.get(cid)
    if q is None or g is None:
        return
    with st.expander(f"📝 내 문제와 답 다시 보기 · {g.status} {g.score}/10"):
        show(diagnosis_html(cid, q, g))


def _note_block(c: Concept, p: PriorityRow, sec: NoteSection | None) -> None:
    detail = sec.detail if sec is not None else note_detail(p)
    with st.container(border=True):
        show(f'<div class="bt-qhead"><span class="bt-name">{h(c.name)}</span></div>'
             f"<div>{badge(detail, 'kind')}{badge(p.action, 'none')}{badge(f'출제 점수 {p.exam_pct}', 'none')}"
             f"{status_badge(p.status)}</div>")
        if sec is None:
            st.caption("이 개념의 요약을 만들지 못했어요. 아래 '요약 노트 다시 만들기'를 눌러 주세요.")
            return
        parts = [f'<div class="bt-ex">{paragraphs(sec.summary)}</div>']
        if sec.key_points:
            parts.append('<span class="bt-lbl">핵심</span><ul>' + "".join(f"<li>{page_chips(h(k))}</li>"
                                                                       for k in sec.key_points) + "</ul>")
        if sec.pitfalls:
            parts.append('<span class="bt-lbl">자주 하는 실수</span><ul>' + "".join(f"<li>{page_chips(h(k))}</li>"
                                                                              for k in sec.pitfalls) + "</ul>")
        for u in professor_quotes(c.id, st.session_state.utterances or []):
            parts.append(f'<div class="bt-quote">🎙️ 교수님 · {h(UTTERANCE_LABELS.get(u.type, u.type))}: “{h(u.quote)}”</div>')
        if sec.source_pages:
            parts.append(f'<div class="bt-pages">📖 근거 페이지: {h(", ".join(f"p.{n}" for n in sec.source_pages))}</div>')
        show('<div class="bt-note">' + "".join(parts) + "</div>")
        if detail != DETAIL_SHORT:
            _page_expander(sec.source_pages)


def _note_view(pri: list[PriorityRow]) -> None:
    concepts: list[Concept] = st.session_state.concepts.concepts
    meta = set(st.session_state.concepts.meta_pages)
    prow = {p.concept_id: p for p in pri}
    notes: dict[str, NoteSection] = st.session_state.notes
    n_full = sum(1 for p in pri if note_detail(p) == DETAIL_FULL)
    n_mid = sum(1 for p in pri if note_detail(p) == DETAIL_MID)
    st.caption(f"강의 순서대로 모든 개념을 정리했어요. 중요한 개념일수록 자세히 썼어요 "
               f"(자세히 {n_full} · 보통 {n_mid} · 짧게 {len(pri) - n_full - n_mid}). "
               "'자세히'는 지금 당장 볼 개념, 출제 가능성이 높은 개념, 진단에서 틀린 개념이에요.")
    for c in lecture_order(concepts, meta):
        if c.id in prow:
            _note_block(c, prow[c.id], notes.get(c.id))
    if st.session_state.notes_failed:
        if st.button("요약 노트 다시 만들기", key="notes_retry"):
            st.session_state.notes_failed = []
            st.rerun()


def _export_docs() -> tuple[str, str]:
    """내려받기 두 개: ① 공부 순서·오답노트 ② 시험 대비 요약 노트. 강의자료 페이지 그림은 넣지 않는다 (v1.3)."""
    s = st.session_state
    meta = set(s.concepts.meta_pages)
    order = [c.id for c in lecture_order(s.concepts.concepts, meta)]
    utts = s.utterances or []
    quotes = {cid: [(UTTERANCE_LABELS.get(u.type, u.type), u.quote) for u in professor_quotes(cid, utts)] for cid in order}
    study = study_html(s.material.name, s.scores, s.grading, s.priorities, s.explanations,
                       transcript_used=bool(s.transcript), questions=s.questions, answer_texts=_answer_texts(),
                       choices={cid: (c if c is not None and c >= 0 else None) for cid, c in s.mcq_choice.items()},
                       confusions={cid: _confusion(cid) for cid in s.questions})
    notes = notes_html(s.material.name, s.priorities, s.notes, note_order=order, quotes=quotes,
                       transcript_used=bool(s.transcript))
    return study, notes


def _downloads(key: str, docs: tuple[str, str]) -> None:
    study, notes = docs
    today = date.today().isoformat()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 공부 순서·오답노트 내려받기", data=study.encode("utf-8"), key=f"{key}_study",
                           type="primary", width="stretch", file_name=f"빈틈노트_공부순서_오답노트_{today}.html",
                           mime="text/html", help="공부 순서와, 문제·내 답·채점·정답·보완 설명을 한 카드에 모은 오답노트. "
                                                 "HTML 파일이라 인터넷 없이 브라우저로 열려요.")
    with c2:
        st.download_button("📒 요약 노트 내려받기", data=notes.encode("utf-8"), key=f"{key}_notes", width="stretch",
                           file_name=f"빈틈노트_요약노트_{today}.html", mime="text/html",
                           help="강의 순서대로 정리한 시험 대비 요약 노트만 따로 담은 HTML 파일이에요.")


def screen_s04() -> None:
    page_head(4, "④ 우선순위 보완 학습", "출제 가능성과 내가 모르는 정도를 곱해 공부 순서를 정했어요. 위에서부터 공부하세요.")
    if st.session_state.priorities is None:
        st.session_state.priorities = compute_priorities(st.session_state.scores, st.session_state.grading)
    pri: list[PriorityRow] = st.session_state.priorities
    rank = {p.concept_id: i for i, p in enumerate(pri, start=1)}
    count = {t: sum(1 for p in pri if p.action == t) for t, _ in TIERS}
    show(tiles([("지금 당장", count["지금 당장"], "red"), ("다음", count["다음"], "amber"),
                ("복습만", count["복습만"], "green")]))

    # 자동으로 만드는 것: 보완 설명('지금 당장' 전부 + 상위 N개 + 헷갈린 점을 적은 개념)과 요약 노트('자세히'·'보통'). '짧게'는 AI 호출 없음.
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    meta = set(st.session_state.concepts.meta_pages)
    for p in pri:
        if note_detail(p) == DETAIL_SHORT and p.concept_id not in st.session_state.notes and p.concept_id in by_id:
            st.session_state.notes[p.concept_id] = short_section(by_id[p.concept_id], meta)
    want = ({p.concept_id for p in pri[:AUTO_EXPLAIN_TOP]} | {p.concept_id for p in pri if p.action == "지금 당장"}
            | {p.concept_id for p in pri if _confusion(p.concept_id)})   # 헷갈린 점을 적은 개념은 바로 답한다 (v1.4)
    auto = [p.concept_id for p in pri if p.concept_id in want and p.concept_id not in st.session_state.explanations
            and p.concept_id not in st.session_state.explain_failed]
    note_ids = [p.concept_id for p in pri if p.concept_id not in st.session_state.notes and p.concept_id in by_id
                and p.concept_id not in st.session_state.notes_failed]
    if auto or note_ids:
        try:
            what = [f"보완 설명 {len(auto)}개" if auto else "", f"요약 노트 {len(note_ids)}개" if note_ids else ""]
            with st.spinner(" · ".join(w for w in what if w) + " 만드는 중…"):
                failed = _build_s04(auto, note_ids)
            if failed:
                st.warning(f"보완 설명·요약 노트 {len(failed)}개를 만들지 못했어요. 빨간 표시가 있는 카드의 '다시 만들기' "
                           "버튼을 눌러 주세요. (E-07)")
        except LLMError as e:
            show_error(error_message(e), str(e))

    docs = _export_docs()
    _downloads("dl_top", docs)

    tab_plan, tab_note = st.tabs(["🎯 공부 순서와 오답노트", "📒 시험 대비 요약 노트"], key="s04_tabs")
    with tab_plan:
        for tier, note in TIERS:
            rows = [p for p in pri if p.action == tier]
            if not rows:
                continue
            show(f'<div class="bt-tier">{h(tier)} · {len(rows)}개<small>{h(note)}</small></div>')
            if tier == "복습만":
                with st.expander(f"복습만 {len(rows)}개 펼치기"):
                    st.caption(f"'진단 안 함'은 문제를 내지 않은 개념이에요(출제 가능성 점수 {DIAG_MIN_PCT}점 미만이거나 "
                               "빠른 진단에서 뺀 개념). 이해도 0.5로 계산해요.")
                    for p in rows:
                        _concept_block(rank[p.concept_id], p)
            else:
                missing = [p.concept_id for p in rows if p.concept_id not in st.session_state.explanations]
                if tier == "다음" and len(missing) > 1:
                    if st.button(f"'다음' 개념 설명 {len(missing)}개 한 번에 보기", key="ex_all_next"):
                        try:
                            with st.spinner(f"보완 설명 {len(missing)}개 만드는 중…"):
                                _explain_many(missing)
                            st.rerun()
                        except LLMError as err:
                            show_error(error_message(err), str(err))
                for p in rows:
                    _concept_block(rank[p.concept_id], p)

        with st.expander("전체 표로 보기"):
            st.dataframe(
                [{"순위": rank[p.concept_id], "개념": p.name, "출제 점수": p.exam_pct, "이해 상태": p.status,
                  "우선순위 점수": p.priority, "권장": p.action} for p in pri],
                hide_index=True, width="stretch",
                column_config={
                    "출제 점수": st.column_config.ProgressColumn(format="%d점", min_value=0, max_value=100,
                                                           help="가장 높은 개념 = 100점인 비교용 점수 (확률 아님)"),
                    "우선순위 점수": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100),
                })
            st.caption("우선순위 점수 = 출제 점수 × (1 − 이해도). 이해도: 앎 1.0 · 헷갈림 0.5 · 모름 0.0 · 진단 안 함 0.5. "
                       "50 이상 지금 당장, 20~49 다음, 20 미만 복습만.")
    with tab_note:
        _note_view(pri)

    st.divider()
    _downloads("dl_bottom", docs)
    if st.button("다른 자료로 다시", width="stretch"):
        reset_state()
        go(1)


# ----------------------------------------------------------------- 화면 S05


def screen_s05() -> None:
    st.title("⑤ 안내·설정", anchor=False)
    st.markdown(
        f"""
**사용 방법**
1. 강의자료(PDF/PPTX)와 녹음(또는 대본)을 올리고 **분석 시작**
2. ② 출제 포인트 순위와 근거를 확인
3. ③ 출제 가능성 점수 {DIAG_MIN_PCT}점 이상인 개념을 전부 객관식·서술형 문제로 진단 (모든 문제에 답해야 채점, 모르면 '모르겠어요')
4. ④ 공부 순서와 오답노트(문제·내 답·채점·보완 설명), 강의 순서대로 정리한 **시험 대비 요약 노트**를 보고,
   **공부 순서·오답노트**와 **요약 노트**를 HTML 파일로 따로 저장

**주의**
- 출제를 보장하지 않습니다. 공부 우선순위를 정하는 참고용입니다.
- 녹음은 교수님 허락을 받은 것만, 개인 학습 목적으로만 올려 주세요.
- 올린 파일은 이 앱 서버의 디스크에 저장하지 않습니다. 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송됩니다.
- 같은 파일을 다시 분석할 때 AI를 또 부르지 않도록, 분석 결과(개념 목록·교수님 강조)와 강의자료 쪽 그림은 서버가 켜져 있는
  동안 서버 메모리에 보관합니다. 같은 파일을 올렸을 때만 다시 쓰고, 서버가 다시 켜지면 사라집니다.
- 학번·전화번호·이메일은 강의자료와 녹음 대본 모두 AI에 보내기 전에 가립니다.
"""
    )
    st.subheader("현재 설정", anchor=False)
    u = st.session_state.usage
    st.table({
        "항목": ["언어 모델", "음성 인식", "진단 기준", "문제 형식", "가중치 버전", "이번 세션 AI 호출", "입력 토큰", "출력 토큰"],
        "값": [LLM_MODEL, (STT_MODEL if stt.stt_available() else "꺼짐 (대본 붙여넣기만)"),
               f"출제 가능성 점수 {DIAG_MIN_PCT}점 이상 전부", st.session_state.q_mode, WEIGHTS_VERSION,
               str(u["calls"]), str(u["input_tokens"]), str(u["output_tokens"])],
    })
    if fake_mode():
        st.warning("가짜 AI 모드(BINTM_FAKE_AI=1)로 동작 중이에요. 결과는 저장된 샘플이에요.")
    st.caption("KOREATECH AI 실습형 이벤트 · Build for Students · 팀 빈틈노트")


# ----------------------------------------------------------------- 사이드바와 라우팅


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### 📝 빈틈노트")
        has_scores = st.session_state.scores is not None
        has_grading = bool(st.session_state.grading)
        enabled = [True, has_scores, has_scores, has_grading, True]
        cur = st.session_state.step
        for i, (label, ok) in enumerate(zip(STEPS, enabled), start=1):
            if st.button(label, key=f"nav_{i}", disabled=not ok, width="stretch",
                         type="primary" if i == cur else "secondary"):
                go(i)
        st.divider()
        if st.button("처음부터", width="stretch"):
            reset_state()
            go(1)
        st.caption(f"모델: {LLM_MODEL}" + (" · 가짜 AI 모드" if fake_mode() else ""))


def main() -> None:
    load_secrets_into_env()
    init_state()
    st.html(CSS)
    sidebar()
    step = st.session_state.step
    if step in (2, 3) and st.session_state.scores is None:
        st.session_state.step = step = 1
        st.info("새로고침하면 결과가 사라져요. 결과는 ④에서 HTML 파일로 내려받을 수 있어요. 자료를 다시 올려 주세요. (E-14)")
    if step == 4 and not st.session_state.grading:
        st.session_state.step = step = 1 if st.session_state.scores is None else 3
    {1: screen_s01, 2: screen_s02, 3: screen_s03, 4: screen_s04, 5: screen_s05}[step]()


main()
