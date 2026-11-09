# -*- coding: utf-8 -*-
"""F06 강조 발화 찾기 (AI 호출 2, 프롬프트 02) + 인용 검사."""
from __future__ import annotations

import json
import re
from typing import Optional

from core import prompts
from core.extract import mask_pii
from core.llm import Usage, ask_json
from core.schemas import UTTERANCE_TYPES, Concept, Utterance, keep_valid

_WS = re.compile(r"\s+")


def _squash(s: str) -> str:
    return _WS.sub("", s or "")


def quote_in_transcript(quote: str, transcript: str) -> bool:
    """공백을 무시하고 대본에 실제로 있는 문장인지 (T-14)."""
    q = _squash(quote)
    return bool(q) and q in _squash(transcript)


def validate_utterances(raw: dict, transcript: str, concepts: list[Concept]) -> list[Utterance]:
    """형식이 틀린 발화는 그 발화만 버린다 (v1.8). 인용이 대본에 없는 발화도 버린다."""
    raw = raw if isinstance(raw, dict) else {}
    ids = {c.id for c in concepts}
    names = {c.name: c.id for c in concepts}
    out: list[Utterance] = []
    for u in keep_valid(Utterance, raw.get("utterances")):
        if u.type not in UTTERANCE_TYPES:
            continue
        if not quote_in_transcript(u.quote, transcript):
            continue
        cid = u.concept_id if u.concept_id in ids else names.get(u.concept_name)
        out.append(u.model_copy(update={"concept_id": cid}))
    return out


def concepts_for_prompt(concepts: list[Concept]) -> str:
    slim = [{"id": c.id, "name": c.name, "summary": c.summary, "keywords": c.keywords} for c in concepts]
    return json.dumps({"concepts": slim}, ensure_ascii=False, indent=1)


def find_utterances(concepts: list[Concept], transcript: str, usage: Optional[Usage] = None) -> list[Utterance]:
    if not transcript or not transcript.strip():
        return []
    # 대본도 학번·전화번호·이메일을 가린 뒤 보낸다 (v1.8). 화면에서 이미 가렸어도 한 번 더 가려 안전하게.
    # 인용 검사도 가린 대본으로 해야 AI가 돌려준 문장과 맞는다.
    transcript = mask_pii(transcript)
    prompt = prompts.fill("02", CONCEPTS_JSON=concepts_for_prompt(concepts), TRANSCRIPT=transcript)
    raw = ask_json(prompt, name="02", max_tokens=6000, thinking=True, usage=usage)
    return validate_utterances(raw, transcript, concepts)
