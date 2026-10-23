"""A dropdown is a list to search (75 districts, 403 constituencies), so it may hold far more options than a list of buttons."""
import pytest

from api import survey_core as sc


def _question(kind, count):
    return [{"id": "q1", "type": kind, "text": "Pick one", "options": [{"text": f"Option {i}"} for i in range(count)]}]


def test_a_dropdown_can_list_seventy_five_districts_and_four_hundred_and_three_constituencies():
    assert len(sc.clean_questions(_question("dropdown", 75))[0]["options"]) == 75
    assert len(sc.clean_questions(_question("dropdown", 403))[0]["options"]) == 403


def test_buttons_keep_their_limit_and_a_dropdown_has_one_too():
    for kind in ("single", "multi"):
        with pytest.raises(ValueError, match="at most 60 options"):
            sc.clean_questions(_question(kind, 61))
    with pytest.raises(ValueError, match="at most 500 options"):
        sc.clean_questions(_question("dropdown", 501))
