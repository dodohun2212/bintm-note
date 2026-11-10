# -*- coding: utf-8 -*-
"""샘플 자료로 실제 AI를 한 바퀴 돌려 결과 예시 파일을 만든다 (v1.10).

화면을 열지 못하는 사람(심사 AI 포함)도 앱이 만드는 결과물을 읽을 수 있게, 앱의
"샘플 자료로 체험하기 → 개념 진단하기 → 예시 답 채우기 → 채점하기 → 공부 순서 보기"와 같은 순서로 돌린다.
docs/결과_예시/에 내려받기 파일 2개(HTML)와 같은 내용의 마크다운 2개, 만든 방법과 잰 값을 적은 README.md를 저장한다.

실행 (저장소 맨 위 폴더에서):
    python scripts/make_example.py                      # 실제 AI. 키는 환경변수 또는 .streamlit/secrets.toml
    BINTM_FAKE_AI=1 python scripts/make_example.py --out <폴더>   # 가짜 AI(저장된 결과)로 모양만 확인
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_PDF = ROOT / "samples" / "자료구조_8장_트리와힙_가상강의자료.pdf"
SAMPLE_SCRIPT = ROOT / "samples" / "강의녹음_대본_8장_트리와힙.md"
OUT_DIR = ROOT / "docs" / "결과_예시"
STUDY_NAME = "공부순서_오답노트"
NOTES_NAME = "요약노트"


# ----------------------------------------------------------------- 키 읽기


def load_keys() -> None:
    """키는 환경변수 → .streamlit/secrets.toml 순. 값은 화면에 찍지 않는다."""
    path = ROOT / ".streamlit" / "secrets.toml"
    if not path.exists():
        return
    import tomllib
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        value = str(data.get(key) or "").strip()
        if value and not os.environ.get(key):
            os.environ[key] = value


# ----------------------------------------------------------------- HTML → 마크다운


_SKIP = {"head", "style", "script", "title"}
_VOID = {"br", "img", "meta", "hr", "link", "input", "wbr"}


class _Markdown(HTMLParser):
    """내려받기 HTML(core/export.py)을 GitHub에서 읽기 좋은 마크다운으로 바꾼다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, str, Optional[Callable[[], None]]]] = []
        self.skip = 0
        self.row = 0          # 공부 순서 한 줄(div.row) 안이면 블록을 나누지 않는다
        self.tiles = 0
        self.tile_n = 0
        self.tier = 0
        self.table: Optional[list[list[str]]] = None
        self.cell: Optional[list[str]] = None

    # 출력
    def _emit(self, s: str) -> None:
        (self.cell if self.cell is not None else self.parts).append(s)

    def _block(self) -> None:
        if self.cell is not None:
            self.cell.append(" ")
            return
        tail = "".join(self.parts[-3:])
        if self.parts and not tail.endswith("\n\n"):
            self.parts.append("\n" if tail.endswith("\n") else "\n\n")

    def _push(self, tag: str, closer: str = "", on_close: Optional[Callable[[], None]] = None) -> None:
        if tag not in _VOID:
            self.stack.append((tag, closer, on_close))

    # 여는 태그
    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        if tag in ("h1", "h2", "h3", "h4"):
            self._block()
            self._emit("#" * int(tag[1]) + " ")
            self._push(tag, "\n\n")
        elif tag == "div":
            self._div(cls)
        elif tag in ("p", "footer", "section", "details"):
            self._block()
            self._push(tag, "\n\n")
        elif tag == "summary":
            self._block()
            self._emit("**")
            self._push(tag, "**\n\n")
        elif tag == "span":
            self._span(cls)
        elif tag in ("b", "strong"):
            self._emit("**")
            self._push(tag, "** ")
        elif tag == "small":
            self._emit("\n\n" if self.tier else " · ")
            self._push(tag)
        elif tag in ("ul", "ol"):
            self._block()
            self._push(tag, "\n\n")
        elif tag == "li":
            self._emit("\n- ")
            self._push(tag)
        elif tag == "br":
            self._emit(" / " if self.cell is not None else "  \n")
        elif tag == "img":
            self._block()
            self._emit("(그림) " + (a.get("alt") or "").strip())
            self._block()
        elif tag == "table":
            self._block()
            self.table = []
            self._push(tag, "", self._end_table)
        elif tag == "tr" and self.table is not None:
            self.table.append([])
            self._push(tag)
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []
            self._push(tag, "", self._end_cell)
        else:
            self._push(tag)

    def _div(self, cls: set[str]) -> None:
        if "row" in cls:
            self._block()
            self.row += 1
            self._push("div", "\n\n", self._leave_row)
        elif self.row:
            starts = {"rank": "**", "name": "**", "small": " · ", "chips": " · 근거: ", "right-col": " · "}
            ends = {"rank": ".** ", "name": "** "}
            key = next((k for k in starts if k in cls), "")
            self._emit(starts.get(key, ""))
            self._push("div", ends.get(key, ""))
        elif "tiles" in cls:
            self._block()
            self.tiles += 1
            self.tile_n = 0
            self._push("div", "\n\n", self._leave_tiles)
        elif "tile" in cls and self.tiles:
            self._emit(" · " if self.tile_n else "")
            self.tile_n += 1
            self._push("div")
        elif "tier" in cls:
            self._block()
            self._emit("### ")
            self.tier += 1
            self._push("div", "\n\n", self._leave_tier)
        elif "sec" in cls:
            self._block()
            self._emit("#### ")
            self._push("div", "\n\n")
        elif cls & {"notice", "warn"}:
            self._block()
            self._emit("> ")
            self._push("div", "\n\n")
        elif "bf-cap" in cls:
            self._block()
            self._emit("*")
            self._push("div", "*\n\n")
        else:
            self._block()
            self._push("div", "\n\n")

    def _span(self, cls: set[str]) -> None:
        if "pg" in cls:                       # (p.3) 인용을 페이지 배지로 바꾼 것 → 다시 (p.3)
            self._emit(" (")
            self._push("span", ")")
        elif cls & {"badge", "chip"}:
            self._emit(" `")
            self._push("span", "`")
        elif "lbl" in cls:
            self._block()
            self._emit("**")
            self._push("span", "**\n\n")
        else:
            self._emit(" " if self.tiles else "")
            self._push("span", " " if "my" in cls else "")

    # 닫는 태그
    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in _VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                popped = self.stack[i:]
                del self.stack[i:]
                for _, closer, on_close in reversed(popped):
                    if closer:
                        self._emit(closer)
                    if on_close:
                        on_close()
                return

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self._emit(re.sub(r"\s+", " ", data))

    def _leave_row(self) -> None:
        self.row -= 1

    def _leave_tiles(self) -> None:
        self.tiles -= 1

    def _leave_tier(self) -> None:
        self.tier -= 1

    def _end_cell(self) -> None:
        if self.table is not None and self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            if not self.table:
                self.table.append([])
            self.table[-1].append(text)
        self.cell = None

    def _end_table(self) -> None:
        rows = [r for r in (self.table or []) if r]
        self.table = None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self._block()
        self._emit("\n".join(lines))
        self._block()


def html_to_markdown(doc: str) -> str:
    p = _Markdown()
    p.feed(doc)
    p.close()
    lines = []
    for ln in "".join(p.parts).split("\n"):
        hard = ln.endswith("  ") and ln.strip()
        ln = re.sub(r"(?<=\S) {2,}(?=\S)", " ", ln.strip())
        ln = ln.replace("( ", "(").replace(" )", ")").replace("** **", " ")
        lines.append(ln + ("  " if hard else ""))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text + "\n"


# ----------------------------------------------------------------- 한 바퀴


def _retry(fn: Callable, tries: int = 2):
    for i in range(tries):
        try:
            return fn()
        except Exception:   # noqa: BLE001  AI 오류나 형식이 안 맞는 답은 한 번 더
            if i == tries - 1:
                raise


def run(out_dir: Path, today: Optional[date] = None) -> dict:
    """샘플 자료로 앱과 같은 순서를 돌려 out_dir에 파일 5개를 쓴다. 잰 값을 돌려준다."""
    from config import AUTO_EXPLAIN_TOP, LLM_MODEL
    from core.concepts import extract_concepts
    from core.diagnose import (REASON_BLANK, REASON_DONT_KNOW, diag_targets, empty_grading, example_answers,
                               grade_answer, grade_mcq, make_question, mcq_answer_text, question_kind)
    from core.explain import explain
    from core.export import notes_html, study_html
    from core.extract import extract_material
    from core.llm import Usage, fake_mode, has_key
    from core.note import lecture_order, make_note_section, note_detail, professor_quotes, short_section
    from core.priority import compute_priorities
    from core.schemas import DETAIL_SHORT, STATUS_KNOWN, STATUS_UNKNOWN, STATUS_UNSURE
    from core.score import UTTERANCE_LABELS, compute_scores
    from core.utterances import find_utterances

    if not has_key():
        raise SystemExit("키가 없어요. .streamlit/secrets.toml의 ANTHROPIC_API_KEY를 채우거나 BINTM_FAKE_AI=1로 실행하세요.")
    today = today or date.today()
    usage, times = Usage(), {}
    t0 = time.perf_counter()

    # ① 분석 (샘플 자료로 체험하기)
    material = extract_material(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    transcript = SAMPLE_SCRIPT.read_text(encoding="utf-8")
    concepts = _retry(lambda: extract_concepts(material, usage))
    utts = _retry(lambda: find_utterances(concepts.concepts, transcript, usage))
    meta = set(concepts.meta_pages)
    scores = compute_scores(concepts.concepts, utts, meta)
    times["분석(개념·교수님 강조)"] = time.perf_counter() - t0

    # ② → ③ 개념 진단하기 (섞어서, 출제 점수 20점 이상 전부)
    t = time.perf_counter()
    by_id = {c.id: c for c in concepts.concepts}
    pct = {s.concept_id: s.pct for s in scores.scores}
    ids = diag_targets(scores)
    names = {cid: by_id[cid].name for cid in ids}

    def one_question(cid: str):
        others = [names[x] for x in ids if x != cid]
        return cid, _retry(lambda: make_question(by_id[cid], material, meta, usage, kind=question_kind(pct[cid]),
                                                 others=others))

    with ThreadPoolExecutor(max_workers=6) as ex:
        questions = dict(ex.map(one_question, ids))
    times["진단 문제"] = time.perf_counter() - t

    # 예시 답 채우기 → 채점하기 (객관식은 코드, 서술형은 AI)
    t = time.perf_counter()
    filled = dict(zip(ids, example_answers([questions[cid] for cid in ids])))
    grading, answer_texts, choices, confusions, essay_jobs = {}, {}, {}, {}, []
    for cid in ids:
        q, a = questions[cid], filled[cid]
        if q.is_mcq:
            grading[cid] = grade_mcq(q, a["choice"], guessed=a["guessed"])
            answer_texts[cid] = mcq_answer_text(q, a["choice"], a["guessed"])
            choices[cid] = a["choice"]
            if a["guessed"] and a["confusion"]:
                confusions[cid] = a["confusion"]
        elif a["dont_know"]:
            grading[cid], answer_texts[cid] = empty_grading(REASON_DONT_KNOW), ""
        elif not a["answer"].strip():
            grading[cid], answer_texts[cid] = empty_grading(REASON_BLANK), ""
        else:
            answer_texts[cid] = a["answer"]
            essay_jobs.append(cid)

    def one_grade(cid: str):
        return cid, _retry(lambda: grade_answer(by_id[cid], questions[cid], answer_texts[cid], material, meta, usage))

    with ThreadPoolExecutor(max_workers=6) as ex:
        grading.update(dict(ex.map(one_grade, essay_jobs)))
    times["채점"] = time.perf_counter() - t

    # ④ 공부 순서 보기: 보완 설명('지금 당장' 전부 + 상위 N개 + 헷갈린 점을 적은 개념)과 요약 노트
    t = time.perf_counter()
    priorities = compute_priorities(scores, grading)
    prow = {p.concept_id: p for p in priorities}
    want = ({p.concept_id for p in priorities[:AUTO_EXPLAIN_TOP]}
            | {p.concept_id for p in priorities if p.action == "지금 당장"} | set(confusions))
    explain_ids = [p.concept_id for p in priorities if p.concept_id in want]
    notes = {p.concept_id: short_section(by_id[p.concept_id], meta) for p in priorities
             if note_detail(p) == DETAIL_SHORT}
    note_ids = [p.concept_id for p in priorities if p.concept_id not in notes]

    def one_s04(job: tuple[str, str]):
        kind, cid = job
        try:
            if kind == "ex":
                return job, _retry(lambda: explain(by_id[cid], material, meta, prow[cid].status, questions.get(cid),
                                                   answer_texts.get(cid) if cid in grading else None,
                                                   grading.get(cid), usage, confusion=confusions.get(cid, "")))
            return job, _retry(lambda: make_note_section(by_id[cid], material, meta, prow[cid], utts,
                                                         grading.get(cid), usage))
        except Exception as e:   # noqa: BLE001  앱처럼 하나가 실패해도 나머지는 쓴다
            return job, e

    explanations, failed = {}, []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (kind, cid), out in ex.map(one_s04, [("ex", c) for c in explain_ids] + [("note", c) for c in note_ids]):
            if isinstance(out, Exception):
                failed.append(f"{'보완 설명' if kind == 'ex' else '요약 노트'}: {by_id[cid].name}")
            elif kind == "ex":
                explanations[cid] = out
            else:
                notes[cid] = out
    times["보완 설명·요약 노트"] = time.perf_counter() - t

    # 내려받기 2개 (+ 같은 내용의 마크다운)
    order = [c.id for c in lecture_order(concepts.concepts, meta)]
    quotes = {cid: [(UTTERANCE_LABELS.get(u.type, u.type), u.quote) for u in professor_quotes(cid, utts)]
              for cid in order}
    study = study_html(material.name, scores, grading, priorities, explanations, transcript_used=True,
                       questions=questions, answer_texts=answer_texts, choices=choices, today=today,
                       confusions=confusions)
    notes_doc = notes_html(material.name, priorities, notes, note_order=order, quotes=quotes, transcript_used=True,
                           today=today)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in ((STUDY_NAME, study), (NOTES_NAME, notes_doc)):
        (out_dir / f"{name}.html").write_text(doc, encoding="utf-8")
        (out_dir / f"{name}.md").write_text(html_to_markdown(doc), encoding="utf-8")

    status = [g.status for g in grading.values()]
    n_kind = sum(1 for q in questions.values() if q.is_mcq)
    stats = dict(
        date=today.isoformat(), fake=fake_mode(), model=LLM_MODEL, concepts=len(concepts.concepts), utterances=len(utts),
        questions=len(questions), essay=len(questions) - n_kind, mcq=n_kind,
        known=status.count(STATUS_KNOWN), unsure=status.count(STATUS_UNSURE), unknown=status.count(STATUS_UNKNOWN),
        tiers={a: sum(1 for p in priorities if p.action == a) for a in ("지금 당장", "다음", "복습만")},
        explanations=len(explanations), notes_ai=sum(1 for n in notes.values() if n.from_ai), notes=len(notes),
        failed=failed, times={k: round(v, 1) for k, v in times.items()}, total=round(time.perf_counter() - t0, 1),
        calls=usage["calls"], input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
        top3=[f"{s.name} {s.pct}점" for s in scores.scores[:3]],
        env=_env_text(),
    )
    (out_dir / "README.md").write_text(index_markdown(stats), encoding="utf-8")
    return stats


def _env_text() -> str:
    """만든 환경: Python과 주요 패키지 버전 (requirements.txt 고정값과 다르면 함께 적는다)."""
    import platform
    from importlib.metadata import PackageNotFoundError, version
    pinned = {}
    for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if "==" in ln:
            name, ver = ln.split("==", 1)
            pinned[name.strip().lower()] = ver.strip()
    parts = [f"Python {platform.python_version()}"]
    for name in ("anthropic", "pymupdf", "pydantic"):
        try:
            v = version(name)
        except PackageNotFoundError:
            continue
        fixed = pinned.get(name)
        parts.append(f"{name} {v}" + (f"(고정값 {fixed})" if fixed and fixed != v else ""))
    return " · ".join(parts)


def index_markdown(s: dict) -> str:
    """docs/결과_예시/README.md: 무엇을, 어떻게 만들었고, 무엇을 쟀는지."""
    how = "가짜 AI(저장된 결과, 모양 확인용)" if s["fake"] else f"실제 AI(`{s['model']}`)"
    times = " · ".join(f"{k} {v}초" for k, v in s["times"].items())
    tiers = " · ".join(f"{k} {v}" for k, v in s["tiers"].items())
    lines = [
        "# 결과 예시 (샘플 자료)",
        "",
        "배포 앱의 **샘플 자료로 체험하기 → 개념 진단하기 → 예시 답 채우기 → 채점하기 → 공부 순서 보기**와 같은 순서로 "
        "`scripts/make_example.py`가 만든 결과입니다. 앱을 열지 않고도 앱이 만드는 결과물을 읽을 수 있습니다.",
        "",
        "| 파일 | 내용 |",
        "|---|---|",
        f"| [공부 순서·오답노트]({STUDY_NAME}.md) ([HTML]({STUDY_NAME}.html)) | 공부 순서(출제 근거 포함), "
        "틀리거나 헷갈린 문제의 오답노트(문제·내 답·채점·정답·보완 설명), 맞힌 문제 |",
        f"| [시험 대비 요약 노트]({NOTES_NAME}.md) ([HTML]({NOTES_NAME}.html)) | 강의 순서대로 모든 개념. "
        "급하거나 출제 점수가 높거나 틀린 개념은 자세히 |",
        "",
        "## 만든 조건과 잰 값",
        "",
        f"- 만든 날: {s['date']} · AI: {how}",
        f"- 실행 환경: {s.get('env', '')}",
        "- 자료: `samples/`의 가상 강의자료(자료구조 8장 트리와 힙, 20쪽)와 녹음 대본",
        f"- 출제 점수 상위 3개: {' · '.join(s['top3'])}",
        f"- 개념 {s['concepts']}개, 교수님 강조 {s['utterances']}개, "
        f"진단 {s['questions']}문제(서술형 {s['essay']} · 객관식 {s['mcq']})",
        f"- 채점: 앎 {s['known']} · 헷갈림 {s['unsure']} · 모름 {s['unknown']}",
        f"- 공부 순서: {tiers} · 보완 설명 {s['explanations']}개 · "
        f"요약 노트 {s['notes']}개(AI {s['notes_ai']} · 짧게 {s['notes'] - s['notes_ai']})",
        f"- 걸린 시간(같은 단계의 AI 호출은 동시에 부름): {times} · 합계 {s['total']}초",
        f"- AI 호출 {s['calls']}번 · 입력 {s['input_tokens']:,} · 출력 {s['output_tokens']:,} 토큰",
    ]
    if s["failed"]:
        lines.append(f"- 만들지 못한 것(앱에서는 '다시 만들기' 버튼): {', '.join(s['failed'])}")
    lines += [
        "",
        "예시 답은 정답·반쯤 맞은 답·찍은 답·'모르겠어요'를 섞어 채운 것입니다(학생이 직접 푼 답이 아님). "
        "AI가 신호를 찾을 때마다 결과가 조금씩 달라질 수 있습니다. 출제를 보장하지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="샘플 자료로 결과 예시 파일을 만든다")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="저장할 폴더 (기본: docs/결과_예시)")
    args = ap.parse_args()
    load_keys()
    stats = run(args.out)
    print(f"저장: {args.out}")
    print(f"걸린 시간 {stats['total']}초 · AI 호출 {stats['calls']}번 · 채점 앎 {stats['known']} · 헷갈림 "
          f"{stats['unsure']} · 모름 {stats['unknown']}" + (f" · 실패 {len(stats['failed'])}" if stats["failed"] else ""))


if __name__ == "__main__":
    main()
