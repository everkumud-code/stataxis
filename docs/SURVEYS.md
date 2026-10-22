# Polls and surveys

Run opinion polls, political polls, brand polls and full surveys from the workspace (menu group **Polls and surveys**, administrators only). People answer on a public page, anonymously by default.

## Where things are

| Part | File |
|---|---|
| Tables `stx_surveys`, `stx_survey_responses`, `stx_survey_invites`, `stx_survey_revisions` | `collector/storage.py` |
| Definition, answer checks, duplicates, results, exports, starters | `api/survey_core.py` |
| Admin routes `/api/v1/surveys/...`, public routes `/api/v1/public/survey/<slug>`, pages | `api/survey_http.py` |
| The respondent page, results page, Polls list | `api/survey_pages.py` |
| Admin screen (builder, settings, share, results, answers) | `dashboard/surveys.js` |
| Tests | `tests/test_surveys.py` |

## Public addresses

`/survey/<slug>` (answer), `/survey/<slug>/results` (when allowed), `/polls` (open polls marked "show on the Polls page"). Unlisted surveys are `noindex`; drafts are 404.

## How a survey is built

Question types: one choice, many choices (with a limit and an "alone" option), dropdown, rating (3 to 10), recommend 0 to 10 (NPS), number, short text, long text, ranking, heading. Options can be "other (write in)". A question can be shown only if an earlier answer matches. Options can be shown in random order. Starters: quick poll, political poll, brand awareness, customer satisfaction/NPS, team pulse, media habits; "age, gender, area, state" can be added to any survey.

Every question and option has a stable id (q1, o1). Once answers exist nothing that holds an answer can be deleted or change type: it is archived (hidden from new respondents, kept in the results).

## Honesty and privacy rules

- Answers are anonymous. Contact details are asked only when the survey says so, with a consent text people must tick; they are stored apart from the answers and leave only in an export where "include contact details" is ticked.
- No address is stored. A device mark is a salted hash tied to one survey; it only flags "same device within a day". A random token kept in the browser stops a second answer (unless "allow several answers from one device").
- Results always say how many answered. Self-selected and panel results carry **no margin of error**; only a survey declared "random sample" shows one (95%, with the finite-population correction when the population size is given).
- Public results need a setting other than private, at least the chosen number of answers, show only choice/rating/score questions (never written answers, contact details or splits), and a **hold** switch turns every public result off at once.
- Political polls show a notice about sections 126 and 126A of the Representation of the People Act, 1951 (opinion-poll publication before polling ends, exit polls): check the Election Commission's current directions before publishing. Results can carry "who paid for it" and a method note.
- Bots: a hidden field catches simple ones (they are told "ok", nothing stored), answers are rate-limited per connection, and very fast answers are flagged. Flagged answers can be counted or removed in the Answers tab.
- Exports (CSV with a BOM for Excel, and Excel) neutralise cells that start with = + - @.

## Invitation-only surveys

Make personal links (one per name or a number of them). Each works once; only a hash of each code is kept, so the links can be downloaded only at the moment they are made.
