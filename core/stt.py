# -*- coding: utf-8 -*-
"""F03 녹음 → 대본. OpenAI 전사 API. 키는 환경변수 OPENAI_API_KEY에서만 읽는다."""
from __future__ import annotations

import os
import time
from typing import Optional

from config import STT_MODEL
from core.llm import Usage


class STTError(Exception):
    """E-05 음성 인식 실패."""


def stt_available() -> bool:
    return bool(STT_MODEL) and bool(os.environ.get("OPENAI_API_KEY"))


def transcribe(data: bytes, filename: str, usage: Optional[Usage] = None) -> str:
    """녹음 바이트를 한국어 대본으로. 임시 파일을 만들지 않고 메모리에서 바로 보낸다 (BR-06)."""
    if not stt_available():
        raise STTError("음성 인식 키가 없음")
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=2, timeout=600.0)
    t0 = time.time()
    try:
        result = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=(filename, data),
            language="ko",
            response_format="text",
        )
    except Exception as e:
        raise STTError(f"{type(e).__name__}: {e}") from e
    text = result if isinstance(result, str) else getattr(result, "text", str(result))
    if usage is not None:
        usage["stt_seconds"] = usage.get("stt_seconds", 0.0) + (time.time() - t0)
    return text.strip()
