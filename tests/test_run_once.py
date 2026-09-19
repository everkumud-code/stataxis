from collector.intelligence import IntelligenceRunResult
from collector.run import CollectionPassResult
from collector import run_once


def test_run_once_returns_nonzero_without_database_url(monkeypatch, caplog):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("YOUTUBE_API_KEY", "secret-key")

    assert run_once.main() == 1
    assert "secret-key" not in caplog.text


def test_run_once_returns_zero_and_logs_counts(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.invalid/db")
    monkeypatch.setenv("YOUTUBE_API_KEY", "secret-key")

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "secret-key"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, _engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(run_once, "create_database", lambda _url: object())
    monkeypatch.setattr(run_once, "load_targets", lambda _path: [object(), object()])
    monkeypatch.setattr(run_once, "YouTubeClient", FakeClient)
    monkeypatch.setattr(run_once, "Session", FakeSession)
    monkeypatch.setattr(
        run_once,
        "run_collection_pass",
        lambda *_args, **_kwargs: CollectionPassResult(
            7, 12, IntelligenceRunResult(10, 9, 0)
        ),
    )

    assert run_once.main() == 0
    assert "collection cycle complete" in caplog.text
    assert "run_id=7" in caplog.text
    assert "secret-key" not in caplog.text
