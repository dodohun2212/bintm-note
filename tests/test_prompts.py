# T-12, T-13: 프롬프트 채우기, JSON 잘라내기
import pytest

from core import prompts
from core.llm import LLMJsonError, extract_json


def test_t12_fill_leaves_no_placeholder():
    text = prompts.fill("01", MATERIAL="=== 페이지 1 ===\n표지")
    assert "{{MATERIAL}}" not in text and "{{" not in text
    assert prompts.placeholders("03B") == {"CONCEPT_NAME", "QUESTION_JSON", "PAGES", "ANSWER"}
    with pytest.raises(KeyError):
        prompts.fill("02", TRANSCRIPT="...")  # CONCEPTS_JSON 빠짐


def test_all_prompt_files_exist():
    for name in prompts.PROMPT_FILES:
        assert prompts.load(name).strip()


def test_t13_extract_json():
    assert extract_json('설명입니다 {"a": 1} 끝') == {"a": 1}
    assert extract_json('```json\n{"b": [1, 2]}\n```') == {"b": [1, 2]}
    with pytest.raises(LLMJsonError):
        extract_json("JSON 없음")
    with pytest.raises(LLMJsonError):
        extract_json("{깨진")
