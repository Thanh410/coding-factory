"""Blank env vars must behave like unset ones.

GitHub Actions passes an empty string for an undeclared ``vars.*`` entry. Before
the fix, code that parsed such a value directly crashed (``int("")``) or silently
erased a default (e.g. the spec stage turned off, or the Sentry base URL became
empty). These tests pin the blank-tolerant behaviour.
"""

from __future__ import annotations

import pytest

from factory.config import ConfigError, Settings, int_env, str_env


def test_int_env_treats_blank_as_default(monkeypatch):
    monkeypatch.setenv("FACTORY_TEST_INT", "")
    assert int_env("FACTORY_TEST_INT", 7) == 7
    monkeypatch.setenv("FACTORY_TEST_INT", "  ")
    assert int_env("FACTORY_TEST_INT", 7) == 7
    monkeypatch.delenv("FACTORY_TEST_INT")
    assert int_env("FACTORY_TEST_INT", 7) == 7
    monkeypatch.setenv("FACTORY_TEST_INT", "12")
    assert int_env("FACTORY_TEST_INT", 7) == 12


def test_int_env_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("FACTORY_TEST_INT", "abc")
    with pytest.raises(ConfigError):
        int_env("FACTORY_TEST_INT", 7)


def test_str_env_treats_blank_as_default(monkeypatch):
    monkeypatch.setenv("FACTORY_TEST_STR", "")
    assert str_env("FACTORY_TEST_STR", "fallback") == "fallback"
    monkeypatch.setenv("FACTORY_TEST_STR", "   ")
    assert str_env("FACTORY_TEST_STR", "fallback") == "fallback"
    monkeypatch.delenv("FACTORY_TEST_STR")
    assert str_env("FACTORY_TEST_STR", "fallback") == "fallback"
    monkeypatch.setenv("FACTORY_TEST_STR", "value")
    assert str_env("FACTORY_TEST_STR", "fallback") == "value"


def test_blank_bool_env_keeps_default_on(monkeypatch):
    # A blank FACTORY_SPEC_STAGE must NOT silently disable the default-on pass.
    monkeypatch.setenv("FACTORY_SPEC_STAGE", "")
    assert Settings.from_env().spec_stage is True
    monkeypatch.setenv("FACTORY_SPEC_STAGE", "false")
    assert Settings.from_env().spec_stage is False


def test_blank_base_branch_keeps_default(monkeypatch):
    monkeypatch.setenv("FACTORY_BASE_BRANCH", "")
    assert Settings.from_env().base_branch == "main"
    monkeypatch.setenv("FACTORY_MERGE_METHOD", "")
    assert Settings.from_env().merge_method == "squash"


def test_blank_monitor_ints_do_not_crash(monkeypatch):
    # Reproduces the CI failure: Actions passes "" for undeclared monitor vars.
    from factory.monitor import MonitorConfig

    monkeypatch.setenv("SENTRY_LIMIT", "")
    monkeypatch.setenv("UPTIME_EXPECT_STATUS", "")
    monkeypatch.setenv("UPTIME_TIMEOUT", "")
    cfg = MonitorConfig.from_env()
    assert cfg.sentry_limit == 10
    assert cfg.uptime_expect == 200
    assert cfg.uptime_timeout == 10


def test_blank_monitor_strings_keep_defaults(monkeypatch):
    from factory.monitor import MonitorConfig

    monkeypatch.setenv("SENTRY_BASE_URL", "")
    monkeypatch.setenv("SENTRY_QUERY", "")
    monkeypatch.setenv("SENTRY_STATS_PERIOD", "")
    monkeypatch.setenv("FACTORY_MONITOR_LABEL", "")
    cfg = MonitorConfig.from_env()
    assert cfg.sentry_base == "https://sentry.io"
    assert cfg.sentry_query == "is:unresolved"
    assert cfg.sentry_period == "24h"
    assert cfg.label == "factory"
