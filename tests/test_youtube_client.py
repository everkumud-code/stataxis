import httpx

from collector.youtube import client as youtube_client


def test_quota_error_keeps_api_reason_without_credentials(monkeypatch) -> None:
    class FakeBudget:
        def acquire(self):
            return None

    class FakeHTTPClient:
        def get(self, url, params):
            return httpx.Response(
                403,
                json={
                    "error": {
                        "errors": [{
                            "reason": "quotaExceeded",
                            "message": "https://user:secret@example.test/path?key=private",
                        }]
                    }
                },
                request=httpx.Request("GET", url, params=params),
            )

    monkeypatch.setattr(youtube_client, "DEFAULT_BUDGET", FakeBudget())
    client = youtube_client.YouTubeClient(api_key="private-key")
    client.client = FakeHTTPClient()

    try:
        try:
            client.get_channel("UC-test")
        except youtube_client.YouTubeAPIError as exc:
            message = str(exc)
            assert exc.status_code == 403
            assert "quotaExceeded" in message
            assert len("quotaExceeded") <= 100
            assert "private-key" not in message
            assert "https://" not in message
            assert "user:secret" not in message
        else:
            raise AssertionError("403 did not raise YouTubeAPIError")
    finally:
        client.close()
