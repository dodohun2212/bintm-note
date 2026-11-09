# -*- coding: utf-8 -*-
"""API 비용 보호 (v1.5). 배포 앱은 운영자 키 하나로 누구나 쓰므로, 한 사람이나 한꺼번에 몰린 사용이
키 한도를 다 써서 다른 사람이 못 쓰게 되는 일을 막는다. streamlit 의존 없음 (테스트 가능).

- 세션당 분석 횟수 제한: 화면 하나(브라우저 탭)에서 '분석 시작'·'샘플 자료로 체험하기'를 누를 수 있는 횟수
- 서버 전체 하루 분석 횟수 제한: 새로고침으로 세션 제한을 우회해도 하루 총량은 넘지 않게
- 샘플 진단 문제 재사용: 샘플 자료는 모두 같은 파일이므로 한 번 만든 문제를 다음 사람에게도 그대로 낸다
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Callable, Hashable, Optional


def session_left(used: int, limit: int) -> int:
    """이 세션에서 분석을 몇 번 더 할 수 있는지. limit이 0 이하면 제한 없음(-1)."""
    if limit <= 0:
        return -1
    return max(0, limit - used)


class DailyCounter:
    """서버 전체 하루 횟수. 날짜가 바뀌면 0부터. 여러 세션(스레드)이 동시에 불러도 안전하다."""

    def __init__(self, limit: int, today: Callable[[], date] = date.today):
        self.limit = limit
        self._today = today
        self._day = today()
        self._count = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        d = self._today()
        if d != self._day:
            self._day, self._count = d, 0

    @property
    def count(self) -> int:
        with self._lock:
            self._roll()
            return self._count

    def try_take(self) -> bool:
        """1회 쓰기. 오늘 한도가 남았으면 세고 True, 다 찼으면 세지 않고 False. limit이 0 이하면 항상 True."""
        with self._lock:
            self._roll()
            if self.limit > 0 and self._count >= self.limit:
                return False
            self._count += 1
            return True

    def give_back(self) -> None:
        """분석이 AI를 부르기 전에 실패했을 때(예: 스캔 PDF) 센 것을 돌려준다."""
        with self._lock:
            self._roll()
            self._count = max(0, self._count - 1)


class ResultCache:
    """만든 결과를 키로 저장해 다시 쓴다(샘플 진단 문제용). 개수가 넘치면 오래된 것부터 버린다."""

    def __init__(self, max_items: int = 200):
        self.max_items = max_items
        self._data: dict[Hashable, object] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[object]:
        with self._lock:
            return self._data.get(key)

    def put(self, key: Hashable, value: object) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._data[key] = value
            while len(self._data) > self.max_items:
                self._data.pop(next(iter(self._data)))

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
