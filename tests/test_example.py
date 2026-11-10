# T-49 결과 예시 만들기 (scripts/make_example.py, v1.10): 가짜 AI로 한 바퀴 → 파일 5개, 마크다운 변환
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("make_example", ROOT / "scripts" / "make_example.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t49_example_files_from_sample(tmp_path):
    """앱과 같은 순서(샘플 → 진단 → 예시 답 → 채점 → ④)로 돌려 HTML 2개, 같은 내용의 마크다운 2개, README를 쓴다."""
    mod = _load()
    stats = mod.run(tmp_path)          # tests/conftest.py가 BINTM_FAKE_AI=1을 켜 둔다
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"README.md", "공부순서_오답노트.html", "공부순서_오답노트.md", "요약노트.html", "요약노트.md"}
    assert stats["fake"] and stats["questions"] and stats["known"] + stats["unsure"] + stats["unknown"] == stats["questions"]
    assert stats["known"] and stats["unsure"] and stats["unknown"]      # 예시 답이라 앎·헷갈림·모름이 모두 나온다
    assert not stats["failed"]

    study = (tmp_path / "공부순서_오답노트.md").read_text(encoding="utf-8")
    notes = (tmp_path / "요약노트.md").read_text(encoding="utf-8")
    for md in (study, notes):
        assert "<div" not in md and "<span" not in md and "data:image" not in md and "<style" not in md
        assert "실제 출제를 보장하지 않습니다" in md
    assert study.startswith("# 빈틈노트 공부 순서·오답노트") and "## 1. 공부 순서" in study and "## 2. 오답노트" in study
    assert "**내가 놓친 점**" in study and "(p." in study and "출제 점수" in study
    assert notes.startswith("# 빈틈노트 시험 대비 요약 노트") and "**핵심**" in notes
    index = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "가짜 AI" in index and "(공부순서_오답노트.md)" in index and "출제를 보장하지 않습니다" in index


def test_t49_html_to_markdown_pieces():
    md = _load().html_to_markdown(
        '<html><head><style>p{}</style><title>t</title></head><body><main><h2>제목</h2>'
        '<p>설명이다<span class="pg">p.3</span>.</p><div class="badges"><span class="badge">모름</span>'
        '<span class="badge">2/10</span></div><ol class="choices"><li>① 가</li><li>② 나 ✓ 정답</li></ol>'
        '<div class="bf"><img alt="배열(인덱스 1부터): [9, 7]" src="data:x"></div>'
        '<table><tr><td>인덱스</td><td>1</td></tr><tr><td>값</td><td>a|b</td></tr></table></main></body></html>')
    assert "## 제목" in md and "설명이다 (p.3)." in md and "`모름` `2/10`" in md
    assert "- ① 가" in md and "- ② 나 ✓ 정답" in md and "(그림) 배열(인덱스 1부터): [9, 7]" in md
    assert "| 인덱스 | 1 |\n|---|---|\n| 값 | a\\|b |" in md
    assert "p{}" not in md and "data:x" not in md
