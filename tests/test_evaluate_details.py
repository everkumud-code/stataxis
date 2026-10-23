"""The Evaluate screen shows the video's views, likes, comments, upload and live times and the channel's figures, even while the STX Index is still withheld."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from api.auth import AuthIdentity
from api.evaluate import evaluate_youtube_url
from collector.storage import create_database


UP = (datetime.now(UTC) - timedelta(hours=5)).replace(microsecond=0)
START = UP + timedelta(minutes=5)


class FakeYouTube:
    def __init__(self, views, likes, comments, viewers):
        self.stats = (views, likes, comments, viewers)

    def get_videos(self, ids):
        views, likes, comments, viewers = self.stats
        return [{"id": ids[0], "snippet": {"channelId": "UCfake", "title": "Real title", "publishedAt": UP.isoformat().replace("+00:00", "Z"), "categoryId": "25"},
                 "statistics": {"viewCount": str(views), "likeCount": str(likes), "commentCount": str(comments)},
                 "liveStreamingDetails": {"actualStartTime": START.isoformat().replace("+00:00", "Z"), "concurrentViewers": str(viewers)}}]

    def get_channel(self, channel_id):
        return {"snippet": {"title": "Fake Channel", "customUrl": "@fake", "publishedAt": "2015-01-01T00:00:00Z", "country": "IN"},
                "statistics": {"subscriberCount": "1200", "viewCount": "99000", "videoCount": "321"}}

    def close(self):
        pass


def test_details_are_given_on_the_first_look_and_the_movement_on_the_second(tmp_path: Path):
    engine = create_database(f"sqlite:///{tmp_path / 'e.db'}")
    admin = AuthIdentity(user_id=1, email="a@x.com", plan="sx_enterprise", is_admin=True)
    with Session(engine) as s:
        first = evaluate_youtube_url(s, admin, "https://youtu.be/dQw4w9WgXcQ", "Mine", client=FakeYouTube(1000, 50, 10, 400)).as_dict()
        assert first["stx_index"] is None                    # still withheld with one reading ...
        d = first["details"]                                 # ... but everything measured is shown
        assert (d["views"], d["likes"], d["comments"], d["concurrent_now"]) == (1000, 50, 10, 400)
        assert d["likes_per_100_views"] == 5.0 and d["comments_per_1000_views"] == 10.0
        assert d["is_live"] is True and d["live_started_at"] == START.isoformat() and 290 <= d["live_minutes"] <= 296
        assert d["uploaded_at"] == UP.isoformat() and 4.9 <= d["age_hours"] <= 5.1
        assert d["since_previous"] is None and d["youtube_url"].endswith("dQw4w9WgXcQ")
        assert d["channel"] == {**d["channel"], "name": "Fake Channel", "handle": "@fake", "subscribers": 1200, "total_views": 99000, "video_count": 321, "country": "IN"}
        second = evaluate_youtube_url(s, admin, "https://youtu.be/dQw4w9WgXcQ", "Mine", client=FakeYouTube(1600, 80, 15, 700)).as_dict()["details"]
        assert second["views"] == 1600 and second["concurrent_peak"] == 700 and second["since_previous"]["views_gained"] == 600
        assert second["since_previous"]["likes_gained"] == 30 and second["since_previous"]["comments_gained"] == 5


def test_a_figure_youtube_does_not_give_stays_empty_not_zero(tmp_path: Path):
    class Hidden(FakeYouTube):
        def get_videos(self, ids):
            v = super().get_videos(ids)
            v[0]["statistics"].pop("likeCount"); v[0].pop("liveStreamingDetails")
            return v

        def get_channel(self, channel_id):
            c = super().get_channel(channel_id)
            c["statistics"]["hiddenSubscriberCount"] = True
            return c

    engine = create_database(f"sqlite:///{tmp_path / 'h.db'}")
    admin = AuthIdentity(user_id=1, email="a@x.com", plan="sx_enterprise", is_admin=True)
    with Session(engine) as s:
        d = evaluate_youtube_url(s, admin, "https://youtu.be/dQw4w9WgXcQ", "Mine", client=Hidden(500, 0, 3, 0)).as_dict()["details"]
    assert d["likes"] is None and d["likes_per_100_views"] is None and d["concurrent_now"] is None and d["live_minutes"] is None
    assert d["channel"]["subscribers"] is None
