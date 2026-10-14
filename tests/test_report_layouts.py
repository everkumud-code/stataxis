"""The one-pager and the booklet, for every interval a client may choose, in the StatAxis design."""
import pytest

pytest.importorskip("reportlab")
fitz = pytest.importorskip("fitz")

from api.report_layouts import INTERVALS, booklet, one_pager, sample_content  # noqa: E402


def text_of(pdf: bytes) -> str:
    return " ".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))


def test_every_interval_has_a_one_pager_on_one_page_and_a_booklet_with_the_stx_first():
    assert list(INTERVALS) == ["daily", "weekly", "fortnightly", "monthly", "quarterly", "half-yearly", "yearly"]
    for interval in INTERVALS:
        c = sample_content(interval)
        assert c["sample"] is True and c["stx"]["leader"] and c["period"] and len(c["ranking"]) == 8 and all(r["stx"] for r in c["ranking"])
        one = fitz.open(stream=one_pager(c), filetype="pdf")
        assert len(one) == 1, interval                                                                    # a one-pager is one page
        t = text_of(one_pager(c)).lower()
        assert "stx index" in t and c["stx"]["leader"].lower() in t and "stataxis viewpoint" in t and "what stands out" in t and "sample" in t and "x.com/stataxis" in t
        book = fitz.open(stream=booklet(c, prepared_for="client@example.com"), filetype="pdf")
        assert 5 <= len(book) <= 8, interval
        bt = text_of(booklet(c)).lower()
        for part in ("at a glance", "detailed findings", "the data, period by period", "observations", "how these numbers were worked out", "stataxis viewpoint"):
            assert part in bt, (interval, part)


def test_the_sample_is_deterministic_and_says_it_is_illustrative():
    assert sample_content("weekly") == sample_content("weekly") and sample_content("weekly") != sample_content("monthly")
    assert "SAMPLE" in text_of(one_pager(sample_content("daily"))) and "illustrative" in text_of(one_pager(sample_content("daily")))
    assert all(r["name"].startswith("Sample") for r in sample_content("yearly")["ranking"])               # fictional channels, never a real channel with invented figures
