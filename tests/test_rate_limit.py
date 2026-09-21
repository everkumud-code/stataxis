import time

from api.rate_limit import SlidingWindowRateLimiter, client_ip


def test_sliding_window_limits_and_retry_after():
    rate = SlidingWindowRateLimiter()
    assert rate.check("x", 2, 60, now=100) == 0
    assert rate.check("x", 2, 60, now=101) == 0
    assert rate.check("x", 2, 60, now=102) > 0
    assert rate.check("x", 2, 60, now=161) == 0


def test_client_ip_ignores_spoofable_leftmost_forwarded_entries(monkeypatch):
    monkeypatch.delenv("STAXIS_TRUSTED_PROXIES", raising=False)
    # A client-supplied value sits on the left; the trusted proxy appended the real peer on the right.
    forged = {"HTTP_X_FORWARDED_FOR": "1.2.3.4, 203.0.113.10", "REMOTE_ADDR": "10.0.0.1"}
    assert client_ip(forged) == "203.0.113.10"
    assert client_ip({"HTTP_X_FORWARDED_FOR": "203.0.113.10", "REMOTE_ADDR": "10.0.0.1"}) == "203.0.113.10"
    assert client_ip({"REMOTE_ADDR": "198.51.100.7"}) == "198.51.100.7"


def test_client_ip_trusted_proxy_count_is_configurable(monkeypatch):
    environ = {"HTTP_X_FORWARDED_FOR": "1.2.3.4, 203.0.113.10, 10.9.9.9", "REMOTE_ADDR": "10.0.0.1"}
    monkeypatch.setenv("STAXIS_TRUSTED_PROXIES", "2")
    assert client_ip(environ) == "203.0.113.10"
    monkeypatch.setenv("STAXIS_TRUSTED_PROXIES", "0")
    assert client_ip(environ) == "10.0.0.1"
    monkeypatch.setenv("STAXIS_TRUSTED_PROXIES", "garbage")
    assert client_ip(environ) == "10.9.9.9"


def test_limiter_memory_is_bounded_under_unique_key_flood():
    rate = SlidingWindowRateLimiter(max_keys=100)
    for index in range(1000):
        assert rate.check(f"login:1.2.3.4:user{index}@example.com", 10, 900, now=float(index) / 100) == 0
    assert len(rate._events) <= 100


def test_limiter_evicts_expired_keys_before_live_ones():
    rate = SlidingWindowRateLimiter(max_keys=3)
    rate.check("old-a", 1, 10, now=0)
    rate.check("old-b", 1, 10, now=0)
    rate.check("live", 1, 1000, now=0)
    rate.check("new", 1, 10, now=500)
    assert rate.check("live", 1, 1000, now=501) > 0
