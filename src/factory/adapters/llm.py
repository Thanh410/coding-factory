"""LLM coding-agent adapter with a provider fallback chain.

This backend drives an OpenAI-compatible chat-completions endpoint with tool
calls: the model reads and edits files in the worktree until it decides it is
done. Because OpenRouter, Google Gemini, and a local Ollama all expose the same
OpenAI-compatible API, one implementation covers all three, and the chain in
``providers`` lets the agent fail over when a provider is unconfigured,
rate-limited, or down.

Why a separate backend from Codex/Antigravity: those are full agent CLIs. This
one is a thin, dependency-free client so a 24/7 runner can use a hosted key
(OpenRouter/Gemini) or a self-hosted model (Ollama) without installing anything.

Config
    FACTORY_LLM_CHAIN      ordered providers, e.g. "openrouter,gemini,ollama"
    FACTORY_LLM_MAX_STEPS  max tool-call turns per attempt (default 30)
    FACTORY_LLM_MAX_TOKENS max tokens per completion (default 4096)
    FACTORY_LLM_TIMEOUT    per-request seconds (default: agent timeout)

Selection: pick this backend with ``--backend llm`` or ``FACTORY_BACKEND=llm``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import int_env
from ..models import AgentResult, Task
from ..providers import ResolvedProvider, resolve_chain
from .base import AgentAdapter, register


class ProviderError(RuntimeError):
    """A single provider failed; the caller should try the next one."""


class ToolError(RuntimeError):
    """A tool call was invalid (bad path, missing args); reported back to the model."""


# --------------------------------------------------------------------------- #
# Tools the agent may call. Deliberately file-scoped: the factory itself runs
# the project's checks, so the agent does not need a shell.
# --------------------------------------------------------------------------- #
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Repo-relative path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a UTF-8 text file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative path"},
                    "content": {"type": "string", "description": "Full new file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files under a directory (recursively, skipping .git).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory, default '.'"},
                },
                "required": [],
            },
        },
    },
]


@register("llm")
class LLMAdapter(AgentAdapter):
    name = "llm"

    def is_available(self) -> bool:
        try:
            return bool(resolve_chain())
        except ValueError:
            return False

    def run(self, task: Task, worktree: Path, prompt: str) -> AgentResult:
        chain = resolve_chain()
        log_path = worktree.parent / "agent.log"
        if not chain:
            log_path.write_text("no LLM provider configured\n", encoding="utf-8")
            return AgentResult(
                ok=False,
                summary=(
                    "No LLM provider configured. Set OPENROUTER_API_KEY and/or "
                    "GEMINI_API_KEY, or run Ollama locally. See FACTORY_LLM_CHAIN."
                ),
                log_path=str(log_path),
                exit_code=127,
            )

        max_steps = int_env("FACTORY_LLM_MAX_STEPS", 30)
        errors: list[str] = []
        transcript: list[str] = []

        for provider in chain:
            try:
                summary = self._run_provider(provider, worktree, prompt, max_steps, transcript)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                transcript.append(f"!! provider {provider.name} failed: {exc}")
                continue
            log_path.write_text("\n".join(transcript), encoding="utf-8")
            return AgentResult(ok=True, summary=summary, log_path=str(log_path), exit_code=0)

        log_path.write_text("\n".join(transcript), encoding="utf-8")
        return AgentResult(
            ok=False,
            summary="all LLM providers failed:\n" + "\n".join(errors),
            log_path=str(log_path),
            exit_code=1,
        )

    # -- one provider's tool-call loop -------------------------------------
    def _run_provider(
        self,
        provider: ResolvedProvider,
        worktree: Path,
        prompt: str,
        max_steps: int,
        transcript: list[str],
    ) -> str:
        transcript.append(f"== provider={provider.name} model={provider.model} ==")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_HINT},
            {"role": "user", "content": prompt},
        ]
        max_tokens = int_env("FACTORY_LLM_MAX_TOKENS", 4096)
        timeout = int_env("FACTORY_LLM_TIMEOUT", self.timeout)

        for step in range(1, max_steps + 1):
            message = _chat(provider, messages, timeout, max_tokens)
            content = (message.get("content") or "").strip()
            tool_calls = message.get("tool_calls") or []

            if content:
                transcript.append(f"-- step {step} assistant: {content[:2000]}")
            if not tool_calls:
                if not content:
                    raise ProviderError("empty response (no content, no tool calls)")
                return _extract_summary(content)

            # Record the assistant turn verbatim so the next request has context.
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                name, args, call_id = _parse_tool_call(call)
                try:
                    result = _dispatch(worktree, name, args)
                except ToolError as exc:
                    result = f"ERROR: {exc}"
                transcript.append(f"-- step {step} {name}({_short(args)}) -> {_short(result)}")
                messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": result}
                )

        raise ProviderError(f"exceeded {max_steps} tool-call steps without finishing")


def _chat(
    provider: ResolvedProvider,
    messages: list[dict[str, Any]],
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    """One chat-completions call. Raises ProviderError on any failure."""
    payload = json.dumps(
        {
            "model": provider.model,
            "messages": messages,
            "tools": _TOOLS,
            "tool_choice": "auto",
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        provider.endpoint(), data=payload, headers=provider.headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:400].decode("utf-8", "replace")
        raise ProviderError(f"HTTP {exc.code}: {detail}{_hint(exc.code, detail)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"network error: {exc}") from exc
    except ValueError as exc:
        raise ProviderError(f"invalid JSON response: {exc}") from exc

    try:
        return body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"unexpected response shape: {str(body)[:300]}") from exc


def _hint(code: int, detail: str) -> str:
    """Add an actionable hint for a few common, self-inflicted failures."""
    low = detail.lower()
    if "guardrail" in low or "data policy" in low or "zdr" in low:
        return (
            "\n[hint] OpenRouter blocked this model by your account's privacy/data "
            "policy (common for :free models). Enable it at "
            "https://openrouter.ai/settings/privacy, or use a non-free model."
        )
    if code == 403 and "key limit" in low:
        return "\n[hint] OpenRouter key limit reached; raise it in the dashboard."
    if code == 401:
        return "\n[hint] check the API key for this provider."
    if code == 404:
        return "\n[hint] model id may be wrong or retired for your key."
    return ""


def _parse_tool_call(call: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    fn = call.get("function", {})
    name = fn.get("name", "")
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args or "{}")
        except ValueError:
            args = {}
    else:
        args = raw_args or {}
    call_id = call.get("id") or f"call_{name}"
    return name, args, call_id


def _safe_path(worktree: Path, rel: str) -> Path:
    root = worktree.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"path escapes the worktree: {rel!r}")
    return target


def _dispatch(worktree: Path, name: str, args: dict[str, Any]) -> str:
    if name == "read_file":
        path = _safe_path(worktree, str(args.get("path", "")))
        if not path.is_file():
            raise ToolError(f"no such file: {args.get('path')!r}")
        return path.read_text(encoding="utf-8", errors="replace")[:20000]

    if name == "write_file":
        if "path" not in args or "content" not in args:
            raise ToolError("write_file requires 'path' and 'content'")
        path = _safe_path(worktree, str(args["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(args["content"]), encoding="utf-8")
        return f"wrote {args['path']} ({len(str(args['content']))} bytes)"

    if name == "delete_file":
        path = _safe_path(worktree, str(args.get("path", "")))
        if not path.exists():
            raise ToolError(f"no such file: {args.get('path')!r}")
        path.unlink()
        return f"deleted {args['path']}"

    if name == "list_files":
        root = _safe_path(worktree, str(args.get("path", ".") or "."))
        if not root.exists():
            raise ToolError(f"no such directory: {args.get('path')!r}")
        entries = []
        for p in sorted(root.rglob("*")):
            if ".git" in p.parts or not p.is_file():
                continue
            entries.append(str(p.relative_to(worktree.resolve())))
            if len(entries) >= 500:
                entries.append("... (truncated)")
                break
        return "\n".join(entries) or "(empty)"

    raise ToolError(f"unknown tool: {name}")


def _extract_summary(output: str) -> str:
    marker = "SUMMARY:"
    idx = output.rfind(marker)
    return output[idx + len(marker):].strip() if idx != -1 else output.strip()[-1000:]


def _short(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


_SYSTEM_HINT = (
    "You are a coding agent operating in a git worktree. Use the provided tools "
    "to read and edit files. Make focused changes that satisfy the task, then "
    "stop calling tools and reply with a final message ending in a 'SUMMARY:' "
    "section. Do not attempt to run git; the harness handles commits and PRs."
)
