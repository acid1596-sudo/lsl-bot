import pytest

from lslbot.providers.base import Provider, ProviderError, UsageExhaustedError
from lslbot.router import FailoverRouter, RouterError


class FakeClock:
    def __init__(self, start=1_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeProvider(Provider):
    """A scripted provider: each call to generate() consumes the next entry
    in `script`, which is either a string (returned as the reply) or an
    exception instance (raised)."""

    def __init__(self, name, script):
        self.name = name
        self._script = list(script)
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        if not self._script:
            raise AssertionError(f"{self.name}.generate() called more times than scripted")
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def make_router(primaries, fallback, clock, **kwargs):
    return FailoverRouter(
        primary_providers=primaries,
        fallback_provider=fallback,
        default_cooldown=kwargs.pop("default_cooldown", 10.0),
        max_cooldown=kwargs.pop("max_cooldown", 100.0),
        backoff_multiplier=kwargs.pop("backoff_multiplier", 2.0),
        clock=clock,
        **kwargs,
    )


def test_primary_success_never_touches_fallback():
    clock = FakeClock()
    primary = FakeProvider("openai", ["hello there"])
    fallback = FakeProvider("ollama", [])  # any call here fails the test

    router = make_router([primary], fallback, clock)
    result = router.generate([{"role": "user", "content": "hi"}])

    assert result.text == "hello there"
    assert result.provider == "openai"
    assert result.handover is False
    assert fallback.calls == 0


def test_usage_exhausted_hands_over_and_hands_back():
    clock = FakeClock()
    primary = FakeProvider(
        "openai",
        [UsageExhaustedError("rate limited", retry_after=30.0), "back on openai"],
    )
    fallback = FakeProvider("ollama", ["local reply", "local reply 2"])
    router = make_router([primary], fallback, clock)

    # First call: openai is exhausted, ollama picks up the task.
    result = router.generate([{"role": "user", "content": "1"}])
    assert result.provider == "ollama"
    assert result.handover is True
    assert "usage exhausted" in result.attempts[0]

    status = router.status()
    assert status["providers"]["openai"]["available"] is False
    assert status["providers"]["openai"]["retry_in_seconds"] == pytest.approx(30.0, abs=0.01)
    assert status["active_provider"] == "ollama"

    # Still within the 30s cooldown: stays on ollama, openai.generate() not retried.
    clock.advance(29.0)
    result = router.generate([{"role": "user", "content": "2"}])
    assert result.provider == "ollama"
    assert primary.calls == 1

    # Cooldown has now elapsed: the very next task goes back to openai automatically.
    clock.advance(1.5)
    result = router.generate([{"role": "user", "content": "3"}])
    assert result.provider == "openai"
    assert result.text == "back on openai"
    assert result.handover is False

    status = router.status()
    assert status["providers"]["openai"]["available"] is True
    assert status["active_provider"] == "openai"


def test_backoff_escalates_when_no_retry_after_is_given():
    clock = FakeClock()
    primary = FakeProvider(
        "openai",
        [
            UsageExhaustedError("quota exceeded"),  # no retry_after -> default_cooldown (10s)
            UsageExhaustedError("quota exceeded"),  # still exhausted -> 10 * 2 = 20s
            UsageExhaustedError("quota exceeded"),  # still exhausted -> 20 * 2 = 40s
            "recovered",
        ],
    )
    fallback = FakeProvider("ollama", ["f1", "f2", "f3"])
    router = make_router([primary], fallback, clock, default_cooldown=10.0, backoff_multiplier=2.0, max_cooldown=100.0)

    router.generate([])  # -> exhausted, cooldown = 10s
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(10.0)

    clock.advance(10.0)
    router.generate([])  # -> exhausted again, cooldown = 20s
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(20.0)

    clock.advance(20.0)
    router.generate([])  # -> exhausted again, cooldown = 40s
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(40.0)

    clock.advance(40.0)
    result = router.generate([])  # -> recovers, hands back
    assert result.provider == "openai"
    assert result.text == "recovered"


def test_backoff_is_capped_at_max_cooldown():
    clock = FakeClock()
    primary = FakeProvider(
        "openai",
        [UsageExhaustedError("x") for _ in range(4)],
    )
    fallback = FakeProvider("ollama", ["f"] * 4)
    router = make_router([primary], fallback, clock, default_cooldown=10.0, backoff_multiplier=10.0, max_cooldown=25.0)

    router.generate([])  # 10s
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(10.0)
    clock.advance(10.0)

    router.generate([])  # min(10*10, 25) = 25s
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(25.0)
    clock.advance(25.0)

    router.generate([])  # min(25*10, 25) = 25s, stays capped
    assert router.status()["providers"]["openai"]["retry_in_seconds"] == pytest.approx(25.0)


def test_falls_through_priority_chain_before_using_fallback():
    clock = FakeClock()
    primary_a = FakeProvider("openai", [UsageExhaustedError("out", retry_after=60.0)])
    primary_b = FakeProvider("anthropic", ["claude reply"])
    fallback = FakeProvider("ollama", [])

    router = make_router([primary_a, primary_b], fallback, clock)
    result = router.generate([])

    assert result.provider == "anthropic"
    assert result.handover is False
    assert fallback.calls == 0
    assert any("openai" in a and "usage exhausted" in a for a in result.attempts)


def test_generic_provider_error_does_not_start_a_cooldown():
    clock = FakeClock()
    primary = FakeProvider("openai", [ProviderError("temporary network blip"), "fine now"])
    fallback = FakeProvider("ollama", ["local"])
    router = make_router([primary], fallback, clock)

    result = router.generate([])
    assert result.provider == "ollama"  # this call still needed to fail over...

    # ...but a plain ProviderError shouldn't blacklist the provider, so the
    # very next call retries it immediately rather than waiting out a cooldown.
    result = router.generate([])
    assert result.provider == "openai"
    assert result.text == "fine now"


def test_all_providers_failing_raises_router_error():
    clock = FakeClock()
    primary = FakeProvider("openai", [ProviderError("down")])
    fallback = FakeProvider("ollama", [ProviderError("also down")])
    router = make_router([primary], fallback, clock)

    with pytest.raises(RouterError):
        router.generate([])


def test_state_persists_across_router_restarts(tmp_path):
    state_path = str(tmp_path / "state.json")
    clock = FakeClock()

    primary = FakeProvider("openai", [UsageExhaustedError("out", retry_after=120.0)])
    fallback = FakeProvider("ollama", ["local-1"])
    router = make_router([primary], fallback, clock, state_path=state_path)
    result = router.generate([])
    assert result.provider == "ollama"

    # A fresh router instance (simulating a process restart) reads the same
    # state file and must not call the still-cooling-down primary again.
    primary_after_restart = FakeProvider("openai", [])  # any call fails the test
    fallback_after_restart = FakeProvider("ollama", ["local-2"])
    restarted_router = make_router(
        [primary_after_restart], fallback_after_restart, clock, state_path=state_path
    )
    result = restarted_router.generate([])
    assert result.provider == "ollama"
    assert primary_after_restart.calls == 0

    status = restarted_router.status()
    assert status["providers"]["openai"]["retry_in_seconds"] == pytest.approx(120.0)
