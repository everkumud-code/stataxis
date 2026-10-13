"""The feed-list importer: exact handles, a name check on what YouTube returns, nothing renamed, and the worker tracks database-only channels."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from collector import feed_importer as fi
from collector import service
from collector.storage import Base, Channel
from collector.youtube.collector import ChannelTarget
from metrics.markets import SEGMENTS, market_label


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class FakeYT:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def resolve_channel_url(self, url):
        self.calls.append(url)
        ref = url.rsplit("/", 1)[-1]
        if ref not in self.table:
            raise RuntimeError("Channel not found")
        cid, title = self.table[ref]
        return {"id": cid, "snippet": {"title": title}}


def test_the_shipped_list_is_complete_and_every_category_is_known():
    feeds = fi.load_feeds()
    assert len(feeds) == 166
    for item in feeds:
        info = fi.classify(item["category"], item["name"])
        assert info["segment"] in SEGMENTS and info["language"] and info["region"]
        assert item["ref"].startswith("@") or item["ref"].startswith("channel/")
    assert {i["category"] for i in feeds} == set(fi.CATEGORY)
    assert market_label("brand", "Hindi") == "Brands & Entertainment"


def test_languages_and_regions_follow_the_list_with_the_known_exceptions():
    assert fi.classify("Business", "CNBC Awaaz")["language"] == "Hindi"
    assert fi.classify("Business", "ET Now")["language"] == "English"
    assert fi.classify("Bangla", "Somoy TV")["region"] == "Bangladesh"
    assert fi.classify("Europe", "WELT")["language"] == "German"
    assert fi.classify("Politicians (Top 10)", "Narendra Modi")["segment"] == "leader"
    assert fi.classify("Brands (Top 10)", "T-Series")["segment"] == "brand"
    with pytest.raises(ValueError):
        fi.classify("Weather", "X")


def test_a_handle_that_belongs_to_someone_else_is_not_registered():
    assert fi.title_matches("Aaj Tak", "Aaj Tak")
    assert fi.title_matches("MS NOW (MSNBC)", "MS NOW")
    assert fi.title_matches("ABP Live", "ABP LIVE")
    assert not fi.title_matches("Aaj Tak", "Random Gaming Clips")


def test_import_adds_matches_skips_mismatches_and_failures_and_leaves_existing_channels_alone(session):
    session.add(Channel(youtube_channel_id="UC_known", name="Curated Name", network="Curated", language="Hindi", region="India", segment="news"))
    session.commit()
    yt = FakeYT({"@aajtak": ("UC_aaj", "Aaj Tak"), "@zeenews": ("UC_known", "Zee News"), "@fake": ("UC_fake", "Totally Different Thing"), "@dup": ("UC_dup", "Dup Channel")})
    feeds = [{"category": "Hindi", "name": "Aaj Tak", "ref": "@aajtak"}, {"category": "Hindi", "name": "Zee News", "ref": "@zeenews"},
             {"category": "Hindi", "name": "Wrong Handle", "ref": "@fake"}, {"category": "Hindi", "name": "Missing", "ref": "@gone"},
             {"category": "Journalists (Top 30)", "name": "Dup Channel", "ref": "@dup"}, {"category": "Hindi", "name": "Dup Channel", "ref": "@DUP"}]
    check = fi.import_feeds(session, yt, feeds, apply=False)
    assert session.query(Channel).count() == 1 and [a["name"] for a in check["added"]] == ["Aaj Tak", "Dup Channel"]
    done = fi.import_feeds(session, yt, feeds, apply=True)
    assert [a["name"] for a in done["added"]] == ["Aaj Tak", "Dup Channel"]
    assert done["already_tracked"][0]["name"] == "Curated Name" and len(done["mismatched"]) == 1 and len(done["failed"]) == 1 and len(done["duplicates"]) == 1
    assert all(c.startswith("https://www.youtube.com/@") for c in yt.calls)
    kept = session.query(Channel).filter_by(youtube_channel_id="UC_known").one()
    assert kept.name == "Curated Name" and kept.network == "Curated"
    aaj = session.query(Channel).filter_by(youtube_channel_id="UC_aaj").one()
    assert (aaj.segment, aaj.language, aaj.region, aaj.handle, aaj.active) == ("news", "Hindi", "India", "@aajtak", True)
    assert session.query(Channel).filter_by(youtube_channel_id="UC_dup").one().segment == "journalist"


def test_the_worker_tracks_channels_that_live_only_in_the_database(session):
    session.add_all([Channel(youtube_channel_id="UC_a", name="A", network="n", language="Hindi", region="India", segment="news", active=True),
                     Channel(youtube_channel_id="UC_b", name="B", network="n", language="English", region="US", segment="brand", active=True),
                     Channel(youtube_channel_id="UC_off", name="Off", network="n", language="Hindi", region="India", segment="news", active=False)])
    session.commit()
    configured = [ChannelTarget(channel_id="UC_a", name="A", language="Hindi", network="n", segment="news")]
    merged = service._with_database_channels(session, configured)
    assert [t.channel_id for t in merged] == ["UC_a", "UC_b"] and merged[1].segment == "brand"
