# T-35~T-39 API 비용 보호 (v1.5): 세션당 분석 횟수, 서버 전체 하루 횟수, 샘플 문제 재사용, 빠른 진단
import threading
from datetime import date

import config
from core.diagnose import diag_targets
from core.guard import DailyCounter, ResultCache, session_left
from core.schemas import ScoresResult


def test_session_left():
    assert session_left(0, 5) == 5
    assert session_left(4, 5) == 1
    assert session_left(5, 5) == 0
    assert session_left(9, 5) == 0          # 넘쳐도 음수가 아님
    assert session_left(100, 0) == -1       # 0이면 제한 없음


def test_config_limits_are_set():
    assert config.MAX_ANALYSES_PER_SESSION > 0
    assert config.MAX_ANALYSES_PER_DAY >= config.MAX_ANALYSES_PER_SESSION
    assert 0 < config.QUICK_DIAG_TOP


def test_daily_counter_limit_and_new_day():
    today = [date(2026, 11, 11)]
    c = DailyCounter(3, today=lambda: today[0])
    assert [c.try_take() for _ in range(4)] == [True, True, True, False]
    assert c.count == 3                      # 다 찬 뒤에는 세지 않음
    c.give_back()                            # 분석이 실패하면 돌려줌
    assert c.try_take() and not c.try_take()
    today[0] = date(2026, 11, 12)            # 날짜가 바뀌면 0부터
    assert c.count == 0 and c.try_take()


def test_daily_counter_unlimited_and_thread_safe():
    assert all(DailyCounter(0).try_take() for _ in range(50))
    c = DailyCounter(100)
    ok = []

    def worker():
        for _ in range(50):
            ok.append(c.try_take())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(ok) == 100 and c.count == 100   # 400번 불러도 정확히 한도까지만


def test_result_cache_reuse_and_eviction():
    cache = ResultCache(max_items=2)
    assert cache.get("a") is None
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)                        # 가장 오래된 a를 버림
    assert cache.get("a") is None and cache.get("b") == 2 and cache.get("c") == 3 and len(cache) == 2


def _scores() -> ScoresResult:
    rows = [{"concept_id": f"c{i}", "name": f"개념{i}", "raw": pct / 10, "pct": pct, "body_pages": [], "reasons": []}
            for i, pct in enumerate([100, 90, 87, 59, 58, 52, 30, 27, 26, 23, 19, 7, 0], start=1)]
    return ScoresResult.model_validate({"max_raw": 10.0, "scores": rows})


def test_quick_diag_top_only_when_asked():
    scores = _scores()
    full = diag_targets(scores)
    assert len(full) == 10                                      # 기본: 20% 이상 전부 (기본 동작 그대로)
    assert diag_targets(scores, top=None) == full
    assert diag_targets(scores, top=5) == ["c1", "c2", "c3", "c4", "c5"]   # 빠른 진단: 순위 순서로 상위 5개
    assert diag_targets(scores, top=50) == full                 # 대상보다 크면 전부


def test_usage_merge_counts_every_call():
    # v1.5: 여러 호출을 묶어 더할 때 호출 수가 1로 세지던 문제
    from core.llm import Usage

    total, part = Usage(), Usage()
    part.add(100, 50, 1.5)
    part.add(200, 70, 2.5)
    total.merge(part)
    total.add(10, 5, 0.5)
    assert total["calls"] == 3 and total["input_tokens"] == 310 and total["output_tokens"] == 125
    assert abs(total["seconds"] - 4.5) < 1e-9
