import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import llm_providers


# --- fakes for the OpenAI chat.completions response shape -------------------

class FakeMessage:
    def __init__(self, content, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class FakeChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeResponse:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


class FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, response):
        self.chat = FakeChat(FakeCompletions(response))


@pytest.fixture(autouse=True)
def _clear_client_cache():
    llm_providers._CLIENT_CACHE.clear()
    yield
    llm_providers._CLIENT_CACHE.clear()


# --- token handling -----------------------------------------------------

def test_get_api_token_reads_from_environment(monkeypatch):
    monkeypatch.setenv("KISTE_API_TOKEN", "test-token-value")
    assert llm_providers._get_api_token() == "test-token-value"


def test_get_api_token_missing_raises_configuration_error(monkeypatch):
    monkeypatch.delenv("KISTE_API_TOKEN", raising=False)
    with pytest.raises(llm_providers.KisteConfigurationError) as excinfo:
        llm_providers._get_api_token()
    assert "KISTE_API_TOKEN" in str(excinfo.value)


def test_call_kiste_missing_token_raises_before_any_network_setup(monkeypatch):
    monkeypatch.delenv("KISTE_API_TOKEN", raising=False)
    with pytest.raises(llm_providers.KisteConfigurationError) as excinfo:
        llm_providers.call_kiste(
            model="m", prompt="p", generation_config={},
            kiste_config={"base_url": "https://kiste.example.invalid/v1"},
        )
    assert "KISTE_API_TOKEN" in str(excinfo.value)


def test_call_kiste_metadata_never_contains_the_token(monkeypatch):
    monkeypatch.setenv("KISTE_API_TOKEN", "sk-should-never-appear-anywhere")
    response = FakeResponse(choices=[FakeChoice(FakeMessage("ok"))], usage=FakeUsage(1, 2))
    fake_client = FakeClient(response)
    monkeypatch.setattr(llm_providers, "_get_client", lambda base_url: fake_client)

    content, metadata = llm_providers.call_kiste(
        model="m", prompt="p", generation_config={},
        kiste_config={"base_url": "https://kiste.example.invalid/v1"},
    )

    serialized = json.dumps(metadata)
    assert "sk-should-never-appear-anywhere" not in serialized
    assert "sk-should-never-appear-anywhere" not in content


def test_get_client_builds_and_caches_a_real_openai_client(monkeypatch):
    """Exercises the real (lazily-imported) openai.OpenAI(...) construction
    path - no network call happens at construction time - and confirms one
    client is reused per base_url rather than rebuilt per call."""
    monkeypatch.setenv("KISTE_API_TOKEN", "test-token-value")

    client_a = llm_providers._get_client("https://kiste.example.invalid/v1")
    client_b = llm_providers._get_client("https://kiste.example.invalid/v1")

    assert client_a is client_b
    assert hasattr(client_a, "chat")


# --- request/response shape ----------------------------------------------

def test_call_kiste_returns_content_and_normalized_token_usage(monkeypatch):
    response = FakeResponse(
        choices=[FakeChoice(FakeMessage("hello world", reasoning_content=None), finish_reason="stop")],
        usage=FakeUsage(prompt_tokens=11, completion_tokens=22),
    )
    monkeypatch.setattr(llm_providers, "_get_client", lambda base_url: FakeClient(response))

    content, metadata = llm_providers.call_kiste(
        model="Qwen3.6-35B-A3B-MLX-8bit",
        prompt="explain this error",
        generation_config={"temperature": 0.1, "top_p": 0.9, "max_tokens": 700, "timeout_seconds": 120},
        kiste_config={"base_url": "https://kiste.example.invalid/v1"},
    )

    assert content == "hello world"
    assert metadata["prompt_eval_count"] == 11
    assert metadata["eval_count"] == 22
    assert metadata["finish_reason"] == "stop"
    assert metadata["reasoning_content_present"] is False
    assert metadata["reasoning_content_chars"] == 0
    assert metadata["provider"] == "kiste"
    assert metadata["model"] == "Qwen3.6-35B-A3B-MLX-8bit"


def test_call_kiste_reports_reasoning_content_presence_without_including_it_in_content(monkeypatch):
    reasoning = "lots of internal chain-of-thought the caller must not persist as the answer"
    response = FakeResponse(
        choices=[FakeChoice(FakeMessage("final answer", reasoning_content=reasoning), finish_reason="stop")],
        usage=FakeUsage(prompt_tokens=5, completion_tokens=700),
    )
    monkeypatch.setattr(llm_providers, "_get_client", lambda base_url: FakeClient(response))

    content, metadata = llm_providers.call_kiste(
        model="m", prompt="p", generation_config={},
        kiste_config={"base_url": "https://kiste.example.invalid/v1"},
    )

    assert content == "final answer"
    assert reasoning not in content
    assert metadata["reasoning_content_present"] is True
    assert metadata["reasoning_content_chars"] == len(reasoning)


def test_call_kiste_missing_content_normalizes_to_empty_string(monkeypatch):
    response = FakeResponse(choices=[FakeChoice(FakeMessage(None), finish_reason="length")])
    monkeypatch.setattr(llm_providers, "_get_client", lambda base_url: FakeClient(response))

    content, metadata = llm_providers.call_kiste(
        model="m", prompt="p", generation_config={},
        kiste_config={"base_url": "https://kiste.example.invalid/v1"},
    )

    assert content == ""
    assert metadata["finish_reason"] == "length"


def test_call_kiste_sends_prompt_as_single_user_message_and_forwards_generation_config(monkeypatch):
    response = FakeResponse(choices=[FakeChoice(FakeMessage("ok"))])
    fake_client = FakeClient(response)
    monkeypatch.setattr(llm_providers, "_get_client", lambda base_url: fake_client)

    llm_providers.call_kiste(
        model="m",
        prompt="THE RENDERED PROMPT",
        generation_config={"temperature": 0.2, "top_p": 0.8, "max_tokens": 123, "timeout_seconds": 45},
        kiste_config={"base_url": "https://kiste.example.invalid/v1"},
    )

    sent = fake_client.chat.completions.last_kwargs
    assert sent["model"] == "m"
    assert sent["messages"] == [{"role": "user", "content": "THE RENDERED PROMPT"}]
    assert sent["temperature"] == 0.2
    assert sent["top_p"] == 0.8
    assert sent["max_tokens"] == 123
    assert sent["timeout"] == 45


def test_call_kiste_missing_base_url_raises():
    with pytest.raises(llm_providers.KisteConfigurationError):
        llm_providers.call_kiste(model="m", prompt="p", generation_config={}, kiste_config={})
