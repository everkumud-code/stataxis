import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from collector import candidate_importer, channel_registry, service
from collector.quota_estimate import affordable_collect_seconds, estimate_daily_units, quota_warning
from collector.resolve_candidates import approve, rank_suggestions, resolve_pending
from collector.storage import create_database
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget
from metrics.markets import SEGMENTS

ROOT = Path(__file__).resolve().parents[1]


def test_large_universe_is_one_pass_and_live_polling_runs_on_its_own_thread(monkeypatch):
    """Collection covers the whole channel list in one batched pass; live polling is never starved
    because it runs in a separate thread (no slicing needed)."""
    monkeypatch.setenv("COLLECT_SECONDS", "600")
    monkeypatch.setenv("LIVE_POLL_SECONDS", "30")
    stop = Event()
    collection_started = Event()
    release_collection = Event()
    loads, passes, live_calls = [], [], []

    class FakeClient:
        reserve_per_minute = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def fake_load(path):
        loads.append(path)
        return [ChannelTarget(f"UC-{index}", f"Channel {index}") for index in range(25)]

    def fake_collection(session, client, targets, **kwargs):
        passes.append((len(targets), kwargs.get("intelligence", True)))
        collection_started.set()
        release_collection.wait(5)  # a slow pass
        return SimpleNamespace(videos_observed=0, channel_errors=0, intelligence=SimpleNamespace(snapshots_built=0, errors=0))

    def fake_live(*a, **k):
        collection_started.wait(5)
        live_calls.append(1)  # ran while the collection pass was still in progress
        release_collection.set()
        stop.set()
        return service.LivePollResult(0, 0, 0, 0, 0)

    monkeypatch.setattr(service, "create_database", lambda url: create_database("sqlite://"))
    monkeypatch.setattr(service, "load_targets", fake_load)
    monkeypatch.setattr(service, "run_collection_pass", fake_collection)
    monkeypatch.setattr(service, "poll_live_once", fake_live)
    monkeypatch.setattr(service, "install_signal_handlers", lambda event: None)
    service.run_service("sqlite://", client_factory=FakeClient, stop_event=stop)

    assert passes == [(25, True)]  # all 25 channels in one pass, scored once
    assert len(loads) == 1
    assert live_calls


def test_quota_estimates_and_warning():
    small = estimate_daily_units(5, 600, 30)
    assert small == {"collection": 2160, "live": 2880, "total": 5040}
    assert quota_warning(5, 600, 30) is None
    big = estimate_daily_units(60, 600, 30)
    assert big["collection"] == 25_920 and big["live"] == 5_760
    assert affordable_collect_seconds(60, 30, quota=10_000) == 5676
    warning = quota_warning(60, 600, 30)
    assert "COLLECT_SECONDS to 5676" in warning and "31680" in warning
    assert affordable_collect_seconds(500, 30, quota=10_000) is None
    assert "live polling alone exceeds" in quota_warning(500, 600, 30)
    with pytest.raises(ValueError):
        estimate_daily_units(5, 0, 30)


def test_quota_can_be_configured(monkeypatch):
    monkeypatch.setenv("STAXIS_YOUTUBE_DAILY_QUOTA_UNITS", "1000000")
    assert quota_warning(60, 600, 30) is None
    monkeypatch.setenv("STAXIS_YOUTUBE_DAILY_QUOTA_UNITS", "junk")
    assert quota_warning(60, 600, 30) is not None


class SearchClient:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search_channels(self, query, max_results=3):
        self.queries.append(query)
        return self.results.get(query, [])


def _candidate(name, **extra):
    return {"name": name, "language": "Hindi", "network": "Net", "segment": "news", "channel_id": "", "verification_status": "pending", **extra}


def test_resolver_ranks_exact_titles_then_audience_and_never_registers():
    found = [
        {"channel_id": "UCfan", "title": "Zee News Fan Clips", "subscriber_count": 9_000_000},
        {"channel_id": "UCreal", "title": "Zee News", "subscriber_count": 500_000},
        {"channel_id": "UCsmall", "title": "Zee News Lite", "subscriber_count": 1_000},
    ]
    ranked = rank_suggestions("Zee News", found)
    assert [item["channel_id"] for item in ranked] == ["UCreal", "UCfan", "UCsmall"]
    assert ranked[0]["match"] == "exact" and ranked[1]["match"] == "similar"
    candidates = [_candidate("Zee News", network="Zee Media"), _candidate("Ghost Channel"), _candidate("Done", channel_id="UCdone", verification_status="registered")]
    client = SearchClient({"Zee News Zee Media": found})
    summary = resolve_pending(candidates, client)
    assert summary == {"searched": 2, "with_suggestions": 1, "not_found": 1, "quota_units": 200}
    assert candidates[0]["verification_status"] == "needs_review" and candidates[0]["channel_id"] == ""
    assert candidates[1]["verification_status"] == "not_found"
    assert len(client.queries) == 2  # the registered one was not searched
    assert resolve_pending(candidates, client, limit=5)["searched"] == 1  # only the not_found one is retried, needs_review is left for a human


def test_resolver_respects_the_search_limit_and_skips_already_suggested():
    candidates = [_candidate(f"C{index}") for index in range(5)]
    client = SearchClient({})
    assert resolve_pending(candidates, client, limit=2)["searched"] == 2
    assert len(client.queries) == 2


def test_approve_picks_a_suggestion_and_leaves_verification_to_the_importer():
    candidates = [_candidate("Zee News", suggestions=[{"channel_id": "UC1", "title": "Zee News", "match": "exact"},
                                                      {"channel_id": "UC2", "title": "Other", "match": "similar"}],
                             verification_status="needs_review")]
    chosen = approve(candidates, "zee news", pick=2)
    assert chosen["channel_id"] == "UC2" and chosen["verification_status"] == "pending"
    with pytest.raises(ValueError, match="pick must be between"):
        approve(candidates, "Zee News", pick=3)
    with pytest.raises(ValueError, match="exactly one candidate"):
        approve(candidates, "Nobody")


def test_registry_and_importer_carry_the_segment(tmp_path, monkeypatch):
    config = tmp_path / "channels.json"
    monkeypatch.setattr(channel_registry, "CONFIG_FILE", config)
    channel_registry.add_channel("UC1", "CNBC-TV18", "English", "Network18", segment="business")
    channel_registry.add_channel("UC2", "Plain", "Hindi", "Net")
    saved = json.loads(config.read_text())["channels"]
    assert saved[0]["segment"] == "business" and saved[1]["segment"] == "news"
    target = ChannelTarget(**saved[0])
    assert target.segment == "business"
    monkeypatch.setattr(candidate_importer, "CANDIDATES_FILE", tmp_path / "candidates.json")
    candidate_importer.save_candidates([{"name": "X", "language": "Hindi"}])
    assert candidate_importer.load_candidates()[0]["name"] == "X"


def test_candidate_file_is_well_formed_and_contains_no_invented_ids():
    candidates = json.loads((ROOT / "config" / "channel_candidates.json").read_text())["candidates"]
    names = [item["name"].strip().lower() for item in candidates]
    assert len(names) == len(set(names)), "duplicate candidate names"
    covered = {item.get("segment", "news") for item in candidates}
    assert {"news", "business", "print", "party", "leader", "commentator"} <= covered
    for item in candidates:
        assert item.get("segment", "news") in SEGMENTS, item["name"]
        assert item["language"] and item["network"], item["name"]
        if not item.get("channel_id"):
            assert item["verification_status"] == "pending", item["name"]
        else:
            # any ID present must already have been verified against the API by a previous run
            assert item["verification_status"] in {"registered", "verified"}, item["name"]
    known = {item["channel_id"] for item in json.loads((ROOT / "config" / "channels.json").read_text())["channels"]}
    assert known, "the registered universe must not be empty"


def test_client_search_channels_returns_ranked_ready_data(monkeypatch):
    client = YouTubeClient(api_key="k")
    calls = []

    def fake_get(resource, params):
        calls.append((resource, params))
        if resource == "search":
            return {"items": [{"snippet": {"channelId": "UC1"}}, {"id": {"channelId": "UC2"}}, {"snippet": {"channelId": "UC1"}}]}
        return {"items": [
            {"id": "UC1", "snippet": {"title": "One", "customUrl": "@one"}, "statistics": {"subscriberCount": "1200", "videoCount": "50"}},
            {"id": "UC2", "snippet": {"title": "Two"}, "statistics": {"hiddenSubscriberCount": True}},
        ]}

    monkeypatch.setattr(client, "_get", fake_get)
    found = client.search_channels("  Zee News ", max_results=99)
    assert [item["channel_id"] for item in found] == ["UC1", "UC2"]
    assert found[0]["subscriber_count"] == 1200 and found[1]["subscriber_count"] is None
    assert calls[0][1]["q"] == "Zee News" and calls[0][1]["maxResults"] == 10  # capped
    assert calls[1][1]["id"] == "UC1,UC2"  # duplicates removed, one batched lookup
    with pytest.raises(ValueError):
        client.search_channels("   ")
    client.close()
