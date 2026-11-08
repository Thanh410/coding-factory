"""Tests for the LLM provider chain and the provider-fallback coding agent.

These exercise the real HTTP client path: a local server speaks the OpenAI
chat-completions protocol, so nothing about our own code is mocked.
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from factory import providers
from factory.adapters.llm import LLMAdapter, _dispatch, _safe_path
from factory.config import Settings
from factory.engine import Engine
from factory.models import Task, TaskState
from factory.pr import PullRequest
from factory.state import Store


# --------------------------------------------------------------------------- #
# A scripted OpenAI-compatible server
# --------------------------------------------------------------------------- #
def _tool_call(name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def _final(text: str) -> dict:
    return {"role": "assistant", "content": text}


class _Server:
    """Serves a scripted list of assistant messages, one per request."""

    def __init__(self, script: list[dict], *, fail_with: int | None = None) -> None:
        self.script = list(script)
        self.fail_with = fail_with
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode() or "{}")
                outer.requests.append(
                    {"path": self.path, "body": body, "headers": dict(self.headers)}
                )
                if outer.fail_with is not None:
                    self.send_response(outer.fail_with)
                    self.end_headers()
                    self.wfile.write(b'{"error": "boom"}')
                    return
                message = outer.script.pop(0) if outer.script else _final("done")
                payload = json.dumps({"choices": [{"message": message}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # silence
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_BASE_URL",
        "GEMINI_BASE_URL",
        "OPENROUTER_MODEL",
        "GEMINI_MODEL",
        "FACTORY_LLM_CHAIN",
        "FACTORY_LLM_MAX_STEPS",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# Provider chain resolution
# --------------------------------------------------------------------------- #
def test_chain_skips_unconfigured_providers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    chain = providers.resolve_chain("openrouter,gemini,ollama")
    # gemini has no key -> skipped; ollama needs no key -> kept.
    assert [p.name for p in chain] == ["openrouter", "ollama"]


def test_chain_pins_model_per_step(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    (provider,) = providers.resolve_chain("openrouter:anthropic/claude-3.5-sonnet")
    assert provider.name == "openrouter"
    assert provider.model == "anthropic/claude-3.5-sonnet"


def test_chain_model_env_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
    (provider,) = providers.resolve_chain("openrouter")
    assert provider.model == "meta-llama/llama-3.1-8b-instruct"


def test_unknown_provider_name_raises(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="unknown LLM provider"):
        providers.resolve_chain("openrouter,typo-provider")


def test_gemini_accepts_google_api_key_alias(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
    (provider,) = providers.resolve_chain("gemini")
    assert provider.name == "gemini"


def test_ollama_needs_no_key(monkeypatch):
    (provider,) = providers.resolve_chain("ollama")
    assert provider.endpoint() == "http://127.0.0.1:11434/v1/chat/completions"
    assert provider.headers["Authorization"] == "Bearer not-needed"


def test_gemini_default_model_is_current(monkeypatch):
    # Gemini 2.x is retired for new keys; guard against regressing to it.
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    (provider,) = providers.resolve_chain("gemini")
    assert provider.model == "gemini-3.5-flash"


def test_openrouter_sends_attribution_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    (provider,) = providers.resolve_chain("openrouter")
    assert provider.headers["X-Title"] == "coding-factory"


def test_guardrail_error_gets_actionable_hint():
    from factory.adapters.llm import _hint

    hint = _hint(404, "0 endpoints ... matching your guardrail restrictions and data policy")
    assert "settings/privacy" in hint


def test_key_limit_error_gets_hint():
    from factory.adapters.llm import _hint

    assert "key limit" in _hint(403, "Key limit exceeded (daily limit)").lower()


# --------------------------------------------------------------------------- #
# Free-model chain alias
# --------------------------------------------------------------------------- #
def test_free_alias_expands_to_curated_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    chain = providers.resolve_chain("free")
    assert len(chain) == len(providers.FREE_MODELS)
    assert all(p.name == "openrouter" for p in chain)
    assert [p.model for p in chain] == list(providers.FREE_MODELS)
    # Every curated entry must actually be a $0 model.
    assert all(m.endswith(":free") for m in providers.FREE_MODELS)


def test_free_alias_respects_limit(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    chain = providers.resolve_chain("free:3")
    assert [p.model for p in chain] == list(providers.FREE_MODELS[:3])


def test_free_alias_needs_openrouter_key(monkeypatch):
    # No key -> the whole free group is unavailable (not an error).
    assert providers.resolve_chain("free") == []


def test_free_alias_combines_with_ollama(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    chain = providers.resolve_chain("free:2,ollama")
    assert [p.name for p in chain] == ["openrouter", "openrouter", "ollama"]
    assert chain[-1].model == "qwen2.5:3b"


def test_free_models_have_no_duplicates():
    assert len(set(providers.FREE_MODELS)) == len(providers.FREE_MODELS)


def test_models_command_lists_free_models(capsys, monkeypatch):
    from factory import cli

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    assert cli.main(["models"]) == 0
    out = capsys.readouterr().out
    assert providers.FREE_MODELS[0] in out
    assert "FACTORY_LLM_CHAIN=free" in out


# --------------------------------------------------------------------------- #
# The adapter: tool loop, fallback, safety
# --------------------------------------------------------------------------- #
def test_llm_adapter_writes_file_and_summarizes(tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    script = [
        _tool_call("write_file", {"path": "generated.txt", "content": "hello\n"}),
        _final("All set.\nSUMMARY: wrote generated.txt"),
    ]
    with _Server(script) as server:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_BASE_URL", server.url)
        monkeypatch.setenv("FACTORY_LLM_CHAIN", "openrouter")

        result = LLMAdapter(timeout=30).run(Task(external_id="t1", title="x"), worktree, "do it")

    assert result.ok is True
    assert "wrote generated.txt" in result.summary
    assert (worktree / "generated.txt").read_text() == "hello\n"
    # The request used the configured model and the tools schema.
    assert server.requests[0]["body"]["model"] == "openai/gpt-4o-mini"
    assert server.requests[0]["body"]["tools"][0]["function"]["name"] == "read_file"


def test_llm_adapter_falls_back_to_next_provider(tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    failing = _Server([], fail_with=500)
    working = _Server(
        [
            _tool_call("write_file", {"path": "f.txt", "content": "ok"}),
            _final("SUMMARY: used the backup provider"),
        ]
    )
    with failing as first, working as second:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_BASE_URL", first.url)
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        monkeypatch.setenv("GEMINI_BASE_URL", second.url)
        monkeypatch.setenv("FACTORY_LLM_CHAIN", "openrouter,gemini")

        result = LLMAdapter(timeout=30).run(Task(external_id="t2", title="x"), worktree, "do it")

    assert result.ok is True
    assert "backup provider" in result.summary
    assert (worktree / "f.txt").read_text() == "ok"
    assert first.requests and second.requests  # both were tried, in order
    assert "provider openrouter failed" in Path(result.log_path).read_text()


def test_llm_adapter_reports_when_no_provider(tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.setenv("FACTORY_LLM_CHAIN", "gemini")  # no key -> empty chain
    result = LLMAdapter(timeout=30).run(Task(external_id="t3", title="x"), worktree, "do it")
    assert result.ok is False
    assert result.exit_code == 127
    assert "No LLM provider configured" in result.summary


def test_llm_adapter_fails_when_all_providers_fail(tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    with _Server([], fail_with=429) as server:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_BASE_URL", server.url)
        monkeypatch.setenv("FACTORY_LLM_CHAIN", "openrouter")
        result = LLMAdapter(timeout=30).run(Task(external_id="t4", title="x"), worktree, "do it")
    assert result.ok is False
    assert "all LLM providers failed" in result.summary
    assert "HTTP 429" in result.summary


def test_tool_rejects_path_escape(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    with pytest.raises(Exception, match="escapes the worktree"):
        _safe_path(worktree, "../outside.txt")
    with pytest.raises(Exception, match="escapes the worktree"):
        _dispatch(worktree, "write_file", {"path": "../evil.txt", "content": "x"})
    assert not (tmp_path / "evil.txt").exists()


def test_tool_list_files_skips_git(tmp_path):
    worktree = tmp_path / "wt"
    (worktree / ".git").mkdir(parents=True)
    (worktree / ".git" / "config").write_text("x")
    (worktree / "a.py").write_text("x")
    listing = _dispatch(worktree, "list_files", {})
    assert "a.py" in listing
    assert ".git/config" not in listing


# --------------------------------------------------------------------------- #
# End-to-end through the engine with the llm backend
# --------------------------------------------------------------------------- #
def _git(args: list[str]) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(["init", "--bare", "-b", "main", str(remote)])
    seed = tmp_path / "seed"
    _git(["clone", str(remote), str(seed)])
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git(["-C", str(seed), "config", k, v])
    (seed / "README.md").write_text("seed\n")
    _git(["-C", str(seed), "add", "-A"])
    _git(["-C", str(seed), "commit", "-m", "init"])
    _git(["-C", str(seed), "push", "-u", "origin", "main"])
    return seed


def test_engine_ships_change_from_llm_backend(tmp_path, monkeypatch):
    seed = _init_repo(tmp_path)
    monkeypatch.setenv("FACTORY_CHECKS", "test -f generated.txt")

    script = [
        # Spec pass: the architect returns a plan (no tools).
        _final("PLAN:\n- create generated.txt"),
        _tool_call("write_file", {"path": "generated.txt", "content": "from the llm agent\n"}),
        _final("SUMMARY: created generated.txt"),
    ]
    with _Server(script) as server:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_BASE_URL", server.url)
        monkeypatch.setenv("FACTORY_LLM_CHAIN", "openrouter")

        settings = Settings(
            repo=seed,
            remote="origin",
            base_branch="main",
            work_root=tmp_path / "work",
            db_path=tmp_path / "work" / "state.db",
            branch_prefix="factory/",
            git_author_name="factory",
            git_author_email="f@f",
            max_repairs=1,
            task_timeout_seconds=120,
            agent_timeout_seconds=120,
        )
        settings.ensure_dirs()
        store = Store(settings.db_path)
        task = Task(external_id="llm-1", title="Add generated file")
        store.upsert(task)

        monkeypatch.setattr(
            "factory.engine.pr_mod.create_pr",
            lambda **kw: PullRequest(url="https://example.test/pr/1", number=1),
        )
        Engine(settings, store, "llm").process(task)
        store.close()

    assert task.state is TaskState.PR_OPEN, task.detail
    shown = subprocess.run(
        ["git", "-C", str(seed), "show", "factory/llm-1-add-generated-file:generated.txt"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert shown.returncode == 0 and "from the llm agent" in shown.stdout
