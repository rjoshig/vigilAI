"""Tests for LLM settings loading (ADR-004)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from greenlight_ai.llm import ConfigError, LLMSettings


def test_defaults_are_the_mock_provider() -> None:
    """Tests and CI run on mock with no configuration at all."""
    settings = LLMSettings.from_env({})
    assert settings.provider == "mock"
    assert settings.temperature == 0.0
    assert settings.log_prompts is False


def test_environment_values_are_read() -> None:
    settings = LLMSettings.from_env(
        {
            "LLM_PROVIDER": "openai",
            "LLM_BASE_URL": "http://llm.internal:8000/v1/",
            "LLM_API_KEY": "secret",
            "LLM_MODEL": "gemma3:27b",
            "LLM_MAX_TOKENS": "1500",
            "LLM_TIMEOUT_S": "30",
            "LLM_PROMPT_VERSION": "4",
        }
    )
    assert settings.provider == "openai"
    assert settings.model == "gemma3:27b"
    assert settings.max_tokens == 1500
    assert settings.timeout_s == 30.0
    assert settings.prompt_version == "4"


def test_trailing_slash_is_stripped_so_path_joining_is_predictable() -> None:
    settings = LLMSettings.from_env(
        {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "http://x/v1/", "LLM_MODEL": "m"}
    )
    assert settings.base_url == "http://x/v1"


def test_real_provider_without_a_base_url_fails_at_load_time() -> None:
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        LLMSettings.from_env({"LLM_PROVIDER": "anthropic"})


def test_unknown_provider_is_rejected_by_name() -> None:
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        LLMSettings.from_env({"LLM_PROVIDER": "hal9000"})


@pytest.mark.parametrize("key", ["LLM_MAX_TOKENS", "LLM_MAX_CONCURRENCY", "LLM_MAX_TOKENS_PER_RUN"])
def test_bad_integers_name_the_offending_key(key: str) -> None:
    with pytest.raises(ConfigError, match=key):
        LLMSettings.from_env({key: "not a number"})


def test_bad_number_names_the_offending_key() -> None:
    with pytest.raises(ConfigError, match="LLM_TIMEOUT_S"):
        LLMSettings.from_env({"LLM_TIMEOUT_S": "soon"})


def test_bad_boolean_names_the_offending_key() -> None:
    with pytest.raises(ConfigError, match="LLM_LOG_PROMPTS"):
        LLMSettings.from_env({"LLM_LOG_PROMPTS": "maybe"})


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_truthy_booleans(value: str) -> None:
    assert LLMSettings.from_env({"LLM_LOG_PROMPTS": value}).log_prompts is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
def test_falsy_booleans(value: str) -> None:
    assert LLMSettings.from_env({"LLM_LOG_PROMPTS": value}).log_prompts is False


def test_settings_are_immutable() -> None:
    settings = LLMSettings.from_env({})
    with pytest.raises(ValidationError):
        settings.model = "other"  # type: ignore[misc]


def test_zero_max_tokens_is_rejected() -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env({"LLM_MAX_TOKENS": "0"})


def test_lenses_are_read_from_the_environment() -> None:
    settings = LLMSettings.from_env(
        {"LLM_VERIFY_LENSES": "delivery, requirements", "LLM_MAX_LENS_CALLS_PER_RUN": "9"}
    )
    assert settings.verify_lenses == ("delivery", "requirements")
    assert settings.max_lens_calls_per_run == 9


def test_single_stands_alone_in_the_lens_list() -> None:
    with pytest.raises(ConfigError, match="stands alone"):
        LLMSettings.from_env({"LLM_VERIFY_LENSES": "single,delivery"})
