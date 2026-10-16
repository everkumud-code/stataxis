"""The three platform connectors. Each reads only what the platform's own official API gives for a public account, with the key an administrator saved
(Facebook and Instagram: a Meta access token, plus the id of an Instagram professional account for Instagram; X: a bearer token). Nothing is scraped.

What the platforms give (and so what StatAxis can show):
  Instagram  Business Discovery: followers, accounts followed, number of posts, and for the latest posts the likes and comments. Only business and creator accounts can be read; a personal account is refused.
  Facebook   Pages: followers and, for the latest posts, reactions, comments and shares. Reading a page you do not manage needs Meta's "Page Public Content Access" feature; without it the page figures
             may still arrive and the posts do not.
  X          API v2: followers, accounts followed, number of posts and, for the latest posts, likes, replies, reposts and (where X gives it) views. X's API is paid.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from collector.social.base import (AccountSnapshot, Fetched, Opener, PostSnapshot, SocialError, clip, http_json, parse_time, quote, to_int)

GRAPH = "https://graph.facebook.com/v21.0"
X_API = "https://api.twitter.com/2"
POST_LIMIT = 25


@dataclass
class Credentials:
    meta_token: str = ""
    meta_ig_user_id: str = ""
    x_bearer: str = ""


def _need(value: str, what: str) -> str:
    if not value:
        raise SocialError("not_configured", f"no {what} is saved yet (an administrator adds it under Social media setup)")
    return value


class Instagram:
    platform = "instagram"

    def __init__(self, creds: Credentials, opener: Opener | None = None):
        self.creds, self.opener = creds, opener

    def ready(self) -> bool:
        return bool(self.creds.meta_token and self.creds.meta_ig_user_id)

    def fetch(self, handle: str, external_id: str | None = None) -> Fetched:
        token, owner = _need(self.creds.meta_token, "Meta access token"), _need(self.creds.meta_ig_user_id, "Instagram account id")
        fields = (f"business_discovery.username({handle}){{username,name,followers_count,follows_count,media_count,"
                  f"media.limit({POST_LIMIT}){{id,caption,media_type,permalink,timestamp,like_count,comments_count}}}}")
        data = http_json(f"{GRAPH}/{quote(owner)}?" + urllib.parse.urlencode({"fields": fields, "access_token": token}), opener=self.opener)
        bd = data.get("business_discovery")
        if not isinstance(bd, dict):
            raise SocialError("unsupported", "Instagram gave nothing for this account: only business and creator accounts can be read")
        posts = []
        for m in ((bd.get("media") or {}).get("data") or []):
            if not m.get("id"):
                continue
            posts.append(PostSnapshot(post_id=str(m["id"]), posted_at=parse_time(m.get("timestamp")), text=clip(m.get("caption")), permalink=m.get("permalink"), media_type=str(m.get("media_type") or "").lower() or None,
                                      likes=to_int(m.get("like_count")), comments=to_int(m.get("comments_count"))))
        return Fetched(AccountSnapshot(followers=to_int(bd.get("followers_count")), following=to_int(bd.get("follows_count")), posts_total=to_int(bd.get("media_count")),
                                       display_name=bd.get("name") or bd.get("username"), external_id=str(bd.get("id")) if bd.get("id") else None, url=f"https://www.instagram.com/{handle}/"), posts)


class Facebook:
    platform = "facebook"

    def __init__(self, creds: Credentials, opener: Opener | None = None):
        self.creds, self.opener = creds, opener

    def ready(self) -> bool:
        return bool(self.creds.meta_token)

    def fetch(self, handle: str, external_id: str | None = None) -> Fetched:
        token = _need(self.creds.meta_token, "Meta access token")
        page = http_json(f"{GRAPH}/{quote(external_id or handle)}?" + urllib.parse.urlencode({"fields": "id,name,fan_count,followers_count,link", "access_token": token}), opener=self.opener)
        page_id = str(page.get("id") or external_id or handle)
        account = AccountSnapshot(followers=to_int(page.get("followers_count", page.get("fan_count"))), display_name=page.get("name"), external_id=page_id, url=page.get("link") or f"https://www.facebook.com/{handle}")
        posts: list[PostSnapshot] = []
        try:
            feed = http_json(f"{GRAPH}/{quote(page_id)}/posts?" + urllib.parse.urlencode({
                "fields": "id,created_time,message,permalink_url,shares,reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)", "limit": POST_LIMIT, "access_token": token}), opener=self.opener)
            for p in feed.get("data") or []:
                if not p.get("id"):
                    continue
                posts.append(PostSnapshot(post_id=str(p["id"]), posted_at=parse_time(p.get("created_time")), text=clip(p.get("message")), permalink=p.get("permalink_url"), media_type="post",
                                          likes=to_int(((p.get("reactions") or {}).get("summary") or {}).get("total_count")), comments=to_int(((p.get("comments") or {}).get("summary") or {}).get("total_count")),
                                          shares=to_int((p.get("shares") or {}).get("count"))))
        except SocialError as exc:
            if exc.code not in ("unsupported", "not_found"):
                raise      # a refused key or a rate limit is told to the administrator; a page whose posts the key may not read still gives its followers
        return Fetched(account, posts)


class X:
    platform = "x"

    def __init__(self, creds: Credentials, opener: Opener | None = None):
        self.creds, self.opener = creds, opener

    def ready(self) -> bool:
        return bool(self.creds.x_bearer)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return http_json(f"{X_API}{path}?" + urllib.parse.urlencode(params), headers={"Authorization": "Bearer " + _need(self.creds.x_bearer, "X bearer token")}, opener=self.opener)

    def fetch(self, handle: str, external_id: str | None = None) -> Fetched:
        user = (self._get(f"/users/by/username/{quote(handle)}", {"user.fields": "public_metrics,name,verified"}).get("data")) or {}
        if not user.get("id"):
            raise SocialError("not_found", "X does not know this account (check the handle)")
        pm = user.get("public_metrics") or {}
        account = AccountSnapshot(followers=to_int(pm.get("followers_count")), following=to_int(pm.get("following_count")), posts_total=to_int(pm.get("tweet_count")), display_name=user.get("name"),
                                  external_id=str(user["id"]), url=f"https://x.com/{handle}")
        posts: list[PostSnapshot] = []
        timeline = self._get(f"/users/{quote(str(user['id']))}/tweets", {"max_results": max(5, POST_LIMIT), "exclude": "retweets,replies", "tweet.fields": "created_at,public_metrics"})
        for t in timeline.get("data") or []:
            m = t.get("public_metrics") or {}
            shares = (to_int(m.get("retweet_count")) or 0) + (to_int(m.get("quote_count")) or 0) if ("retweet_count" in m or "quote_count" in m) else None
            posts.append(PostSnapshot(post_id=str(t["id"]), posted_at=parse_time(t.get("created_at")), text=clip(t.get("text")), permalink=f"https://x.com/{handle}/status/{t['id']}", media_type="post",
                                      likes=to_int(m.get("like_count")), comments=to_int(m.get("reply_count")), shares=shares, views=to_int(m.get("impression_count"))))
        return Fetched(account, posts)


def connectors(creds: Credentials, opener: Opener | None = None) -> dict[str, Any]:
    return {"instagram": Instagram(creds, opener), "facebook": Facebook(creds, opener), "x": X(creds, opener)}
