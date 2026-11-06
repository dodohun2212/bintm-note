# -*- coding: utf-8 -*-
"""빈틈노트 화면 (S01~S05). 계산은 전부 core/ 에 있고, 이 파일은 화면만 다룬다."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import streamlit as st

from config import (AUTO_EXPLAIN_TOP, LLM_MODEL, MAX_AUDIO_MB, MAX_MATERIAL_MB, MAX_PAGES, N_DIAG_DEFAULT,
                    STT_MODEL)
from core import stt
from core.concepts import NoConceptsError, extract_concepts
from core.diagnose import empty_grading, grade_answer, make_question
from core.explain import explain
from core.export import to_markdown
from core.extract import (SUPPORTED_AUDIO, SUPPORTED_MATERIAL, ExtractError, extract_material, file_ext, is_scanned,
                          run_id)
from core.llm import LLMError, LLMJsonError, LLMKeyError, Usage, fake_mode, has_key
from core.priority import compute_priorities
from core.schemas import (STATUS_KNOWN, STATUS_NOT_DIAGNOSED, STATUS_UNKNOWN, STATUS_UNSURE, Concept, ConceptsResult,
                          Explanation, Grading, Material, Question, Utterance)
from core.score import WEIGHTS_VERSION, compute_scores
from core.stt import STTError
from core.utterances import find_utterances

ROOT = Path(__file__).resolve().parent
SAMPLE_PDF = ROOT / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
SAMPLE_SCRIPT = ROOT / "samples" / "강의녹음_대본_8장_트리와힙.md"
NOTICE = "출제를 보장하지 않습니다. 공부 우선순위를 정하는 참고용입니다."
STEPS = ["① 자료 올리기", "② 출제 포인트 레이더", "③ 내 취약점 진단", "④ 우선순위 보완 학습", "⑤ 안내·설정"]
STATUS_COLOR = {STATUS_KNOWN: "green", STATUS_UNSURE: "orange", STATUS_UNKNOWN: "red", STATUS_NOT_DIAGNOSED: "gray"}

st.set_page_config(page_title="빈틈노트", page_icon="📝", layout="wide")


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
    questions={}, answers={}, dont_know={}, grading={}, priorities=None, explanations={}, run_id=None,
    errors=[], usage=None, from_sample=False, diag_ids=[],
)


def init_state() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, (dict, list)) else type(v)()
    if st.session_state.usage is None:
        st.session_state.usage = Usage()
    if "n_diag" not in st.session_state:
        st.session_state.n_diag = N_DIAG_DEFAULT


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
                import json as _json

                utts = [Utterance.model_validate(x) for x in _json.loads(utts_json)]

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
                            answers={}, dont_know={}, grading={}, priorities=None, explanations={}, diag_ids=[])
    if transcript and not utts:
        st.info("녹음에서 강조한 말을 찾지 못했어요. 자료만으로 점수를 계산했어요. (E-10)")
    return True


# ----------------------------------------------------------------- 화면 S01


def screen_s01() -> None:
    st.title("📝 빈틈노트")
    st.caption("강의자료와 교수님 강의 녹음 속 강조점, 메타인지 진단으로 시험 전 공부 우선순위를 정해주는 AI 서비스")
    st.info(NOTICE + " 올린 자료와 녹음은 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송되고, 이 앱의 서버에는 저장하지 않아요.")

    if not has_key():
        st.warning("AI 키가 설정되지 않았어요. README의 설정 방법을 보세요. 키가 있어야 분석 버튼이 열려요. (E-06)")
    if fake_mode():
        st.warning("지금은 **가짜 AI 모드**(BINTM_FAKE_AI=1)예요. 실제 AI를 부르지 않고 저장된 샘플 결과를 보여줘요. 개발·테스트용이에요.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 강의자료")
        material_file = st.file_uploader(f"PDF 또는 PPTX, 최대 {MAX_MATERIAL_MB}MB", type=list(SUPPORTED_MATERIAL),
                                         accept_multiple_files=False)
        if material_file is not None:
            st.caption(f"{material_file.name} · {material_file.size / 1_000_000:.1f}MB")
    with col2:
        st.subheader("2. 강의 녹음 (권장)")
        tab_audio, tab_paste = st.tabs(["녹음 파일", "대본 붙여넣기"])
        with tab_audio:
            if stt.stt_available() or fake_mode():
                audio_file = st.file_uploader(f"m4a / mp3 / wav, 최대 {MAX_AUDIO_MB}MB", type=list(SUPPORTED_AUDIO))
            else:
                audio_file = None
                st.caption("음성 인식 키가 없어 녹음 파일은 받을 수 없어요. 대본 붙여넣기를 써 주세요.")
            st.caption("교수님 허락을 받은 녹음만, 개인 학습 목적으로만 올려 주세요.")
        with tab_paste:
            pasted = st.text_area("받아쓴 대본을 붙여 넣으세요 (없으면 비워 두세요)", height=160, key="pasted_transcript")

    st.divider()
    b1, b2 = st.columns([1, 1])
    with b1:
        start = st.button("분석 시작", type="primary", disabled=(material_file is None or not has_key()), use_container_width=True)
    with b2:
        sample = st.button("샘플 자료로 체험하기", disabled=not has_key(), use_container_width=True,
                           help="우리가 만든 가상 강의자료(자료구조 8장, 20쪽)와 녹음 대본으로 바로 돌려 봅니다.")

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
            st.session_state.just_analyzed = True
            go(2)
    elif sample:
        if run_analysis(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name, None, None,
                        SAMPLE_SCRIPT.read_text(encoding="utf-8"), True):
            st.session_state.just_analyzed = True
            go(2)


# ----------------------------------------------------------------- 화면 S02


def screen_s02() -> None:
    st.title("② 출제 포인트 레이더")
    scores = st.session_state.scores
    concepts: list[Concept] = st.session_state.concepts.concepts
    by_id = {c.id: c for c in concepts}
    if st.session_state.pop("just_analyzed", False):
        n_u = len(st.session_state.utterances or [])
        st.success(f"개념 {len(concepts)}개, 강조 발화 {n_u}개를 찾았어요." + (" (샘플 자료)" if st.session_state.from_sample else ""))
    if not st.session_state.transcript:
        st.info("녹음 없이 자료만으로 계산했어요. 녹음을 넣으면 순위가 더 정확해져요.")
    rows = []
    for i, s in enumerate(scores.scores, start=1):
        rows.append({"순위": i, "개념": s.name, "출제 가능성(%)": s.pct, "근거": " · ".join(r.label for r in s.reasons)})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("점수는 자료와 녹음의 신호를 정해진 규칙(가중치 " + WEIGHTS_VERSION + ")으로 더한 값이고, 실제 출제를 보장하지 않습니다.")

    st.subheader("개념별 근거")
    for i, s in enumerate(scores.scores, start=1):
        c = by_id[s.concept_id]
        with st.expander(f"{i}. {s.name} · {s.pct}%"):
            if c.summary:
                st.write(c.summary)
            st.write("등장 페이지: " + (", ".join(f"p.{p}" for p in c.pages) or "-") +
                     (f" (본문 {len(s.body_pages)}쪽)" if s.body_pages else ""))
            for r in s.reasons:
                sign = "+" if r.points >= 0 else ""
                st.write(f"- {r.label} ({sign}{r.points:g})")
            if c.objective_quote:
                st.caption("학습목표: " + c.objective_quote)

    n = st.session_state.n_diag
    if st.button(f"상위 {n}개 진단하기 →", type="primary"):
        st.session_state.diag_ids = [s.concept_id for s in scores.scores[:n]]
        go(3)


# ----------------------------------------------------------------- 화면 S03


def _make_questions(ids: list[str]) -> None:
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    todo = [cid for cid in ids if cid not in st.session_state.questions]
    if not todo:
        return
    usage = Usage()
    with st.spinner(f"진단 문제 {len(todo)}개 만드는 중…"):
        with ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(lambda cid: (cid, make_question(by_id[cid], material, meta, usage)), todo))
    for cid, q in results:
        st.session_state.questions[cid] = q
    add_usage(usage)


def screen_s03() -> None:
    st.title("③ 내 취약점 진단")
    scores = st.session_state.scores
    n = st.session_state.n_diag
    ids = [s.concept_id for s in scores.scores[:n]]
    st.session_state.diag_ids = ids
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    try:
        _make_questions(ids)
    except LLMError as e:
        show_error(error_message(e), str(e))
        if st.button("다시 시도"):
            st.rerun()
        return

    grading: dict[str, Grading] = st.session_state.grading
    if grading:
        known = sum(1 for g in grading.values() if g.status == STATUS_KNOWN)
        unsure = sum(1 for g in grading.values() if g.status == STATUS_UNSURE)
        unknown = sum(1 for g in grading.values() if g.status == STATUS_UNKNOWN)
        st.success(f"앎 {known} · 헷갈림 {unsure} · 모름 {unknown}")

    st.write("문제마다 아는 만큼 적어 주세요. 모르면 '모르겠어요'를 체크하면 돼요. 답은 한 번에 채점해요.")
    for i, cid in enumerate(ids, start=1):
        q: Question = st.session_state.questions.get(cid)
        if q is None:
            continue
        c = by_id[cid]
        with st.container(border=True):
            st.markdown(f"**{i}. {c.name}**")
            st.write(q.question)
            g = grading.get(cid)
            if g is None:
                st.session_state.answers[cid] = st.text_area("내 답", key=f"ans_{cid}", height=100,
                                                             value=st.session_state.answers.get(cid, ""))
                st.session_state.dont_know[cid] = st.checkbox("모르겠어요", key=f"dk_{cid}",
                                                              value=st.session_state.dont_know.get(cid, False))
            else:
                color = STATUS_COLOR.get(g.status, "gray")
                st.markdown(f":{color}[**{g.status}**] · {g.score}/10" + (f" · 틀린 유형: {g.error_type}" if g.error_type else ""))
                st.write(g.reason)
                with st.expander("정답과 근거 페이지"):
                    st.write(q.answer)
                    st.caption("근거: " + ", ".join(f"p.{p}" for p in q.source_pages))
                    for it, sc in zip(q.rubric, g.rubric_scores or [None] * len(q.rubric)):
                        st.write(f"- {it.point} ({'?' if sc is None else sc}/{it.score})")

    if not grading:
        if st.button("채점하기", type="primary"):
            _grade_all(ids)
    else:
        if st.button("우선순위 보기 →", type="primary"):
            go(4)


def _grade_all(ids: list[str]) -> None:
    """세션 상태는 메인 스레드에서만 읽고 쓴다. 스레드에는 순수 인자만 넘긴다."""
    material: Material = st.session_state.material
    meta = set(st.session_state.concepts.meta_pages)
    by_id = {c.id: c for c in st.session_state.concepts.concepts}
    questions = dict(st.session_state.questions)
    answers = dict(st.session_state.answers)
    dont_know = dict(st.session_state.dont_know)
    usage = Usage()

    jobs: list[tuple[str, str]] = []
    for cid in ids:
        if dont_know.get(cid) or not answers.get(cid, "").strip():
            st.session_state.grading[cid] = empty_grading()
        else:
            jobs.append((cid, answers[cid]))

    def one(job: tuple[str, str]) -> tuple[str, Grading]:
        cid, ans = job
        return cid, grade_answer(by_id[cid], questions[cid], ans, material, meta, usage)

    try:
        with st.spinner(f"채점 중… ({len(jobs)}개)"):
            with ThreadPoolExecutor(max_workers=5) as ex:
                results = list(ex.map(one, jobs))
    except LLMError as e:
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
    answers = dict(st.session_state.answers)
    grading = dict(st.session_state.grading)
    usage = Usage()

    def one(cid: str) -> tuple[str, Explanation]:
        return cid, explain(by_id[cid], material, meta, status.get(cid, STATUS_NOT_DIAGNOSED), questions.get(cid),
                            answers.get(cid), grading.get(cid), usage)

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(one, ids))
    for cid, e in results:
        st.session_state.explanations[cid] = e
    add_usage(usage)


def screen_s04() -> None:
    st.title("④ 우선순위 보완 학습")
    if st.session_state.priorities is None:
        st.session_state.priorities = compute_priorities(st.session_state.scores, st.session_state.grading)
    pri = st.session_state.priorities
    rows = [{"우선순위": i, "개념": p.name, "출제 가능성(%)": p.exam_pct, "이해 상태": p.status,
             "우선순위 점수": p.priority, "권장": p.action} for i, p in enumerate(pri, start=1)]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("우선순위 점수 = 출제 가능성 × (1 − 이해도). 이해도: 앎 1.0 · 헷갈림 0.5 · 모름 0.0 · 진단 안 함 0.5")

    # 상위 N개 자동 설명
    auto = [p.concept_id for p in pri[:AUTO_EXPLAIN_TOP] if p.concept_id not in st.session_state.explanations]
    if auto:
        try:
            with st.spinner(f"보완 설명 {len(auto)}개 만드는 중…"):
                _explain_many(auto)
        except LLMError as e:
            show_error(error_message(e), str(e))

    st.subheader("보완 설명")
    for i, p in enumerate(pri, start=1):
        e: Explanation | None = st.session_state.explanations.get(p.concept_id)
        with st.container(border=True):
            color = STATUS_COLOR.get(p.status, "gray")
            st.markdown(f"**{i}. {p.name}** · 출제 {p.exam_pct}% · :{color}[{p.status}] · {p.action}")
            if e is None:
                if st.button("설명 보기", key=f"ex_{p.concept_id}"):
                    try:
                        with st.spinner("설명 만드는 중…"):
                            _explain_many([p.concept_id])
                        st.rerun()
                    except LLMError as err:
                        show_error(error_message(err), str(err))
                continue
            if e.my_gap:
                st.markdown(f"내가 놓친 점: *{e.my_gap}*")
            st.write(e.explanation)
            if e.not_found:
                st.warning("올린 자료에서 찾지 못함 · " + (e.not_found_note or "") + " 교재 다른 장이나 수업 노트를 확인하세요. (E-12)")
            if e.check_pages:
                st.caption("다시 볼 페이지: " + ", ".join(f"p.{n}" for n in e.check_pages))

    st.divider()
    md = to_markdown(st.session_state.material.name, st.session_state.scores, st.session_state.grading, pri,
                     st.session_state.explanations, transcript_used=bool(st.session_state.transcript))
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("결과 다운로드 (.md)", data=md.encode("utf-8"),
                           file_name=f"빈틈노트_결과_{date.today().isoformat()}.md", mime="text/markdown",
                           use_container_width=True)
    with c2:
        if st.button("다른 자료로 다시", use_container_width=True):
            reset_state()
            go(1)


# ----------------------------------------------------------------- 화면 S05


def screen_s05() -> None:
    st.title("⑤ 안내·설정")
    st.markdown(
        """
**사용 방법**
1. 강의자료(PDF/PPTX)와 녹음(또는 대본)을 올리고 **분석 시작**
2. ② 출제 포인트 순위와 근거를 확인
3. ③ 상위 개념의 진단 문제에 답하고 채점
4. ④ 우선순위와 자료 근거 보완 설명을 보고, 결과를 .md로 저장

**주의**
- 출제를 보장하지 않습니다. 공부 우선순위를 정하는 참고용입니다.
- 녹음은 교수님 허락을 받은 것만, 개인 학습 목적으로만 올려 주세요.
- 올린 파일은 이 앱의 서버에 저장하지 않습니다. 분석을 위해 AI 제공사(Anthropic, OpenAI) 서버로 전송됩니다.
- 학번·전화번호·이메일은 AI에 보내기 전에 가립니다.
"""
    )
    st.subheader("현재 설정")
    u = st.session_state.usage
    st.table({
        "항목": ["언어 모델", "음성 인식", "진단 개념 수", "가중치 버전", "이번 세션 AI 호출", "입력 토큰", "출력 토큰"],
        "값": [LLM_MODEL, (STT_MODEL if stt.stt_available() else "꺼짐 (대본 붙여넣기만)"), str(st.session_state.n_diag),
               WEIGHTS_VERSION, str(u["calls"]), str(u["input_tokens"]), str(u["output_tokens"])],
    })
    if fake_mode():
        st.warning("가짜 AI 모드(BINTM_FAKE_AI=1)로 동작 중이에요. 결과는 저장된 샘플이에요.")
    st.caption("KOREATECH AI 실습형 이벤트 · Build for Students · 팀 빈틈노트")


# ----------------------------------------------------------------- 사이드바와 라우팅


def sidebar() -> None:
    with st.sidebar:
        st.markdown("## 빈틈노트")
        has_scores = st.session_state.scores is not None
        has_grading = bool(st.session_state.grading)
        enabled = [True, has_scores, has_scores, has_grading, True]
        cur = st.session_state.step
        for i, (label, ok) in enumerate(zip(STEPS, enabled), start=1):
            mark = "▶" if i == cur else ("✓" if ok and i < cur else ("·" if ok else "🔒"))
            if st.button(f"{mark} {label}", key=f"nav_{i}", disabled=not ok, use_container_width=True):
                go(i)
        st.divider()
        st.session_state.n_diag = st.slider("진단할 개념 수", 3, 8, st.session_state.n_diag,
                                            help="② 순위 상위 몇 개를 진단할지")
        if st.button("처음부터", use_container_width=True):
            reset_state()
            go(1)
        st.caption(f"모델: {LLM_MODEL}")
        if fake_mode():
            st.caption("가짜 AI 모드")


def main() -> None:
    load_secrets_into_env()
    init_state()
    sidebar()
    step = st.session_state.step
    if step in (2, 3) and st.session_state.scores is None:
        st.session_state.step = step = 1
        st.info("새로고침하면 결과가 사라져요. 결과는 ④에서 내보내기로 저장할 수 있어요. 자료를 다시 올려 주세요. (E-14)")
    if step == 4 and not st.session_state.grading:
        st.session_state.step = step = 1 if st.session_state.scores is None else 3
    {1: screen_s01, 2: screen_s02, 3: screen_s03, 4: screen_s04, 5: screen_s05}[step]()


main()
