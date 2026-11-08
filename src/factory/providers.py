"""LLM provider registry and fallback-chain resolution.

Every supported provider speaks the OpenAI-compatible chat-completions API, so a
single client drives any of them. The chain is what gives the factory its
resilience: if the first provider is unconfigured, rate-limited, or down, the
next one takes over.

Providers
    openrouter  hosted, many models, needs OPENROUTER_API_KEY
    gemini      Google AI Studio, needs GEMINI_API_KEY (or GOOGLE_API_KEY)
    ollama      self-hosted, no key, default http://127.0.0.1:11434/v1

Chain spec
    FACTORY_LLM_CHAIN=openrouter,gemini,ollama     (default order)
    A step may pin a model:  openrouter:anthropic/claude-3.5-sonnet
    Unknown names raise (a typo is a configuration error). Known providers that
    are simply unconfigured (no key) are skipped, which is the point of a chain.

Free models
    ``FACTORY_LLM_CHAIN=free`` expands to a curated list of OpenRouter models
    that are priced at $0 *and* support tool calling (see FREE_MODELS). Combined
    with a local fallback: ``FACTORY_LLM_CHAIN=free,ollama`` runs at no cost with
    failover. Run ``factory models`` to print the list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CHAIN = "openrouter,gemini,ollama"


@dataclass(frozen=True)
class Provider:
    """Static description of one OpenAI-compatible endpoint."""

    name: str
    base_url: str
    key_envs: tuple[str, ...]
    default_model: str
    model_env: str
    base_url_env: str
    requires_key: bool = True
    extra_headers: tuple[tuple[str, str], ...] = ()


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_envs=("OPENROUTER_API_KEY",),
        default_model="openai/gpt-4o-mini",
        model_env="OPENROUTER_MODEL",
        base_url_env="OPENROUTER_BASE_URL",
        extra_headers=(
            ("HTTP-Referer", "https://github.com/Thanh410/coding-factory"),
            ("X-Title", "coding-factory"),
        ),
    ),
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_envs=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        # Gemini 2.x is retired for new keys; 3.5-flash is current and verified
        # to work over the OpenAI-compatible endpoint, including tool calling.
        default_model="gemini-3.5-flash",
        model_env="GEMINI_MODEL",
        base_url_env="GEMINI_BASE_URL",
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://127.0.0.1:11434/v1",
        key_envs=("OLLAMA_API_KEY",),
        default_model="qwen2.5:3b",
        model_env="OLLAMA_MODEL",
        base_url_env="OLLAMA_BASE_URL",
        requires_key=False,
    ),
}


# Curated OpenRouter models that cost $0 AND support tool calling, which our
# agent needs. Ordered roughly most-capable-first so a chain of them degrades
# gracefully. OpenRouter's free lineup rotates; refresh with `factory models
# --refresh` (queries the live /models API) and update this list.
#
# The coding-focused ones are listed first: they are the best fit for the factory.
FREE_MODELS: tuple[str, ...] = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "cohere/north-mini-code:free",
    "recursive/flint-v1.0:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3.5-lightning:free",
    "dots-studio/dots-3-note-preview:free",
    "liquid/lfm-3-1.7b:free",
)

# `free` is a chain alias, not a provider: it expands to FREE_MODELS on the
# openrouter endpoint. Using it requires OPENROUTER_API_KEY.
FREE_ALIAS = "free"


@dataclass(frozen=True)
class ResolvedProvider:
    """A provider with its endpoint, model, and key resolved from the env."""

    provider: Provider
    base_url: str
    model: str
    api_key: str

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.provider.extra_headers)
        return headers

    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def resolve(name: str, *, model: str | None = None) -> ResolvedProvider | None:
    """Resolve one provider by name, or None when it is known but unconfigured."""
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"unknown LLM provider {name!r}; known: {sorted(PROVIDERS)}")
    key = _first_env(provider.key_envs)
    if provider.requires_key and not key:
        return None
    return ResolvedProvider(
        provider=provider,
        base_url=os.environ.get(provider.base_url_env, "").strip() or provider.base_url,
        model=(model or "").strip()
        or os.environ.get(provider.model_env, "").strip()
        or provider.default_model,
        api_key=key or "not-needed",
    )


def resolve_chain(spec: str | None = None) -> list[ResolvedProvider]:
    """Return the ordered, configured providers from a chain spec.

    The special step ``free`` (optionally ``free:3`` to cap the count) expands to
    FREE_MODELS on the OpenRouter endpoint, so ``free,ollama`` gives a no-cost
    chain with a local fallback.
    """
    raw = spec if spec is not None else os.environ.get("FACTORY_LLM_CHAIN", DEFAULT_CHAIN)
    chain: list[ResolvedProvider] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        name, _, model = item.partition(":")
        name, model = name.strip(), model.strip()

        if name == FREE_ALIAS:
            limit = int(model) if model.isdigit() else len(FREE_MODELS)
            openrouter = resolve("openrouter")
            if openrouter is None:
                continue  # no key -> the whole free group is unavailable
            for free_model in FREE_MODELS[:limit]:
                chain.append(_with_model(openrouter, free_model))
            continue

        resolved = resolve(name, model=model or None)
        if resolved is not None:
            chain.append(resolved)
    return chain


def _with_model(base: ResolvedProvider, model: str) -> ResolvedProvider:
    return ResolvedProvider(
        provider=base.provider,
        base_url=base.base_url,
        model=model,
        api_key=base.api_key,
    )


def available(spec: str | None = None) -> list[str]:
    """Names of the configured providers, in chain order."""
    return [p.name for p in resolve_chain(spec)]
