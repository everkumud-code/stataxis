# Facebook, Instagram and X in StatAxis

Public figures of the Facebook pages, Instagram accounts and X accounts that belong to the tracked channels, set beside YouTube. Read through each platform's **official API** or taken from a **sheet**. Nothing is scraped.

## What it does

| Part | Where |
|---|---|
| Rankings per platform (followers, growth, engagement rate) | workspace → Social media → Rankings (`/api/v1/social/overview`) |
| Every channel on one row: YouTube + the three platforms + STX | Beside YouTube (`/presence`) |
| One channel in depth, several channels compared | One channel (`/channel`, `/compare`) |
| Best posts | Top posts (`/posts`) |
| Excel file (data-export privilege) | `/api/v1/social/export.xlsx` |
| PDF and picture card of any screen | the report bar under each screen |
| Social part of the e-mailed periodic reports | the "Social media" section in Report e-mails |
| Setup (admin only) | Channels and data → Social media setup (`/api/v1/social/admin/*`) |

The screens are the privilege `social` (SX Intelligence and above by default, changeable per package and per person). The STX Index and the IFX Score still use YouTube data only; the social figures sit beside them.

## How the data gets in

* `collector/social/connectors.py` has one connector per platform. A pass of the collector's job thread (`collector/jobs.py`, every 10 minutes) reads at most 40 due accounts; an account is read again after the interval set in the admin screen (6 hours by default). X is limited per pass (X charges per read).
* `collector/social/service.py` stores one reading of each account (`stx_social_stats`) and the latest 25 posts with what each had gathered (`stx_social_posts`, `stx_social_post_stats`). A figure a platform does not give is stored empty, never zero.
* Sheets (admin screen): accounts (`channel, platform, handle`), follower figures (`platform, handle, date, followers[, following, posts]`), posts (`platform, handle, post_id, posted_at, text, permalink, likes, comments, shares, views`). Rows that fail are listed with the reason; the rest are kept.
* A single follower figure can be typed in from the accounts table ("Add a figure").

## Keys (never typed by anyone but the administrator, kept on the server, shown as the last four characters)

| Platform | What is needed | Notes |
|---|---|---|
| Instagram | Meta access token + the id of an Instagram professional account | Business Discovery reads only **business and creator** accounts (followers, accounts followed, posts; likes and comments of the latest posts). |
| Facebook | the same Meta access token | Page followers work with a normal token; reading **other pages' posts** needs Meta's *Page Public Content Access* feature (app review). Without it the followers still arrive and posts do not. |
| X | a bearer token (paid X API plan) | followers, accounts followed, post count, likes, replies, reposts and views where X gives them. |

Environment overrides: `STAXIS_META_TOKEN`, `STAXIS_META_IG_USER_ID`, `STAXIS_X_BEARER_TOKEN`. Without a key an account shows "no key yet" and nothing is lost.

## Honest edges

* Reach and impressions are not public on any of the three platforms. The engagement rate is *(likes + comments + shares) per post as a percentage of followers*: how many people reacted, not how many saw. Under 5 posts with figures it is marked low-confidence.
* Growth needs two readings at least one day apart; a history shorter than the period shows the span actually used.
* "Social followers" add the platforms together and count a person who follows on two platforms twice.
* Keeping: figures for at most 36 calendar months; a post's text and link are cleared when the platform has not given them again within 30 days (`collector/social/retention.py`, hourly from the job thread).
* Methodology page and changelog (`api/methodology.py`) describe this; add an entry whenever a formula changes.

## Tests

`tests/test_social.py` (connectors against invented platform answers, reading and storing, sheets, growth and engagement, routes and privileges, keeping rules, the demo's invented accounts, the report part).
