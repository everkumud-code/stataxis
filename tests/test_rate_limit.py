import time

from api.rate_limit import SlidingWindowRateLimiter, client_ip


def test_sliding_window_limits_and_retry_after():
    rate = SlidingWindowRateLimiter()
    assert rate.check("x", 2, 60, now=100) == 0
    assert rate.check("x", 2, 60, now=101) == 0
    assert rate.check("x", 2, 60, now=102) > 0
    assert rate.check("x", 2, 60, now=161) == 0


def test_client_ip_uses_first_forwarded_hop():
    assert client_ip({"HTTP_X_FORWARDED_FOR": "203.0.113.10, 10.0.0.1", "REMOTE_ADDR": "127.0.0.1"}) == "203.0.113.10"
    assert client_ip({"REMOTE_ADDR": "198.51.100.7"}) == "198.51.100.7"
