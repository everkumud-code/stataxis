"""Online polls and surveys: how they are defined, how an answer is checked and stored, and how the results are worked out.

A survey is a list of questions with stable ids (q1, q2 ...) and, for choice questions, stable option ids (o1, o2 ...). Results are tied to those ids, never to the wording, so a typo can be corrected at any time.
Once answers exist a question or an option can no longer be deleted (it can be archived: hidden from new respondents, kept in the results) and a question's type cannot change.

Honest by construction: respondents are anonymous unless the survey asks for contact details (with a consent text); the device mark is a salted hash that cannot be turned back into an address; results say how many
answered and, unless the survey declares a random sample, that they are self-selected and carry no margin of error.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from collector.storage import Survey, SurveyImage, SurveyInvite, SurveyResponse, SurveyRevision

KINDS = ("poll", "survey")
CATEGORIES = ("opinion", "political", "brand", "customer", "employee", "media", "other")
STATUSES = ("draft", "review", "live", "closed")
ACCESS = ("public", "invite")
RESULTS_MODES = ("private", "after_vote", "public", "after_close")
SAMPLING = ("self_selected", "random_sample", "panel")
CONTACT_MODES = ("none", "optional", "required")
CONTACT_FIELDS = ("name", "mobile", "email")
TYPES = ("section", "single", "multi", "dropdown", "rating", "nps", "number", "text", "longtext", "ranking")
CHOICE = ("single", "multi", "dropdown", "ranking")
ANSWERED = ("single", "multi", "dropdown", "rating", "nps", "number", "text", "longtext", "ranking")
RESERVED = {"new", "results", "polls", "api", "admin"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_QUESTIONS, MAX_OPTIONS = 60, 60
MAX_DROPDOWN_OPTIONS = 500   # a dropdown is a list to search (the 75 districts of a state, the 403 constituencies), so it may be far longer than a list of buttons

STRINGS = {   # the words of the buttons and messages, by survey language; the questions are whatever the administrator writes
    "en": {"submit": "Submit", "next": "Next", "back": "Back", "required": "This question needs an answer.", "other": "Please say what", "thanks": "Thank you. Your answer has been recorded.", "closed": "This is closed.",
           "not_yet": "This has not opened yet.", "invite": "This survey is by invitation. Please use the link you were sent.", "already": "You have already answered this.", "consent": "I agree that my details may be used for this survey.",
           "results": "See the results", "select_up_to": "Choose up to", "one_per_rank": "Give each choice its own rank", "choose": "Choose…", "name": "Your name", "mobile": "Mobile number", "email": "E-mail",
           "progress": "Question", "last_step": "Last step: your name and mobile number", "dup_mobile": "This mobile number has already been used for this survey.", "of": "of", "powered": "Conducted by StatAxis", "cta_poll": "Take the poll", "cta_survey": "Take the survey", "live_poll": "Live now", "not_now": "Not now", "private_note": "Your answers are anonymous unless this survey asks for your contact details."},
    "hi": {"submit": "जमा करें", "next": "आगे", "back": "पीछे", "required": "इस प्रश्न का उत्तर ज़रूरी है।", "other": "कृपया बताएं", "thanks": "धन्यवाद। आपका उत्तर दर्ज हो गया है।", "closed": "यह बंद हो चुका है।",
           "not_yet": "यह अभी शुरू नहीं हुआ है।", "invite": "यह सर्वे केवल आमंत्रित लोगों के लिए है। कृपया भेजे गए लिंक का उपयोग करें।", "already": "आप इसका उत्तर पहले ही दे चुके हैं।",
           "consent": "मैं सहमत हूँ कि मेरी जानकारी इस सर्वे के लिए इस्तेमाल हो सकती है।", "results": "नतीजे देखें", "select_up_to": "अधिकतम चुनें", "one_per_rank": "हर विकल्प को अलग क्रम दें",
           "choose": "चुनें…", "name": "आपका नाम", "mobile": "मोबाइल नंबर", "email": "ई-मेल", "progress": "प्रश्न", "last_step": "अंतिम चरण: आपका नाम और मोबाइल नंबर", "dup_mobile": "इस मोबाइल नंबर से इस सर्वे में उत्तर पहले ही दिया जा चुका है।", "of": "में से", "powered": "स्टैटएक्सिस द्वारा संचालित", "cta_poll": "पोल में भाग लें", "cta_survey": "सर्वे में भाग लें", "live_poll": "अभी चालू", "not_now": "अभी नहीं",
           "private_note": "आपके उत्तर गोपनीय हैं, जब तक यह सर्वे आपसे संपर्क जानकारी न माँगे।"},
}
INDIA_STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
                "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands",
                "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"]


class AnswerError(ValueError):
    """The answers cannot be accepted; `errors` maps a question id to a plain sentence, so the page can mark the questions to fix."""

    def __init__(self, message: str, errors: dict[str, str] | None = None):
        super().__init__(message)
        self.errors = errors or {}


def sc_base() -> str:
    from api import services_cms
    return services_cms.BASE_URL


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _text(value: Any, label: str, limit: int, *, required: bool = False) -> str:
    out = re.sub(r"[ \t]+", " ", str(value if value is not None else "").replace("\r", "")).strip()
    if required and not out:
        raise ValueError(f"{label} cannot be empty")
    if len(out) > limit:
        raise ValueError(f"{label} is too long: {len(out)} characters, the most is {limit}")
    return out


def _choice(value: Any, allowed: tuple[str, ...], label: str, default: str) -> str:
    v = str(value or default)
    if v not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return v


def _when(value: Any, label: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid date and time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _int(value: Any, label: str, lo: int, hi: int) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number") from exc
    if not lo <= n <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi}")
    return n


def _num(value: Any, label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if math.isnan(n) or math.isinf(n):
        raise ValueError(f"{label} must be a number")
    return n


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(text or "").lower())).strip("-")[:70]


# ----------------------------------------------------------------------------------------------- pictures
MAX_UPLOAD_BYTES, MAX_PIXELS = 2_500_000, 40_000_000
SIZE_LIMITS = {"option": 480, "logo": 600, "question": 1200}   # the longest side after shrinking, by use
_KEY = re.compile(r"^[0-9a-f]{20}$")
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"), (b"GIF87a", "GIF"), (b"GIF89a", "GIF"))


def _image_key(value: Any) -> str:
    v = str(value or "")
    return v if _KEY.fullmatch(v) else ""


def image_url(key: str | None) -> str:
    return f"/survey-img/{key}.webp" if key else ""


def process_image(raw: bytes, purpose: str = "option") -> tuple[bytes, int, int]:
    """A picture made safe for the page: only PNG, JPEG, WebP or GIF (checked by the file's own first bytes, never by its name; SVG is refused because it can carry script), turned upright, stripped of
    camera data and location, shrunk to a sensible size and stored as WebP. Raises ValueError with a plain sentence."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("The picture is too large: the most is 2.5 MB.")
    if not (any(raw.startswith(m) for m, _ in _MAGIC) or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")):
        raise ValueError("Only PNG, JPEG, WebP or GIF pictures are accepted.")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("The picture has too many pixels. Please use a smaller one.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise ValueError("That file is not a picture that can be read.") from exc
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA") if (img.mode in ("P", "LA", "RGBA") or "transparency" in img.info) else img.convert("RGB")
    limit = SIZE_LIMITS.get(purpose, 480)
    img.thumbnail((limit, limit), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=4)
    return buf.getvalue(), img.width, img.height


def store_image(session: Session, filename: str, raw: bytes, by: str | None, purpose: str = "option", survey_id: int | None = None) -> dict[str, Any]:
    data, w, h = process_image(raw, purpose)
    session.query(SurveyImage).filter(SurveyImage.survey_id.is_(None), SurveyImage.created_at < _now() - timedelta(hours=48)).delete(synchronize_session=False)   # pictures uploaded but never used
    key = secrets.token_hex(10)
    session.add(SurveyImage(key=key, survey_id=survey_id, filename=re.sub(r"[^\w.\- ]", "", str(filename or ""))[:160], width=w, height=h, data=data, created_at=_now(), created_by=by))
    session.commit()
    return {"key": key, "url": image_url(key), "width": w, "height": h}


def get_image(session: Session, key: str) -> SurveyImage | None:
    return session.query(SurveyImage).filter_by(key=key).first() if _image_key(key) else None


def referenced_image_keys(questions: list[dict[str, Any]], logo: str | None = None) -> set[str]:
    keys = {logo} if logo else set()
    for q in questions:
        if q.get("image"):
            keys.add(q["image"])
        keys.update(o["image"] for o in q.get("options", []) if o.get("image"))
    return keys


def _verify_images(session: Session, keys: set[str], survey_id: int | None, image_owner: str | None = None) -> None:
    if not keys:
        return
    rows = session.query(SurveyImage).filter(SurveyImage.key.in_(keys)).all()
    if len(rows) != len(keys) or (image_owner is not None and any(r.created_by != image_owner for r in rows)):
        raise ValueError("A picture in this survey is missing. Please add it again.")
    if any(r.survey_id not in (None, survey_id) for r in rows):
        raise ValueError("A picture belongs to another survey. Please upload it again.")


def _attach_images(session: Session, keys: set[str], survey_id: int) -> None:
    if keys:
        session.query(SurveyImage).filter(SurveyImage.key.in_(keys), SurveyImage.survey_id.is_(None)).update({"survey_id": survey_id}, synchronize_session=False)


def _clone_images(session: Session, questions: list[dict[str, Any]], logo: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """Copies of the pictures for a copy of a survey, so that deleting one survey never takes a picture from the other."""
    made: dict[str, str] = {}

    def clone(key: str) -> str:
        if key not in made:
            src = session.query(SurveyImage).filter_by(key=key).first()
            if src is None:
                return ""
            new = secrets.token_hex(10)
            session.add(SurveyImage(key=new, survey_id=None, filename=src.filename, width=src.width, height=src.height, data=src.data, created_at=_now(), created_by=src.created_by))
            made[key] = new
        return made[key]
    out = json.loads(json.dumps(questions))
    for q in out:
        if q.get("image"):
            q["image"] = clone(q["image"]) or None
        for o in q.get("options", []):
            if o.get("image"):
                o["image"] = clone(o["image"]) or None
    session.flush()
    return out, (clone(logo) if logo else None)


# ----------------------------------------------------------------------------------------------- questions
def _next_id(prefix: str, used: set[str]) -> str:
    n = 1 + max((int(x[len(prefix):]) for x in used if re.fullmatch(prefix + r"\d+", x)), default=0)
    return f"{prefix}{n}"


def clean_questions(raw: Any, previous: list[dict[str, Any]] | None = None, has_responses: bool = False) -> list[dict[str, Any]]:
    """The questions, checked and given stable ids. When answers already exist nothing that holds an answer may be removed or changed in type."""
    if not isinstance(raw, list):
        raise ValueError("the questions must be a list")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"a survey can have at most {MAX_QUESTIONS} questions")
    out: list[dict[str, Any]] = []
    used_q: set[str] = set()
    for item in raw:
        if isinstance(item, dict) and re.fullmatch(r"q\d+", str(item.get("id") or "")):
            used_q.add(str(item["id"]))
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"question {index} is not valid")
        qtype = _choice(item.get("type"), TYPES, f"the type of question {index}", "single")
        qid = str(item.get("id") or "")
        if not re.fullmatch(r"q\d+", qid) or qid in seen:
            qid = _next_id("q", used_q | seen)
        seen.add(qid)
        q: dict[str, Any] = {"id": qid, "type": qtype, "text": _text(item.get("text"), f"the text of question {index}", 400, required=True), "help": _text(item.get("help"), "the help text", 300),
                             "required": bool(item.get("required")) and qtype != "section", "archived": bool(item.get("archived"))}
        if _image_key(item.get("image")):
            q["image"] = _image_key(item.get("image"))
        if qtype in CHOICE:
            options, used_o = [], set()
            for o in item.get("options") or []:
                if isinstance(o, dict) and re.fullmatch(r"o\d+", str(o.get("id") or "")):
                    used_o.add(str(o["id"]))
            taken: set[str] = set()
            for o in item.get("options") or []:
                if isinstance(o, str):
                    o = {"text": o}
                if not isinstance(o, dict) or not str(o.get("text") or "").strip():
                    continue
                oid = str(o.get("id") or "")
                if not re.fullmatch(r"o\d+", oid) or oid in taken:
                    oid = _next_id("o", used_o | taken)
                taken.add(oid)
                options.append({"id": oid, "text": _text(o.get("text"), "an option", 200), "other": bool(o.get("other")) and qtype in ("single", "multi", "dropdown"),
                                "exclusive": bool(o.get("exclusive")) and qtype == "multi", "archived": bool(o.get("archived")), **({"group": str(o["group"])} if re.fullmatch(r"o\d+", str(o.get("group") or "")) else {}), **({"image": _image_key(o.get("image"))} if _image_key(o.get("image")) else {})})
            if len([o for o in options if not o["archived"]]) < 2:
                raise ValueError(f"question {index} needs at least two options")
            limit = MAX_DROPDOWN_OPTIONS if qtype == "dropdown" else MAX_OPTIONS
            if len(options) > limit:
                raise ValueError(f"question {index} can have at most {limit} options")
            parent_id = str(item.get("depends_on") or "") if qtype == "dropdown" else ""
            if parent_id:   # a dropdown that lists only the options belonging to the answer of an earlier question (a district's constituencies)
                parent = next((p for p in out if p["id"] == parent_id), None)
                if parent is None or parent["type"] not in ("single", "dropdown"):
                    raise ValueError(f"question {index}: the options can depend only on an earlier one-choice or dropdown question")
                known = {p["id"] for p in parent["options"]}
                if any(o.get("group") not in known for o in options):
                    raise ValueError(f"question {index}: every option must belong to one answer of the question it depends on")
                q["depends_on"] = parent_id
            else:
                for o in options:
                    o.pop("group", None)
            q["options"] = options
            q["randomize"] = bool(item.get("randomize"))
            if qtype == "multi":
                q["max_select"] = _int(item.get("max_select"), "the most choices", 1, MAX_OPTIONS)
        elif qtype == "rating":
            q["scale_max"] = _int(item.get("scale_max"), "the top of the scale", 3, 10) or 5
            q["label_low"], q["label_high"] = _text(item.get("label_low"), "the low label", 40), _text(item.get("label_high"), "the high label", 40)
        elif qtype == "nps":
            q["label_low"] = _text(item.get("label_low"), "the low label", 40) or "Not at all likely"
            q["label_high"] = _text(item.get("label_high"), "the high label", 40) or "Extremely likely"
        elif qtype == "number":
            for key in ("min", "max"):
                q[key] = _num(item.get(key), f"the {key} of question {index}")
            if q["min"] is not None and q["max"] is not None and q["min"] > q["max"]:
                raise ValueError(f"question {index}: the least is more than the most")
            q["unit"] = _text(item.get("unit"), "the unit", 20)
        elif qtype in ("text", "longtext"):
            q["max_length"] = _int(item.get("max_length"), "the longest answer", 20, 2000) or (300 if qtype == "text" else 1500)
        cond = item.get("show_if")
        if isinstance(cond, dict) and cond.get("q"):
            if str(cond["q"]) not in seen - {qid}:
                raise ValueError(f"question {index}: a question can only depend on one that comes before it")
            op = str(cond.get("op") or "is")
            if op not in ("is", "not"):
                raise ValueError(f"question {index}: the condition must be 'is' or 'is not'")
            values = [str(v)[:40] for v in (cond.get("values") or [])][:20]
            if not values:
                raise ValueError(f"question {index}: choose which answer shows this question")
            q["show_if"] = {"q": str(cond["q"]), "op": op, "values": values}
        out.append(q)
    if previous and has_responses:
        now = {q["id"]: q for q in out}
        for old in previous:
            new = now.get(old["id"])
            if new is None:
                raise ValueError(f'Answers already exist: "{old["text"]}" cannot be deleted. Archive it instead (it is hidden from new respondents and kept in the results).')
            if new["type"] != old["type"]:
                raise ValueError(f'Answers already exist: the type of "{old["text"]}" cannot change.')
            for oo in old.get("options") or []:
                if oo["id"] not in {o["id"] for o in new.get("options") or []}:
                    raise ValueError(f'Answers already exist: the option "{oo["text"]}" cannot be deleted. Archive it instead.')
    return out


def active_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for q in questions:
        if q.get("archived"):
            continue
        q = dict(q)
        if "options" in q:
            q["options"] = [o for o in q["options"] if not o.get("archived")]
        out.append(q)
    return out


def _answer_values(ans: dict[str, Any] | None) -> list[str]:
    if not ans:
        return []
    if "o" in ans:
        return [str(x) for x in (ans["o"] if isinstance(ans["o"], list) else [ans["o"]])]
    if "n" in ans:
        return [str(ans["n"]).rstrip("0").rstrip(".") if isinstance(ans["n"], float) else str(ans["n"])]
    return []


def _shown(q: dict[str, Any], answers: dict[str, Any]) -> bool:
    if q.get("depends_on") and not _answer_values(answers.get(q["depends_on"])):
        return False   # the options depend on an answer that has not been given
    cond = q.get("show_if")
    if not cond:
        return True
    hit = bool(set(_answer_values(answers.get(cond["q"]))) & set(cond["values"]))
    return hit if cond["op"] == "is" else not hit


# ----------------------------------------------------------------------------------------------- the survey record
def _slug_free(session: Session, slug: str, current: Survey | None) -> None:
    other = session.query(Survey).filter(Survey.slug == slug).first()
    if other is not None and (current is None or other.id != current.id):
        raise ValueError(f'the web address "{slug}" is already used by "{other.title}"')


def clean_survey(payload: dict[str, Any], session: Session, current: Survey | None) -> dict[str, Any]:
    title = _text(payload.get("title"), "the title", 200, required=True)
    slug = slugify(payload.get("slug") or title)
    if not SLUG_RE.fullmatch(slug) or len(slug) < 3 or slug in RESERVED:
        raise ValueError("the web address needs 3 or more letters or numbers (small letters, numbers and hyphens)")
    _slug_free(session, slug, current)
    contact_mode = _choice(payload.get("contact_mode"), CONTACT_MODES, "contact details", "none")
    fields = [f for f in (payload.get("contact_fields") or []) if f in CONTACT_FIELDS] if isinstance(payload.get("contact_fields"), list) else [f for f in str(payload.get("contact_fields") or "").split(",") if f in CONTACT_FIELDS]
    if contact_mode != "none" and not fields:
        raise ValueError("choose which contact details to ask for (name, mobile, e-mail)")
    consent = _text(payload.get("consent_text"), "the consent text", 1000)
    if contact_mode != "none" and not consent:
        raise ValueError("when contact details are asked for, write the consent text people agree to")
    opens, closes = _when(payload.get("opens_at"), "the opening time"), _when(payload.get("closes_at"), "the closing time")
    if opens and closes and closes <= opens:
        raise ValueError("the closing time must be after the opening time")
    redirect = _text(payload.get("redirect_url"), "the address to go to afterwards", 500)
    if redirect and not redirect.startswith("https://"):
        raise ValueError("the address to go to afterwards must start with https://")
    sampling = _choice(payload.get("sampling"), SAMPLING, "the sampling", "self_selected")
    population = _int(payload.get("population_size"), "the population size", 2, 2_000_000_000)
    questions = clean_questions(payload.get("questions") if "questions" in payload else (json.loads(current.questions_json) if current else []),
                                json.loads(current.questions_json) if current else None, bool(current and response_count(session, current.id, include_removed=True)))
    kind = _choice(payload.get("kind"), KINDS, "the kind", "survey")
    if kind == "poll" and len([q for q in questions if q["type"] in ANSWERED and not q.get("archived")]) > 3:
        raise ValueError("a poll has at most three questions; make it a survey for more")
    return {"slug": slug, "title": title, "kind": kind, "category": _choice(payload.get("category"), CATEGORIES, "the subject", "opinion"), "description": _text(payload.get("description"), "the short description", 700),
            "intro": _text(payload.get("intro"), "the introduction", 3000), "thank_you": _text(payload.get("thank_you"), "the thank-you text", 1000), "language": _choice(payload.get("language"), ("en", "hi"), "the language", "en"),
            "access": _choice(payload.get("access"), ACCESS, "who can answer", "public"), "results_mode": _choice(payload.get("results_mode"), RESULTS_MODES, "the results setting", "private"),
            "results_hold": bool(payload.get("results_hold")), "min_results": _int(payload.get("min_results"), "the least answers before results show", 0, 100000) if payload.get("min_results") not in (None, "") else 10,
            "sampling": sampling, "population_size": population if sampling == "random_sample" else None, "contact_mode": contact_mode, "contact_fields": ",".join(fields) if contact_mode != "none" else "", "consent_text": consent,
            "sponsor": _text(payload.get("sponsor"), "who paid for it", 200), "method_note": _text(payload.get("method_note"), "the method note", 1500), "opens_at": opens, "closes_at": closes,
            "max_responses": _int(payload.get("max_responses"), "the most answers", 1, 10_000_000), "allow_repeat": bool(payload.get("allow_repeat")), "listed": bool(payload.get("listed")),
            "promote": bool(payload["promote"]) if "promote" in payload else (bool(current.promote) if current else True),
            "redirect_url": redirect or None, "logo_image": _image_key(payload.get("logo_image") if "logo_image" in payload else (current.logo_image if current else None)) or None, "questions": questions}


def serialize(row: Survey, session: Session | None = None) -> dict[str, Any]:
    out = {"id": row.id, "slug": row.slug, "title": row.title, "kind": row.kind, "category": row.category, "description": row.description, "intro": row.intro, "thank_you": row.thank_you, "language": row.language,
           "status": row.status, "state": state_of(row), "access": row.access, "results_mode": row.results_mode, "results_hold": bool(row.results_hold), "min_results": row.min_results, "sampling": row.sampling,
           "population_size": row.population_size, "contact_mode": row.contact_mode, "contact_fields": [f for f in (row.contact_fields or "").split(",") if f], "consent_text": row.consent_text, "sponsor": row.sponsor,
           "method_note": row.method_note, "opens_at": row.opens_at.isoformat() if row.opens_at else None, "closes_at": row.closes_at.isoformat() if row.closes_at else None, "max_responses": row.max_responses,
           "allow_repeat": bool(row.allow_repeat), "listed": bool(row.listed), "promote": bool(row.promote), "redirect_url": row.redirect_url or "", "owner_id": row.owner_id, "review_note": row.review_note or "", "logo_image": row.logo_image or "", "logo_url": image_url(row.logo_image), "questions": json.loads(row.questions_json or "[]"),
           "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "updated_by": row.updated_by}
    if session is not None:
        out["responses"] = response_count(session, row.id)
        out["has_responses"] = response_count(session, row.id, include_removed=True) > 0
    return out


def state_of(row: Survey, now: datetime | None = None) -> str:
    """draft, scheduled (live but not yet open), open, or closed (by hand, by its closing time, or because it is full needs the count: see accepting())."""
    now = now or _now()
    if row.status == "draft":
        return "draft"
    if row.status == "review":
        return "review"
    if row.status == "closed":
        return "closed"
    if row.opens_at and _aware(row.opens_at) > now:
        return "scheduled"
    if row.closes_at and _aware(row.closes_at) <= now:
        return "closed"
    return "open"


def _revise(session: Session, row: Survey | None, action: str, by: str | None, snapshot: dict[str, Any] | None = None) -> None:
    snap = snapshot if snapshot is not None else serialize(row)
    session.add(SurveyRevision(survey_id=row.id if row is not None else snap.get("id"), slug=row.slug if row is not None else snap.get("slug", ""), action=action, snapshot=json.dumps(snap, ensure_ascii=False), by=by, at=_now()))


def _apply(row: Survey, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if key == "questions":
            row.questions_json = json.dumps(value, ensure_ascii=False)
        else:
            setattr(row, key, value)


def get_survey(session: Session, survey_id: int) -> Survey:
    row = session.get(Survey, survey_id)
    if row is None:
        raise LookupError("that survey does not exist")
    return row


def _go_live_checks(data: dict[str, Any]) -> None:
    answered = [q for q in data["questions"] if q["type"] in ANSWERED and not q.get("archived")]
    if not answered:
        raise ValueError("to open it, add at least one question")


def save_survey(session: Session, by: str, payload: dict[str, Any], survey_id: int | None = None, *, owner_id: int | None = None, can_publish: bool = True, image_owner: str | None = None) -> dict[str, Any]:
    """Save a survey. `can_publish` False (a client without the publish tick): asking for "live" sends it to review instead, and an open survey cannot be changed (close it, change it, send it again).
    `image_owner` limits the pictures to those that account uploaded."""
    row = get_survey(session, survey_id) if survey_id else None
    if row is not None and row.status == "live" and not can_publish and str(payload.get("status") or "live") == "live":
        raise PermissionError("This poll is open, so it cannot be changed. Close it, make the change, and send it for approval again.")
    data = clean_survey(payload, session, row)
    status = str(payload.get("status") or (row.status if row else "draft"))
    if status not in STATUSES:
        raise ValueError("the state must be draft, review, live or closed")
    if status == "review" and can_publish:
        status = "live"
    if status in ("live", "review"):
        _go_live_checks(data)
    if status == "live" and not can_publish:
        status = "review"
    keys = referenced_image_keys(data["questions"], data.get("logo_image"))
    _verify_images(session, keys, row.id if row else None, image_owner)
    created = row is None
    if created:
        row = Survey(created_at=_now(), owner_id=owner_id)
        session.add(row)
    before = None if created else row.status
    _apply(row, data)
    row.status, row.updated_at, row.updated_by = status, _now(), by
    session.flush()
    _attach_images(session, keys, row.id)
    if row.review_note and status in ("review", "live"):
        row.review_note = ""
    _revise(session, row, "create" if created else ("open" if status == "live" and before != "live" else "request" if status == "review" and before != "review" else "close" if status == "closed" and before != "closed" else "update"), by)
    session.commit()
    return serialize(row, session)


def set_status(session: Session, by: str, survey_id: int, status: str, *, can_publish: bool = True) -> dict[str, Any]:
    row = get_survey(session, survey_id)
    if status not in STATUSES:
        raise ValueError("the state must be draft, review, live or closed")
    if status == "review" and can_publish:
        status = "live"
    if status in ("live", "review"):
        _go_live_checks({"questions": json.loads(row.questions_json or "[]")})
    if status == "live" and not can_publish:
        if row.status == "live":
            return serialize(row, session)
        status = "review"
    if row.status != status:
        row.status, row.updated_at, row.updated_by = status, _now(), by
        if status in ("review", "live"):
            row.review_note = ""
        _revise(session, row, {"live": "open", "closed": "close", "draft": "update", "review": "request"}[status], by)
        session.commit()
    return serialize(row, session)


def reject_review(session: Session, by: str, survey_id: int, note: str) -> dict[str, Any]:
    """An administrator sends a poll that was waiting for approval back to its owner as a draft, with the reason."""
    row = get_survey(session, survey_id)
    if row.status != "review":
        raise ValueError("that poll is not waiting for approval")
    row.status, row.review_note, row.updated_at, row.updated_by = "draft", _text(note, "the reason", 400), _now(), by
    _revise(session, row, "reject", by)
    session.commit()
    return serialize(row, session)


def delete_survey(session: Session, by: str, survey_id: int) -> dict[str, Any]:
    row = get_survey(session, survey_id)
    snap = serialize(row, session)
    n = response_count(session, row.id, include_removed=True)
    if n and row.status != "draft":
        raise ValueError(f"This survey has {n} answers. Close it instead (the answers stay), or export them first and delete the answers one by one.")
    _revise(session, row, "delete", by, snap)
    for r in session.query(SurveyResponse).filter_by(survey_id=row.id).all():
        session.delete(r)
    for i in session.query(SurveyInvite).filter_by(survey_id=row.id).all():
        session.delete(i)
    session.query(SurveyImage).filter_by(survey_id=row.id).delete(synchronize_session=False)
    session.delete(row)
    session.commit()
    return {"deleted": snap["slug"]}


def duplicate_survey(session: Session, by: str, survey_id: int, *, owner_id: int | None = None) -> dict[str, Any]:
    src = serialize(get_survey(session, survey_id))
    base = src["slug"] + "-copy"
    slug, n = base, 1
    while session.query(Survey).filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    questions, logo = _clone_images(session, src["questions"], src.get("logo_image"))
    return save_survey(session, by, {**src, "slug": slug, "title": src["title"] + " (copy)", "status": "draft", "questions": questions, "logo_image": logo, "opens_at": None, "closes_at": None, "listed": False}, owner_id=owner_id)


def list_surveys(session: Session, owner_id: int | None = None) -> list[dict[str, Any]]:
    query = session.query(Survey)
    if owner_id is not None:
        query = query.filter(Survey.owner_id == owner_id)
    return [serialize(r, session) for r in query.order_by(Survey.created_at.desc(), Survey.id.desc()).all()]


def revisions(session: Session, survey_id: int) -> list[dict[str, Any]]:
    return [{"id": r.id, "action": r.action, "by": r.by, "at": r.at.isoformat() if r.at else None} for r in session.query(SurveyRevision).filter_by(survey_id=survey_id).order_by(SurveyRevision.id.desc()).limit(60).all()]


# ----------------------------------------------------------------------------------------------- the page a respondent sees
def _with_urls(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for q in questions:
        if q.get("image"):
            q["image_url"] = image_url(q["image"])
        for o in q.get("options", []):
            if o.get("image"):
                o["image_url"] = image_url(o["image"])
    return questions


def public_definition(row: Survey) -> dict[str, Any]:
    """Only what the respondent's page needs: no settings of the administrator, no archived questions or options."""
    s = serialize(row)
    strings = STRINGS[s["language"]]
    return {"slug": s["slug"], "title": s["title"], "kind": s["kind"], "category": s["category"], "description": s["description"], "intro": s["intro"], "thank_you": s["thank_you"] or strings["thanks"], "language": s["language"],
            "strings": strings, "contact": {"mode": s["contact_mode"], "fields": s["contact_fields"], "consent": s["consent_text"]}, "sponsor": s["sponsor"], "redirect_url": s["redirect_url"],
            "logo_url": s["logo_url"], "questions": _with_urls(active_questions(s["questions"])), "access": s["access"], "results_mode": s["results_mode"]}


def home_polls(session: Session, limit: int = 3, now: datetime | None = None) -> list[dict[str, Any]]:
    """The open, public polls and surveys that are shown on the home page (a popup for the newest, and a section for up to three), newest first. Invitation-only and full ones never appear."""
    out = []
    for row in session.query(Survey).filter(Survey.status == "live", Survey.access == "public", Survey.promote.is_(True)).order_by(Survey.id.desc()).all():
        if accepting(session, row, now)[0]:
            s = STRINGS[row.language]
            out.append({"slug": row.slug, "title": row.title, "kind": row.kind, "category": row.category, "description": row.description or row.intro[:160], "logo_url": image_url(row.logo_image),
                        "cta": s["cta_poll"] if row.kind == "poll" else s["cta_survey"], "label": s["live_poll"], "later": s["not_now"]})
        if len(out) >= limit:
            break
    return out


def accepting(session: Session, row: Survey, now: datetime | None = None) -> tuple[bool, str]:
    """Whether new answers are accepted, and if not, the key of the sentence to tell the respondent."""
    state = state_of(row, now)
    if state in ("draft", "review"):
        return False, "closed"
    if state == "scheduled":
        return False, "not_yet"
    if state == "closed":
        return False, "closed"
    if row.max_responses and response_count(session, row.id) >= row.max_responses:
        return False, "closed"
    return True, ""


# ----------------------------------------------------------------------------------------------- answers
def validate_answers(questions: list[dict[str, Any]], answers: Any, language: str = "en") -> dict[str, Any]:
    """The cleaned answers: unknown questions and answers to hidden questions are dropped, every rule is checked. Raises AnswerError naming the questions to fix."""
    strings = STRINGS.get(language, STRINGS["en"])
    if not isinstance(answers, dict):
        raise AnswerError("the answers must be an object")
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for q in active_questions(questions):
        if q["type"] == "section":
            continue
        qid, ans = q["id"], answers.get(q["id"])
        if not _shown(q, clean):
            continue
        empty = ans is None or ans == {} or ans == "" or (isinstance(ans, dict) and not any(v not in (None, "", []) for v in ans.values()))
        if empty:
            if q.get("required"):
                errors[qid] = strings["required"]
            continue
        if not isinstance(ans, dict):
            errors[qid] = "That answer is not valid."
            continue
        try:
            clean[qid] = _check_one(q, ans, strings)
            if q.get("depends_on"):
                chosen = next((o for o in q["options"] if o["id"] == clean[qid].get("o")), None)
                if chosen is not None and chosen.get("group") not in _answer_values(clean.get(q["depends_on"])):
                    clean.pop(qid)
                    raise ValueError("That answer is not valid.")
        except ValueError as exc:
            errors[qid] = str(exc)
    if errors:
        raise AnswerError(next(iter(errors.values())), errors)
    return clean


def _check_one(q: dict[str, Any], ans: dict[str, Any], strings: dict[str, str]) -> dict[str, Any]:
    t = q["type"]
    options = {o["id"]: o for o in q.get("options", [])}
    if t in ("single", "dropdown"):
        oid = str(ans.get("o") if not isinstance(ans.get("o"), list) else (ans["o"][0] if ans["o"] else ""))
        if oid not in options:
            raise ValueError("Please choose one of the options.")
        out: dict[str, Any] = {"o": oid}
        if options[oid].get("other"):
            other = _text(ans.get("t"), "the answer", 300)
            if not other:
                raise ValueError(strings["other"] + ".")
            out["t"] = other
        return out
    if t == "multi":
        chosen = [str(x) for x in (ans.get("o") if isinstance(ans.get("o"), list) else [ans.get("o")]) if x]
        chosen = list(dict.fromkeys(chosen))
        if not chosen or any(c not in options for c in chosen):
            raise ValueError("Please choose from the options.")
        if q.get("max_select") and len(chosen) > q["max_select"]:
            raise ValueError(f"{strings['select_up_to']} {q['max_select']}.")
        if any(options[c].get("exclusive") for c in chosen) and len(chosen) > 1:
            raise ValueError("That choice cannot be combined with the others.")
        out = {"o": chosen}
        if any(options[c].get("other") for c in chosen):
            other = _text(ans.get("t"), "the answer", 300)
            if not other:
                raise ValueError(strings["other"] + ".")
            out["t"] = other
        return out
    if t == "ranking":
        order = [str(x) for x in (ans.get("o") or [])] if isinstance(ans.get("o"), list) else []
        if sorted(order) != sorted(options):
            raise ValueError(strings["one_per_rank"] + ".")
        return {"o": order}
    if t in ("rating", "nps", "number"):
        try:
            n = float(ans.get("n"))
        except (TypeError, ValueError):
            raise ValueError("Please give a number.") from None
        if math.isnan(n) or math.isinf(n):
            raise ValueError("Please give a number.")
        if t == "rating" and not (1 <= n <= q["scale_max"] and n == int(n)):
            raise ValueError(f"Please choose from 1 to {q['scale_max']}.")
        if t == "nps" and not (0 <= n <= 10 and n == int(n)):
            raise ValueError("Please choose from 0 to 10.")
        if t == "number":
            if q.get("min") is not None and n < q["min"]:
                raise ValueError(f"The number must be at least {q['min']:g}.")
            if q.get("max") is not None and n > q["max"]:
                raise ValueError(f"The number must be at most {q['max']:g}.")
        return {"n": int(n) if n == int(n) else n}
    if t in ("text", "longtext"):
        text = _text(ans.get("t"), "the answer", q.get("max_length", 300))
        if not text:
            raise ValueError("Please write an answer.")
        return {"t": text}
    raise ValueError("That question cannot be answered.")


def _secret() -> bytes:
    return os.getenv("STAXIS_AUTH_SECRET", "development-only-secret").encode("utf-8")


def hash_value(kind: str, value: str, survey_id: int) -> str:
    return hashlib.sha256(_secret() + f"|{kind}|{survey_id}|{value}".encode("utf-8")).hexdigest()


def new_invite_code() -> str:
    return secrets.token_urlsafe(18)


def clean_mobile(raw: str) -> str:
    """The mobile number as digits, or "" when it cannot be real. An Indian number (10 digits starting 6 to 9, with or without +91 or 0) is stored as those 10 digits; a number written with another country code
    (+ then 8 to 15 digits) is kept as typed digits. Numbers made of one repeated digit or a straight run (1234567890) are refused. This checks the shape only; it cannot know that the person owns the number."""
    text = raw.strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and not digits.startswith("91"):
        return digits if 8 <= len(digits) <= 15 else ""
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits) or len(set(digits)) <= 2 or digits in "01234567890123456789" or digits in "98765432109876543210":
        return ""
    return digits


def _mobile_used(session: Session, row: Survey, mobile: str) -> bool:
    """Whether a response that was not removed already came with this mobile number."""
    if not mobile:
        return False
    like = f'%"mobile": "{mobile}"%'
    return session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id, SurveyResponse.status != "removed", SurveyResponse.contact_json.like(like)).first() is not None


def _clean_contact(row: Survey, contact: Any, consent: Any) -> dict[str, str] | None:
    mode = row.contact_mode
    if mode == "none":
        return None
    fields = [f for f in (row.contact_fields or "").split(",") if f]
    contact = contact if isinstance(contact, dict) else {}
    out: dict[str, str] = {}
    errors: dict[str, str] = {}
    for f in fields:
        v = _text(contact.get(f), f, 160)
        if f == "mobile" and v:
            v = clean_mobile(v)
            if not v:
                errors["contact"] = "Please give a valid mobile number."
                continue
        if f == "email" and v and not EMAIL_RE.fullmatch(v):
            errors["contact"] = "Please give a valid e-mail address."
        if v:
            out[f] = v
        elif mode == "required":
            errors["contact"] = "Please fill in your details."
    if errors:
        raise AnswerError(errors["contact"], errors)
    if out and not consent:
        raise AnswerError("Please tick the box to agree.", {"contact": "Please tick the box to agree."})
    return out or None


def submit_response(session: Session, row: Survey, answers: Any, *, contact: Any = None, consent: bool = False, token: str = "", device: str = "", started_ms: Any = None, invite: str = "",
                    now: datetime | None = None) -> dict[str, Any]:
    """Check and store one response. Raises ValueError with a sentence for the respondent (AnswerError names the questions to fix)."""
    now = now or _now()
    ok, why = accepting(session, row, now)
    strings = STRINGS.get(row.language, STRINGS["en"])
    if not ok:
        raise ValueError(strings[why])
    invite_row = None
    if row.access == "invite":
        invite_row = session.query(SurveyInvite).filter_by(survey_id=row.id, code_hash=hash_value("invite", invite, row.id)).first() if invite else None
        if invite_row is None:
            raise ValueError(strings["invite"])
        if invite_row.used_at is not None:
            raise ValueError(strings["already"])
    clean = validate_answers(json.loads(row.questions_json or "[]"), answers, row.language)
    if not clean:
        raise AnswerError("Please answer at least one question.")
    contact_clean = _clean_contact(row, contact, consent)
    if contact_clean and not row.allow_repeat and _mobile_used(session, row, contact_clean.get("mobile", "")):
        raise AnswerError(strings["dup_mobile"], {"contact": strings["dup_mobile"]})
    token_hash = hash_value("token", token, row.id) if token and len(token) >= 16 else None
    if token_hash and not row.allow_repeat and session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id, SurveyResponse.token_hash == token_hash, SurveyResponse.status != "removed").first():
        raise ValueError(strings["already"])
    device_hash = hash_value("device", device, row.id) if device else None
    flags = []
    if device_hash and session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id, SurveyResponse.device_hash == device_hash, SurveyResponse.status != "removed",
                                                              SurveyResponse.submitted_at >= now - timedelta(hours=24)).first():
        flags.append("same device within a day")
    duration = None
    try:
        if started_ms not in (None, ""):
            duration = max(0, int((now.timestamp() * 1000 - float(started_ms)) / 1000))
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration < max(3, int(1.2 * len(clean))):
        flags.append("answered very fast")
    resp = SurveyResponse(survey_id=row.id, submitted_at=now, duration_seconds=duration if duration is not None and duration < 86400 else None, answers_json=json.dumps(clean, ensure_ascii=False),
                          contact_json=json.dumps(contact_clean, ensure_ascii=False) if contact_clean else None, status="flagged" if flags else "valid", flags="; ".join(flags), token_hash=token_hash,
                          device_hash=device_hash, invite_id=invite_row.id if invite_row else None)
    session.add(resp)
    if invite_row is not None:
        invite_row.used_at = now
    session.commit()
    return {"id": resp.id}


def response_count(session: Session, survey_id: int, *, include_removed: bool = False, include_flagged: bool = True) -> int:
    query = session.query(SurveyResponse).filter(SurveyResponse.survey_id == survey_id)
    if not include_removed:
        query = query.filter(SurveyResponse.status != "removed")
    if not include_flagged:
        query = query.filter(SurveyResponse.status == "valid")
    return query.count()


def set_response_status(session: Session, response_id: int, status: str) -> dict[str, Any]:
    if status not in ("valid", "flagged", "removed"):
        raise ValueError("the state must be valid, flagged or removed")
    r = session.get(SurveyResponse, response_id)
    if r is None:
        raise LookupError("that answer does not exist")
    r.status = status
    if status == "valid":
        r.flags = ""
    session.commit()
    return {"id": r.id, "status": r.status}


def purge_removed(session: Session, survey_id: int) -> int:
    rows = session.query(SurveyResponse).filter_by(survey_id=survey_id, status="removed").all()
    for r in rows:
        session.delete(r)
    session.commit()
    return len(rows)


# ----------------------------------------------------------------------------------------------- invites
def create_invites(session: Session, row: Survey, labels: list[str] | None = None, count: int = 0) -> list[dict[str, str]]:
    """Personal links for an invite-only survey. The codes are returned once (only their hashes are kept)."""
    names = [_text(x, "a label", 160) for x in (labels or []) if str(x).strip()] or [f"Link {i}" for i in range(1, count + 1)]
    if not names or len(names) > 5000:
        raise ValueError("ask for between 1 and 5000 links")
    out = []
    for name in names:
        code = new_invite_code()
        session.add(SurveyInvite(survey_id=row.id, code_hash=hash_value("invite", code, row.id), label=name, created_at=_now()))
        out.append({"label": name, "code": code})
    session.commit()
    return out


def invite_summary(session: Session, survey_id: int) -> dict[str, Any]:
    rows = session.query(SurveyInvite).filter_by(survey_id=survey_id).order_by(SurveyInvite.id).all()
    return {"total": len(rows), "used": sum(1 for r in rows if r.used_at), "invites": [{"id": r.id, "label": r.label, "used": bool(r.used_at), "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows[:1000]]}


# ----------------------------------------------------------------------------------------------- results
def margin_of_error(p: float, n: int, population: int | None = None) -> float:
    """The 95% margin of error of a share p (0-1) among n answers, in percentage points, with the finite-population correction when the population is known."""
    if n < 2:
        return 100.0
    moe = 1.96 * math.sqrt(max(p * (1 - p), 0) / n)
    if population and population > n:
        moe *= math.sqrt((population - n) / (population - 1))
    return round(moe * 100, 1)


def _rows(session: Session, row: Survey, include_flagged: bool, since: datetime | None, until: datetime | None) -> list[tuple[SurveyResponse, dict[str, Any]]]:
    query = session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id, SurveyResponse.status != "removed")
    if not include_flagged:
        query = query.filter(SurveyResponse.status == "valid")
    if since:
        query = query.filter(SurveyResponse.submitted_at >= since)
    if until:
        query = query.filter(SurveyResponse.submitted_at < until)
    return [(r, json.loads(r.answers_json or "{}")) for r in query.order_by(SurveyResponse.id).all()]


def _question_result(q: dict[str, Any], answers: list[dict[str, Any]], sampling: str, population: int | None) -> dict[str, Any]:
    given = [a[q["id"]] for a in answers if q["id"] in a]
    n = len(given)
    out: dict[str, Any] = {"id": q["id"], "type": q["type"], "text": q["text"], "n": n, "archived": bool(q.get("archived"))}
    scientific = sampling == "random_sample"
    if q["type"] in ("single", "dropdown", "multi"):
        counts = {o["id"]: 0 for o in q["options"]}
        others: list[str] = []
        for a in given:
            for oid in a.get("o") if isinstance(a.get("o"), list) else [a.get("o")]:
                if oid in counts:
                    counts[oid] += 1
            if a.get("t"):
                others.append(a["t"])
        out["options"] = [{"id": o["id"], "text": o["text"], "count": counts[o["id"]], "pct": round(100 * counts[o["id"]] / n, 1) if n else 0.0, "archived": bool(o.get("archived")), **({"image_url": image_url(o["image"])} if o.get("image") else {}),
                           **({"moe": margin_of_error(counts[o["id"]] / n, n, population)} if scientific and n else {})} for o in q["options"]]
        out["other_texts"] = others[-100:]
    elif q["type"] == "ranking":
        pos = {o["id"]: [] for o in q["options"]}
        for a in given:
            for rank, oid in enumerate(a.get("o") or [], 1):
                if oid in pos:
                    pos[oid].append(rank)
        out["options"] = sorted([{"id": o["id"], "text": o["text"], **({"image_url": image_url(o["image"])} if o.get("image") else {}), "avg_rank": round(sum(pos[o["id"]]) / len(pos[o["id"]]), 2) if pos[o["id"]] else None,
                                  "first_choice": sum(1 for x in pos[o["id"]] if x == 1), "first_pct": round(100 * sum(1 for x in pos[o["id"]] if x == 1) / n, 1) if n else 0.0}
                                 for o in q["options"]], key=lambda x: (x["avg_rank"] is None, x["avg_rank"] or 0))
    elif q["type"] in ("rating", "nps", "number"):
        values = [a["n"] for a in given if "n" in a]
        out["mean"] = round(statistics.fmean(values), 2) if values else None
        out["median"] = statistics.median(values) if values else None
        out["min"], out["max"] = (min(values), max(values)) if values else (None, None)
        if q["type"] in ("rating", "nps"):
            lo, hi = (1, q["scale_max"]) if q["type"] == "rating" else (0, 10)
            out["distribution"] = [{"value": v, "count": values.count(v), "pct": round(100 * values.count(v) / n, 1) if n else 0.0} for v in range(lo, hi + 1)]
        if q["type"] == "nps":
            promoters, detractors = sum(1 for v in values if v >= 9), sum(1 for v in values if v <= 6)
            out["nps"] = {"promoters": promoters, "passives": n - promoters - detractors, "detractors": detractors, "score": round(100 * (promoters - detractors) / n, 1) if n else None}
    elif q["type"] in ("text", "longtext"):
        out["texts"] = [a["t"] for a in given if a.get("t")][-100:]
    return out


def survey_results(session: Session, row: Survey, *, include_flagged: bool = True, since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    questions = json.loads(row.questions_json or "[]")
    rows = _rows(session, row, include_flagged, since, until)
    answers = [a for _, a in rows]
    durations = [r.duration_seconds for r, _ in rows if r.duration_seconds]
    by_day: dict[str, int] = {}
    ist = timedelta(hours=5, minutes=30)
    for r, _ in rows:
        day = (_aware(r.submitted_at) + ist).date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    all_status = session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id).all()
    return {"survey": {"id": row.id, "title": row.title, "slug": row.slug, "sampling": row.sampling, "population_size": row.population_size, "sponsor": row.sponsor, "method_note": row.method_note,
                       "opens_at": row.opens_at.isoformat() if row.opens_at else None, "closes_at": row.closes_at.isoformat() if row.closes_at else None, "category": row.category},
            "totals": {"counted": len(rows), "valid": sum(1 for r in all_status if r.status == "valid"), "flagged": sum(1 for r in all_status if r.status == "flagged"), "removed": sum(1 for r in all_status if r.status == "removed"),
                       "median_seconds": int(statistics.median(durations)) if durations else None, "first": min((r.submitted_at.isoformat() for r, _ in rows), default=None), "last": max((r.submitted_at.isoformat() for r, _ in rows), default=None)},
            "by_day": [{"date": d, "count": c} for d, c in sorted(by_day.items())],
            "scientific": row.sampling == "random_sample",
            "note": ("Random sample: margins of error are shown (95% level)." if row.sampling == "random_sample" else
                     "Panel sample: not a random sample, so no margin of error is claimed." if row.sampling == "panel" else
                     "Self-selected answers: the people who chose to answer. These results describe them, not the whole population, and carry no margin of error."),
            "questions": [_question_result(q, answers, row.sampling, row.population_size) for q in questions if q["type"] in ANSWERED]}


def crosstab(session: Session, row: Survey, target_id: str, by_id: str, *, include_flagged: bool = True) -> dict[str, Any]:
    """How the answers to one choice question split by the answers to another (single choice) question. Column percentages: each column adds up to 100."""
    questions = {q["id"]: q for q in json.loads(row.questions_json or "[]")}
    target, by = questions.get(target_id), questions.get(by_id)
    if target is None or by is None or target["type"] not in ("single", "dropdown", "multi") or by["type"] not in ("single", "dropdown"):
        raise ValueError("choose a choice question to look at, and a single-choice question to split it by")
    cols = {o["id"]: {"text": o["text"], "n": 0, "counts": {t["id"]: 0 for t in target["options"]}} for o in by["options"]}
    for _, a in _rows(session, row, include_flagged, None, None):
        b, t = a.get(by_id), a.get(target_id)
        if not b or not t or b.get("o") not in cols:
            continue
        col = cols[b["o"]]
        col["n"] += 1
        for oid in t["o"] if isinstance(t["o"], list) else [t["o"]]:
            if oid in col["counts"]:
                col["counts"][oid] += 1
    return {"target": {"id": target_id, "text": target["text"]}, "by": {"id": by_id, "text": by["text"]}, "columns": [{"id": k, "text": v["text"], "n": v["n"]} for k, v in cols.items()],
            "rows": [{"id": o["id"], "text": o["text"], "cells": [{"count": cols[c]["counts"][o["id"]], "pct": round(100 * cols[c]["counts"][o["id"]] / cols[c]["n"], 1) if cols[c]["n"] else None} for c in cols]} for o in target["options"]],
            "note": "Small columns (under 30 answers) are not reliable; read them as hints."}


def public_results(row: Survey, session: Session) -> dict[str, Any] | None:
    """The aggregate results a visitor may see, or None when they may not: only choice, rating and score questions, never text answers, contact details or splits."""
    if row.results_hold or row.results_mode == "private":
        return None
    if row.results_mode == "after_close" and state_of(row) != "closed":
        return None
    n = response_count(session, row.id, include_flagged=False)
    if n < (row.min_results or 0):
        return {"waiting": True, "needed": row.min_results, "have": n}
    res = survey_results(session, row, include_flagged=False)
    keep = []
    for q in res["questions"]:
        if q["type"] in ("single", "dropdown", "multi", "rating", "nps"):
            q = {k: v for k, v in q.items() if k not in ("other_texts", "texts")}
            if "options" in q:
                q["options"] = [o for o in q["options"] if not o.get("archived") or o["count"]]
            keep.append(q)
    return {"waiting": False, "title": row.title, "n": res["totals"]["counted"], "note": res["note"], "sponsor": row.sponsor, "method_note": row.method_note, "scientific": res["scientific"],
            "first": res["totals"]["first"], "last": res["totals"]["last"], "questions": keep}


# ----------------------------------------------------------------------------------------------- export
def _label(q: dict[str, Any], a: dict[str, Any] | None) -> str:
    if not a:
        return ""
    opts = {o["id"]: o["text"] for o in q.get("options", [])}
    if "o" in a:
        vals = a["o"] if isinstance(a["o"], list) else [a["o"]]
        text = "; ".join(opts.get(v, v) for v in vals) if q["type"] != "ranking" else " > ".join(opts.get(v, v) for v in vals)
        return text + (f" ({a['t']})" if a.get("t") else "")
    if "n" in a:
        return str(a["n"])
    return a.get("t", "")


def export_rows(session: Session, row: Survey, *, include_contact: bool = False, include_flagged: bool = True) -> tuple[list[str], list[list[Any]]]:
    questions = [q for q in json.loads(row.questions_json or "[]") if q["type"] in ANSWERED]
    ist = timedelta(hours=5, minutes=30)
    fields = [f for f in (row.contact_fields or "").split(",") if f] if include_contact else []
    header = ["Response", "Time (IST)", "Seconds", "Status", "Flags"] + [f"{q['id']}: {q['text']}" for q in questions] + [f"Contact {f}" for f in fields]
    out = []
    for r, a in _rows(session, row, include_flagged, None, None):
        contact = json.loads(r.contact_json) if (fields and r.contact_json) else {}
        out.append([r.id, (_aware(r.submitted_at) + ist).strftime("%Y-%m-%d %H:%M:%S"), r.duration_seconds or "", r.status, r.flags] + [_label(q, a.get(q["id"])) for q in questions] + [contact.get(f, "") for f in fields])
    return header, out


def _safe_cell(value: Any) -> Any:
    """A cell that starts with = + - or @ would be run as a formula by a spreadsheet; a leading apostrophe-free space keeps it as text."""
    return " " + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value


def export_csv(session: Session, row: Survey, **kw: Any) -> bytes:
    header, rows = export_rows(session, row, **kw)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe_cell(c) for c in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def export_xlsx(session: Session, row: Survey, **kw: Any) -> bytes:
    from openpyxl import Workbook
    header, rows = export_rows(session, row, **kw)
    wb = Workbook()
    ws = wb.active
    ws.title = "Answers"
    ws.append(header)
    for r in rows:
        ws.append([_safe_cell(c) for c in r])
    summary = wb.create_sheet("Summary")
    res = survey_results(session, row, include_flagged=kw.get("include_flagged", True))
    summary.append(["Survey", row.title])
    summary.append(["Answers counted", res["totals"]["counted"]])
    summary.append(["Note", res["note"]])
    summary.append([])
    for q in res["questions"]:
        summary.append([f"{q['id']}: {q['text']}", f"answered by {q['n']}"])
        for o in q.get("options", []):
            summary.append(["", _safe_cell(o["text"]), o.get("count", ""), o.get("pct", "")])
        for d in q.get("distribution", []):
            summary.append(["", d["value"], d["count"], d["pct"]])
        if q.get("mean") is not None:
            summary.append(["", "mean", q["mean"], "median", q["median"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------------------------- starter kits
def demographics(language: str = "en") -> list[dict[str, Any]]:
    """Standard background questions (all optional) for splitting results by age, gender, area and place."""
    return [
        {"type": "dropdown", "text": "Your age group", "options": [{"text": t} for t in ("18-24", "25-34", "35-44", "45-54", "55-64", "65 or more", "Prefer not to say")]},
        {"type": "single", "text": "Your gender", "options": [{"text": t} for t in ("Male", "Female", "Other", "Prefer not to say")]},
        {"type": "single", "text": "Where do you live?", "options": [{"text": t} for t in ("Metro city", "Other city or town", "Village", "Prefer not to say")]},
        {"type": "dropdown", "text": "Your state or union territory", "options": [{"text": t} for t in INDIA_STATES]},
    ]


def _yn(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "single", "text": text, "required": True, "options": [{"text": "Yes"}, {"text": "No"}, {"text": "Can't say"}], **extra}


TEMPLATES: dict[str, dict[str, Any]] = {
    "quick-poll": {"title": "Quick opinion poll", "kind": "poll", "category": "opinion", "description": "One question, instant result.",
                   "intro": "", "results_mode": "after_vote", "questions": [_yn("Write your question here: do you agree with ...?")]},
    "political-poll": {"title": "Political opinion poll", "kind": "survey", "category": "political", "sampling": "self_selected", "results_mode": "private",
                       "description": "Voting intention, the issues that matter, and how people rate the government.",
                       "intro": "This is an opinion poll. Your answers are anonymous and are used only in totals.",
                       "method_note": "Who commissioned it, how people were reached, the dates, and the number of answers: write them here before any result is published.",
                       "questions": [
                           {"type": "single", "text": "If an election were held today, who would you vote for?", "required": True,
                            "options": [{"text": "Party or candidate A"}, {"text": "Party or candidate B"}, {"text": "Party or candidate C"}, {"text": "Other", "other": True}, {"text": "Undecided"}, {"text": "Prefer not to say"}]},
                           {"type": "multi", "text": "Which issues matter most to you? (choose up to 3)", "max_select": 3, "options": [{"text": t} for t in ("Jobs", "Prices", "Roads, water and electricity", "Health", "Education", "Law and order", "Farming", "Corruption", "Other")]},
                           {"type": "rating", "text": "How satisfied are you with the work of the current government?", "scale_max": 5, "label_low": "Not at all", "label_high": "Very satisfied"},
                           {"type": "single", "text": "Did you vote in the last election?", "options": [{"text": "Yes"}, {"text": "No"}, {"text": "Was not eligible"}, {"text": "Prefer not to say"}]},
                           *demographics()]},
    "brand-tracker": {"title": "Brand awareness and preference", "kind": "survey", "category": "brand", "description": "Awareness, consideration, intent and recommendation for a brand and its rivals.",
                      "intro": "A few questions about brands you know. It takes about three minutes.",
                      "questions": [
                          {"type": "text", "text": "Which brands of this kind come to mind first?", "help": "Write the first one or two that you think of."},
                          {"type": "multi", "text": "Which of these brands have you heard of?", "options": [{"text": t} for t in ("Brand A", "Brand B", "Brand C", "Brand D", "None of these")]},
                          {"type": "single", "text": "Which brand would you consider first?", "options": [{"text": t} for t in ("Brand A", "Brand B", "Brand C", "Brand D", "None of these")]},
                          {"type": "rating", "text": "How likely are you to buy from Brand A in the next three months?", "scale_max": 5, "label_low": "Very unlikely", "label_high": "Very likely"},
                          {"type": "nps", "text": "How likely are you to recommend Brand A to a friend or colleague?"},
                          *demographics()]},
    "customer-satisfaction": {"title": "Customer satisfaction and NPS", "kind": "survey", "category": "customer", "description": "Satisfaction, recommendation and what to improve.",
                              "intro": "Thank you for being our customer. Please tell us how we did.",
                              "questions": [
                                  {"type": "rating", "text": "Overall, how satisfied are you?", "required": True, "scale_max": 5, "label_low": "Very unhappy", "label_high": "Very happy"},
                                  {"type": "nps", "text": "How likely are you to recommend us to a friend or colleague?", "required": True},
                                  {"type": "multi", "text": "What should we improve?", "options": [{"text": t} for t in ("Quality", "Price", "Speed", "Support", "Ease of use", "Other")]},
                                  {"type": "longtext", "text": "Anything else you would like to tell us?"}]},
    "team-pulse": {"title": "Team pulse survey", "kind": "survey", "category": "employee", "description": "A short anonymous check on workload, leadership, tools and purpose.",
                   "intro": "This survey is anonymous. Results are shown only for groups large enough to protect each person.",
                   "questions": [
                       {"type": "rating", "text": "My workload is manageable.", "required": True, "scale_max": 5, "label_low": "Strongly disagree", "label_high": "Strongly agree"},
                       {"type": "rating", "text": "I get the support I need from my leaders.", "required": True, "scale_max": 5, "label_low": "Strongly disagree", "label_high": "Strongly agree"},
                       {"type": "rating", "text": "I have the tools I need to do my work well.", "scale_max": 5, "label_low": "Strongly disagree", "label_high": "Strongly agree"},
                       {"type": "nps", "text": "How likely are you to recommend this team as a place to work?"},
                       {"type": "longtext", "text": "What one thing would make work better?"}]},
    "media-habits": {"title": "Media habits survey", "kind": "survey", "category": "media", "description": "Where people watch news, for how long, and whom they trust.",
                     "intro": "Tell us how you watch news and videos. Your answers are anonymous.",
                     "questions": [
                         {"type": "multi", "text": "Where do you watch news? (choose all that apply)", "options": [{"text": t} for t in ("TV", "YouTube", "Facebook", "Instagram", "X", "News websites and apps", "Newspapers", "WhatsApp forwards", "Other", "I do not follow news")]},
                         {"type": "single", "text": "How much time do you spend on news in a day?", "options": [{"text": t} for t in ("Less than 15 minutes", "15 to 30 minutes", "30 to 60 minutes", "1 to 2 hours", "More than 2 hours")]},
                         {"type": "rating", "text": "How much do you trust the news you see online?", "scale_max": 5, "label_low": "Not at all", "label_high": "Completely"},
                         {"type": "ranking", "text": "Rank these by how often you use them for news (1 is the most)", "options": [{"text": t} for t in ("TV", "YouTube", "Social media", "Websites and apps", "Newspapers")]},
                         *demographics()]},
}


def template_list() -> list[dict[str, str]]:
    return [{"key": k, "title": v["title"], "kind": v["kind"], "category": v["category"], "description": v["description"], "questions": len([q for q in v["questions"] if q["type"] in ANSWERED])} for k, v in TEMPLATES.items()]


def from_template(key: str) -> dict[str, Any]:
    """A ready draft to start from (never saved by itself): the administrator reads, edits and saves it."""
    t = TEMPLATES.get(key)
    if t is None:
        raise LookupError("that starter does not exist")
    return json.loads(json.dumps(t))


def list_responses(session: Session, row: Survey, *, page: int = 1, size: int = 50, status: str = "", include_contact: bool = False) -> dict[str, Any]:
    """One page of the individual answers, newest first, for reading and for removing the ones that should not count."""
    questions = {q["id"]: q for q in json.loads(row.questions_json or "[]")}
    query = session.query(SurveyResponse).filter(SurveyResponse.survey_id == row.id)
    if status in ("valid", "flagged", "removed"):
        query = query.filter(SurveyResponse.status == status)
    total = query.count()
    ist = timedelta(hours=5, minutes=30)
    items = []
    for r in query.order_by(SurveyResponse.id.desc()).offset(max(0, page - 1) * size).limit(size).all():
        a = json.loads(r.answers_json or "{}")
        items.append({"id": r.id, "time": (_aware(r.submitted_at) + ist).strftime("%d %b %Y %H:%M"), "seconds": r.duration_seconds, "status": r.status, "flags": r.flags,
                      "answers": {qid: _label(questions[qid], v) for qid, v in a.items() if qid in questions}, **({"contact": json.loads(r.contact_json)} if include_contact and r.contact_json else {})})
    return {"total": total, "page": page, "size": size, "responses": items}
