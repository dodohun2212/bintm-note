# -*- coding: utf-8 -*-
"""빈틈노트 화면 (S01~S05). 계산은 전부 core/ 에 있고, 이 파일은 화면만 다룬다."""
from __future__ import annotations

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import streamlit as st

from config import (AUTO_EXPLAIN_TOP, DIAG_MIN_PCT, ESSAY_MIN_PCT, LLM_MODEL, MAX_AUDIO_MB, MAX_MATERIAL_MB,
                    MAX_PAGES, STT_MODEL)
from core import stt
from core.concepts import NoConceptsError, extract_concepts
from core.diagnose import (CIRCLED, MODE_MIX, QUESTION_MODES, REASON_BLANK, REASON_DONT_KNOW, diag_targets,
                           empty_grading, grade_answer, grade_mcq, make_question, mcq_answer_text, question_kind)
from core.explain import explain
from core.export import to_html
from core.extract import (SUPPORTED_AUDIO, SUPPORTED_MATERIAL, ExtractError, extract_material, file_ext, is_scanned,
                          run_id)
from core.llm import LLMError, LLMJsonError, LLMKeyError, Usage, fake_mode, has_key
from core.priority import compute_priorities
from core.schemas import (STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, STATUS_UNSURE, Concept, ConceptsResult,
                          Explanation, Grading, Material, PriorityRow, Question, ScoreRow, Utterance)
from core.score import UTTERANCE_LABELS, WEIGHTS_VERSION, compute_scores
from core.stt import STTError
from core.utterances import find_utterances

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
    questions={}, answers={}, dont_know={}, mcq_choice={}, guessed={}, grading={}, priorities=None, explanations={},
    run_id=None, errors=[], usage=None, from_sample=False, diag_ids=[], q_mode=MODE_MIX, q_mode_used=None,
)


def init_state() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, (dict, list)) else type(v)()
    if st.session_state.usage is None:
        st.session_state.usage = Usage()


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
            f'<div>{reason_chips(s.reasons)}</div></div><div class="bt-pct">{s.pct}%</div></div>')


def explanation_html(e: Explanation) -> str:
    out = []
    if e.my_gap:
        out.append(f'<div class="bt-gap"><b>내가 놓친 점</b>{h(e.my_gap)}</div>')
    out.append(f'<div class="bt-ex">{paragraphs(e.explanation)}</div>')
    if e.not_found:
        out.append(f'<div class="bt-warn">⚠️ 올린 자료에서 찾지 못함 · {h(e.not_found_note or "")} '
                   '교재 다른 장이나 수업 노트를 확인하세요. (E-12)</div>')
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


@st.cache_data(show_spinner=False)
def cached_concepts(rid: str, material_json: str) -> tuple[str, dict]:
    usage = Usage()
    material = Material.model_validate_json(material_json)
    result = extract_concepts(material, usage)
    return result.model_dump_json(), dict(usage)


@st.cache_data(show_spinner=False)
def cached_utterances(rid: str, concepts_json: str, transcript: str) -> tuple[str, dict]:
    usage = Usage()
    concepts = ConceptsResult.model_validate_json(concepts_json)
    utts = find_utterances(concepts.concepts, transcript, usage)
    return "[" + ",".join(u.model_dump_json() for u in utts) + "]", dict(usage)


def add_usage(u: dict) -> None:
    st.session_state.usage.add(u.get("input_tokens", 0), u.get("output_tokens", 0), u.get("seconds", 0.0))


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

            status.update(label="개념 찾는 중")
            concepts_json, u1 = cached_concepts(rid, material.model_dump_json())
            add_usage(u1)
            concepts = ConceptsResult.model_validate_json(concepts_json)

            utts: list[Utterance] = []
            if transcript:
                status.update(label="교수님 강조 찾는 중")
                utts_json, u2 = cached_utterances(rid, concepts_json, transcript)
                add_usage(u2)
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
                            answers={}, dont_know={}, mcq_choice={}, guessed={}, grading={}, priorities=None,
                            explanations={}, diag_ids=[], q_mode_used=None)
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
                                         accept_multiple_files=False)

    with st.container(border=True):
        st.subheader("2. 강의 녹음 (권장)", anchor=False)
        st.caption("녹음이 있으면 교수님이 강조한 곳을 찾아 순위가 더 정확해져요. 녹음 파일과 대본 중 하나만 넣으면 돼요.")
        tab_audio, tab_paste = st.tabs(["🎙️ 녹음 파일", "📝 대본 붙여넣기"])
        with tab_audio:
            if stt.stt_available() or fake_mode():
                audio_file = st.file_uploader(f"m4a · mp3 · wav · 최대 {MAX_AUDIO_MB}MB", type=list(SUPPORTED_AUDIO))
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
    st.caption(NOTICE + " 올린 자료와 녹음은 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송되고, 이 앱의 서버에는 저장하지 않아요.")

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
        if run_analysis(material_file.getvalue(), material_file.name, audio_bytes, audio_name, pasted, False):
            go(2)
    elif sample:
        if run_analysis(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name, None, None,
                        SAMPLE_SCRIPT.read_text(encoding="utf-8"), True):
            go(2)


# ----------------------------------------------------------------- 화면 S02


def screen_s02() -> None:
    page_head(2, "② 출제 포인트 레이더", "강의자료와 교수님 말에서 시험에 나올 만한 곳을 찾아 순위를 매겼어요.")
    scores = st.session_state.scores
    concepts: list[Concept] = st.session_state.concepts.concepts
    by_id = {c.id: c for c in concepts}
    utts: list[Utterance] = st.session_state.utterances or []
    targets = diag_targets(scores)

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
            rows.append(f'<div class="bt-split">아래 {len(low)}개는 출제 가능성이 {DIAG_MIN_PCT}% 미만이라 진단하지 않고 '
                        "'복습만'으로 둬요.</div>")
        rows.append(concept_row(i, s, dim=s.concept_id not in targets))
    show('<div class="bt-list">' + "".join(rows) + "</div>")
    st.caption(f"출제 가능성은 자료와 녹음의 신호를 정해진 규칙(가중치 {WEIGHTS_VERSION})으로 더한 값이에요. "
               "가장 높은 개념이 100%예요. 실제 출제를 보장하지 않습니다.")

    with st.expander("점수 내역과 교수님이 한 말 자세히 보기"):
        for i, s in enumerate(scores.scores, start=1):
            c = by_id[s.concept_id]
            st.markdown(f"**{i}. {c.name}** · {s.pct}%")
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
                    captions=[f"출제 가능성 {ESSAY_MIN_PCT}% 이상은 서술형, 나머지는 객관식", "빠르게 풀기", "깊게 확인하기"])
    st.session_state.q_mode = mode
    label = "진단 결과 보기 →" if graded else f"{len(targets)}개 개념 진단하기 →"
    if st.button(label, type="primary", width="stretch"):
        if not graded and st.session_state.q_mode_used != mode:
            st.session_state.update(questions={}, answers={}, dont_know={}, mcq_choice={}, guessed={})
        st.session_state.q_mode_used = mode
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
    if not todo:
        return
    usage = Usage()

    def one(cid: str) -> tuple[str, Question]:
        others = [by_id[x].name for x in ids if x != cid]   # 다른 개념의 핵심을 다시 묻지 않게
        return cid, make_question(by_id[cid], material, meta, usage, kind=question_kind(pct[cid], mode),
                                  others=others)

    with st.spinner(f"진단 문제 {len(todo)}개 만드는 중…"):
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(one, todo))
    for cid, q in results:
        st.session_state.questions[cid] = q
    add_usage(usage)


def _is_answered(cid: str, q: Question) -> bool:
    if q.is_mcq:
        return st.session_state.get(f"mcq_{cid}") is not None
    return bool(st.session_state.get(f"dk_{cid}")) or bool(str(st.session_state.get(f"ans_{cid}") or "").strip())


def _essay_input(cid: str) -> None:
    st.session_state.answers[cid] = st.text_area(
        "내 답", key=f"ans_{cid}", height=120, value=st.session_state.answers.get(cid, ""),
        placeholder="아는 만큼 2~5문장으로 적어 주세요.", label_visibility="collapsed")
    st.session_state.dont_know[cid] = st.checkbox("모르겠어요", key=f"dk_{cid}",
                                                  value=st.session_state.dont_know.get(cid, False))


def _mcq_input(cid: str, q: Question) -> None:
    options = list(range(len(q.choices))) + [-1]
    prev = st.session_state.mcq_choice.get(cid)
    choice = st.radio("답 고르기", options, key=f"mcq_{cid}", label_visibility="collapsed",
                      index=options.index(prev) if prev in options else None,
                      format_func=lambda i: "모르겠어요" if i == -1 else f"{CIRCLED[i]} {q.choices[i]}")
    st.session_state.mcq_choice[cid] = choice
    if choice is not None and choice >= 0:
        st.session_state.guessed[cid] = st.checkbox("확신 없이 골랐어요 (찍었어요)", key=f"guess_{cid}",
                                                    value=st.session_state.guessed.get(cid, False))
    else:
        st.session_state.guessed[cid] = False


def _result_view(cid: str, q: Question, g: Grading) -> None:
    head = status_badge(g.status) + badge(f"{g.score}/10", "none") + (badge(g.error_type, "none") if g.error_type else "")
    if q.is_mcq:
        chosen = st.session_state.mcq_choice.get(cid)
        body = choices_html(q, chosen if chosen is not None and chosen >= 0 else None)
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
    if grading:
        n = {s: sum(1 for g in grading.values() if g.status == s) for s in (STATUS_KNOWN, STATUS_UNSURE, STATUS_UNKNOWN)}
        show(tiles([("앎", n[STATUS_KNOWN], "green"), ("헷갈림", n[STATUS_UNSURE], "amber"),
                    ("모름", n[STATUS_UNKNOWN], "red")]))
    else:
        n_mcq = sum(1 for cid in shown if questions[cid].is_mcq)
        done = sum(1 for cid in shown if _is_answered(cid, questions[cid]))
        st.progress(done / max(1, len(shown)), text=f"답한 문제 {done} / {len(shown)} · 객관식 {n_mcq} · 서술형 {len(shown) - n_mcq}")

    for i, cid in enumerate(shown, start=1):
        q = questions[cid]
        with st.container(border=True):
            show(f'<div class="bt-qhead"><span class="bt-qno">Q{i}</span><span class="bt-name">{h(by_id[cid].name)}</span></div>'
                 f'<div>{badge(q.kind, "kind")}{badge(f"출제 {pct.get(cid, 0)}%", "none")}</div>'
                 f'<div class="bt-q">{h(q.question)}</div>')
            g = grading.get(cid)
            if g is not None:
                _result_view(cid, q, g)
            elif q.is_mcq:
                _mcq_input(cid, q)
            else:
                _essay_input(cid)

    if not grading:
        st.caption("객관식은 바로, 서술형은 AI가 자료를 근거로 채점해요.")
        if st.button("채점하기", type="primary", width="stretch"):
            _grade_all(shown)
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

    def one(job: tuple[str, str]) -> tuple[str, Grading]:
        cid, ans = job
        return cid, grade_answer(by_id[cid], questions[cid], ans, material, meta, usage)

    try:
        with st.spinner(f"서술형 채점 중… ({len(jobs)}개)"):
            with ThreadPoolExecutor(max_workers=6) as ex:
                results = list(ex.map(one, jobs))
    except LLMError as e:
        st.session_state.grading = {}
        show_error(error_message(e), str(e))
        return
    for cid, g in results:
        st.session_state.grading[cid] = g
    add_usage(usage)
    st.session_state.priorities = compute_priorities(st.session_state.scores, st.session_state.grading)
    st.rerun()


# ----------------------------------------------------------------- 화면 S04


def _explain_many(ids: list[str]) -> None:
    """보완 설명 생성. 세션 상태는 메인 스레드에서만 읽고 쓴다."""
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    status = {p.concept_id: p.status for p in st.session_state.priorities}
    questions = dict(st.session_state.questions)
    answers = _answer_texts()
    grading = dict(st.session_state.grading)
    usage = Usage()

    def one(cid: str) -> tuple[str, Explanation]:
        return cid, explain(by_id[cid], material, meta, status.get(cid, STATUS_NOT_DIAGNOSED), questions.get(cid),
                            answers.get(cid) if cid in grading else None, grading.get(cid), usage)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, ids))
    for cid, e in results:
        st.session_state.explanations[cid] = e
    add_usage(usage)


def _concept_block(rank: int, p: PriorityRow) -> None:
    e: Explanation | None = st.session_state.explanations.get(p.concept_id)
    with st.container(border=True):
        show(f'<div class="bt-qhead"><span class="bt-qno">{rank}</span><span class="bt-name">{h(p.name)}</span></div>'
             f"<div>{status_badge(p.status)}{badge(f'출제 {p.exam_pct}%', 'none')}{badge(f'우선순위 {p.priority}', 'kind')}</div>")
        if e is None:
            if st.button("설명 보기", key=f"ex_{p.concept_id}"):
                try:
                    with st.spinner("설명 만드는 중…"):
                        _explain_many([p.concept_id])
                    st.rerun()
                except LLMError as err:
                    show_error(error_message(err), str(err))
            return
        show(explanation_html(e))


def _download(key: str) -> None:
    s = st.session_state
    doc = to_html(s.material.name, s.scores, s.grading, s.priorities, s.explanations,
                  transcript_used=bool(s.transcript), questions=s.questions, answer_texts=_answer_texts(),
                  choices={cid: (c if c is not None and c >= 0 else None) for cid, c in s.mcq_choice.items()})
    st.download_button("📥 결과 내려받기 (HTML)", data=doc.encode("utf-8"), key=key, type="primary", width="stretch",
                       file_name=f"빈틈노트_결과_{date.today().isoformat()}.html", mime="text/html",
                       help="파일을 열면 브라우저에서 바로 보여요. 인터넷 없이도 열려요.")


def screen_s04() -> None:
    page_head(4, "④ 우선순위 보완 학습", "출제 가능성과 내가 모르는 정도를 곱해 공부 순서를 정했어요. 위에서부터 공부하세요.")
    if st.session_state.priorities is None:
        st.session_state.priorities = compute_priorities(st.session_state.scores, st.session_state.grading)
    pri: list[PriorityRow] = st.session_state.priorities
    rank = {p.concept_id: i for i, p in enumerate(pri, start=1)}
    count = {t: sum(1 for p in pri if p.action == t) for t, _ in TIERS}
    show(tiles([("지금 당장", count["지금 당장"], "red"), ("다음", count["다음"], "amber"),
                ("복습만", count["복습만"], "green")]))
    _download("dl_top")

    # 자동 설명: '지금 당장' 전부 + 상위 N개. 나머지는 버튼으로 (비용 절약)
    want = {p.concept_id for p in pri[:AUTO_EXPLAIN_TOP]} | {p.concept_id for p in pri if p.action == "지금 당장"}
    auto = [p.concept_id for p in pri if p.concept_id in want and p.concept_id not in st.session_state.explanations]
    if auto:
        try:
            with st.spinner(f"보완 설명 {len(auto)}개 만드는 중…"):
                _explain_many(auto)
        except LLMError as e:
            show_error(error_message(e), str(e))

    for tier, note in TIERS:
        rows = [p for p in pri if p.action == tier]
        if not rows:
            continue
        show(f'<div class="bt-tier">{h(tier)} · {len(rows)}개<small>{h(note)}</small></div>')
        if tier == "복습만":
            with st.expander(f"복습만 {len(rows)}개 펼치기"):
                st.caption(f"'진단 안 함'은 출제 가능성이 {DIAG_MIN_PCT}% 미만이라 문제를 내지 않은 개념이에요.")
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
            [{"순위": rank[p.concept_id], "개념": p.name, "출제 가능성": p.exam_pct, "이해 상태": p.status,
              "우선순위 점수": p.priority, "권장": p.action} for p in pri],
            hide_index=True, width="stretch",
            column_config={
                "출제 가능성": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                "우선순위 점수": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100),
            })
        st.caption("우선순위 점수 = 출제 가능성 × (1 − 이해도). 이해도: 앎 1.0 · 헷갈림 0.5 · 모름 0.0 · 진단 안 함 0.5. "
                   "50 이상 지금 당장, 20~49 다음, 20 미만 복습만.")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        _download("dl_bottom")
    with c2:
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
3. ③ 출제 가능성 {DIAG_MIN_PCT}% 이상인 개념을 전부 객관식·서술형 문제로 진단
4. ④ 공부 순서와 자료 근거 보완 설명을 보고, 결과를 HTML 파일로 저장

**주의**
- 출제를 보장하지 않습니다. 공부 우선순위를 정하는 참고용입니다.
- 녹음은 교수님 허락을 받은 것만, 개인 학습 목적으로만 올려 주세요.
- 올린 파일은 이 앱의 서버에 저장하지 않습니다. 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송됩니다.
- 학번·전화번호·이메일은 AI에 보내기 전에 가립니다.
"""
    )
    st.subheader("현재 설정", anchor=False)
    u = st.session_state.usage
    st.table({
        "항목": ["언어 모델", "음성 인식", "진단 기준", "문제 형식", "가중치 버전", "이번 세션 AI 호출", "입력 토큰", "출력 토큰"],
        "값": [LLM_MODEL, (STT_MODEL if stt.stt_available() else "꺼짐 (대본 붙여넣기만)"),
               f"출제 가능성 {DIAG_MIN_PCT}% 이상 전부", st.session_state.q_mode, WEIGHTS_VERSION,
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
