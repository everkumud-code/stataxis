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


def _district_form():
    return [
        {"id": "q1", "type": "dropdown", "text": "District", "required": True, "options": [{"id": "o1", "text": "Lucknow"}, {"id": "o2", "text": "Agra"}]},
        {"id": "q2", "type": "dropdown", "text": "Constituency", "required": True, "depends_on": "q1", "options": [
            {"id": "o1", "text": "Lucknow West", "group": "o1"}, {"id": "o2", "text": "Lucknow East", "group": "o1"}, {"id": "o3", "text": "Agra Cantt.", "group": "o2"}]},
    ]


def test_a_dropdown_can_list_only_the_options_of_the_district_chosen_before():
    questions = sc.clean_questions(_district_form())
    assert questions[1]["depends_on"] == "q1" and [o["group"] for o in questions[1]["options"]] == ["o1", "o1", "o2"]
    assert sc.validate_answers(questions, {"q1": {"o": "o1"}, "q2": {"o": "o2"}}) == {"q1": {"o": "o1"}, "q2": {"o": "o2"}}
    with pytest.raises(sc.AnswerError):                          # an Agra constituency under Lucknow is refused
        sc.validate_answers(questions, {"q1": {"o": "o1"}, "q2": {"o": "o3"}})
    with pytest.raises(sc.AnswerError):                          # no district, so the constituency is not asked and the district is missing
        sc.validate_answers(questions, {"q2": {"o": "o1"}})


def test_the_dependency_must_point_at_an_earlier_choice_and_every_option_needs_its_group():
    bad = _district_form()
    bad[1]["options"][0]["group"] = "o9"
    with pytest.raises(ValueError, match="belong to one answer"):
        sc.clean_questions(bad)
    bad = _district_form()
    bad[1]["depends_on"] = "q7"
    with pytest.raises(ValueError, match="earlier one-choice or dropdown"):
        sc.clean_questions(bad)
    plain = _district_form()
    del plain[1]["depends_on"]
    assert all("group" not in o for o in sc.clean_questions(plain)[1]["options"])      # a group means nothing without the dependency
