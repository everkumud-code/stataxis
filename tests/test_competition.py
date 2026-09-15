from metrics.competition import CompetitionPoint, build_competition, compare_head_to_head, summarize_competition


def test_competition_ranks_by_value_and_preserves_missing_values():
    standings = build_competition([CompetitionPoint("b", "Beta", 800), CompetitionPoint("a", "Alpha", 1000), CompetitionPoint("c", "Gamma", None)])
    assert [item.channel_id for item in standings] == ["a", "b", "c"]
    assert [item.rank for item in standings] == [1, 2, None]
    assert standings[2].share is None


def test_equal_values_use_competition_ranking():
    standings = build_competition([CompetitionPoint("a", "Alpha", 100), CompetitionPoint("b", "Beta", 100), CompetitionPoint("c", "Gamma", 50)])
    assert [item.rank for item in standings] == [1, 1, 3]


def test_share_is_relative_to_comparison_set():
    standings = build_competition([CompetitionPoint("a", "Alpha", 600), CompetitionPoint("b", "Beta", 400)])
    assert standings[0].share == 60
    assert standings[1].share == 40
    assert sum(item.share for item in standings if item.share is not None) == 100


def test_rank_share_and_gap_changes_are_calculated_from_previous_window():
    previous = [CompetitionPoint("a", "Alpha", 600), CompetitionPoint("b", "Beta", 400)]
    current = [CompetitionPoint("a", "Alpha", 500), CompetitionPoint("b", "Beta", 700)]
    standings = build_competition(current, previous)
    alpha = next(item for item in standings if item.channel_id == "a")
    beta = next(item for item in standings if item.channel_id == "b")
    assert (alpha.rank, alpha.previous_rank, alpha.rank_change) == (2, 1, -1)
    assert alpha.share_change == -18.333333333333
    assert (alpha.gap_to_leader, alpha.previous_gap_to_leader, alpha.gap_change) == (200, 0, 200)
    assert (beta.rank, beta.previous_rank, beta.rank_change) == (1, 2, 1)
    assert beta.share_change == 18.333333333333


def test_gap_change_can_show_a_channel_closing_the_gap():
    previous = [CompetitionPoint("a", "Alpha", 400), CompetitionPoint("b", "Beta", 600)]
    current = [CompetitionPoint("a", "Alpha", 550), CompetitionPoint("b", "Beta", 600)]
    alpha = next(item for item in build_competition(current, previous) if item.channel_id == "a")
    assert (alpha.gap_to_leader, alpha.previous_gap_to_leader, alpha.gap_change) == (50, 200, -150)


def test_momentum_rank_is_independent_of_audience_rank():
    standings = build_competition([CompetitionPoint("a", "Alpha", 1000, momentum=2), CompetitionPoint("b", "Beta", 800, momentum=5), CompetitionPoint("c", "Gamma", 600, momentum=None)])
    assert next(item for item in standings if item.channel_id == "a").momentum_rank == 2
    assert next(item for item in standings if item.channel_id == "b").momentum_rank == 1
    assert next(item for item in standings if item.channel_id == "c").momentum_rank is None


def test_zero_total_has_no_share_signal():
    standings = build_competition([CompetitionPoint("a", "Alpha", 0), CompetitionPoint("b", "Beta", 0)])
    assert all(item.share is None for item in standings)
    assert all(item.gap_to_leader == 0 for item in standings)


def test_head_to_head_reports_value_and_momentum_leaders():
    result = compare_head_to_head([CompetitionPoint("a", "Alpha", 1200, momentum=4), CompetitionPoint("b", "Beta", 900, momentum=7)], "a", "b")
    assert result.value_leader == "a"
    assert result.value_gap == 300
    assert result.momentum_leader == "b"
    assert result.momentum_gap == 3


def test_head_to_head_preserves_ties_as_no_leader():
    result = compare_head_to_head([CompetitionPoint("a", "Alpha", 100, momentum=5), CompetitionPoint("b", "Beta", 100, momentum=5)], "a", "b")
    assert result.value_leader is None
    assert result.value_gap == 0
    assert result.momentum_leader is None
    assert result.momentum_gap == 0


def test_head_to_head_does_not_invent_missing_values():
    result = compare_head_to_head([CompetitionPoint("a", "Alpha", None, momentum=5), CompetitionPoint("b", "Beta", 100, momentum=None)], "a", "b")
    assert result.value_leader is None
    assert result.value_gap is None
    assert result.momentum_leader is None
    assert result.momentum_gap is None


def test_head_to_head_rejects_unknown_channel():
    try:
        compare_head_to_head([CompetitionPoint("a", "Alpha", 100)], "a", "missing")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_competitive_summary_identifies_top_movers_and_leaders():
    previous = [CompetitionPoint("a", "Alpha", 900, momentum=2), CompetitionPoint("b", "Beta", 700, momentum=5), CompetitionPoint("c", "Gamma", 400, momentum=1)]
    current = [CompetitionPoint("a", "Alpha", 700, momentum=3), CompetitionPoint("b", "Beta", 1000, momentum=8), CompetitionPoint("c", "Gamma", 300, momentum=2)]
    summary = summarize_competition(build_competition(current, previous))
    assert summary.leader_id == "b"
    assert summary.momentum_leader_id == "b"
    assert summary.biggest_rank_gainer_id == "b"
    assert summary.biggest_rank_loser_id == "a"
    assert summary.biggest_share_gainer_id == "b"
    assert summary.biggest_share_loser_id == "a"
    assert summary.biggest_gap_closer_id == "b"
    assert summary.biggest_gap_widener_id == "a"
    assert summary.channels_with_data == 3


def test_competitive_summary_does_not_force_a_tied_extreme():
    previous = [CompetitionPoint("a", "Alpha", 500), CompetitionPoint("b", "Beta", 400), CompetitionPoint("c", "Gamma", 300)]
    current = [CompetitionPoint("a", "Alpha", 400), CompetitionPoint("b", "Beta", 300), CompetitionPoint("c", "Gamma", 200)]
    summary = summarize_competition(build_competition(current, previous))
    assert summary.biggest_rank_gainer_id is None
    assert summary.biggest_rank_loser_id is None


def test_competitive_summary_handles_no_ranked_channels():
    summary = summarize_competition(build_competition([CompetitionPoint("a", "Alpha", None, momentum=None)]))
    assert summary.leader_id is None
    assert summary.momentum_leader_id is None
    assert summary.channels_with_data == 0
