from metrics.competition import CompetitionPoint, build_competition


def test_competition_ranks_by_value_and_preserves_missing_values():
    standings = build_competition(
        [
            CompetitionPoint("b", "Beta", 800),
            CompetitionPoint("a", "Alpha", 1000),
            CompetitionPoint("c", "Gamma", None),
        ]
    )

    assert [item.channel_id for item in standings] == ["a", "b", "c"]
    assert [item.rank for item in standings] == [1, 2, None]
    assert standings[2].share is None


def test_equal_values_use_competition_ranking():
    standings = build_competition(
        [
            CompetitionPoint("a", "Alpha", 100),
            CompetitionPoint("b", "Beta", 100),
            CompetitionPoint("c", "Gamma", 50),
        ]
    )

    assert [item.rank for item in standings] == [1, 1, 3]


def test_share_is_relative_to_comparison_set():
    standings = build_competition(
        [
            CompetitionPoint("a", "Alpha", 600),
            CompetitionPoint("b", "Beta", 400),
        ]
    )

    assert standings[0].share == 60
    assert standings[1].share == 40
    assert sum(item.share for item in standings if item.share is not None) == 100


def test_rank_share_and_gap_changes_are_calculated_from_previous_window():
    previous = [
        CompetitionPoint("a", "Alpha", 600),
        CompetitionPoint("b", "Beta", 400),
    ]
    current = [
        CompetitionPoint("a", "Alpha", 500),
        CompetitionPoint("b", "Beta", 700),
    ]

    standings = build_competition(current, previous)
    alpha = next(item for item in standings if item.channel_id == "a")
    beta = next(item for item in standings if item.channel_id == "b")

    assert alpha.rank == 2
    assert alpha.previous_rank == 1
    assert alpha.rank_change == -1
    assert alpha.share_change == -10
    assert alpha.gap_to_leader == 200
    assert alpha.previous_gap_to_leader == 200
    assert alpha.gap_change == 0

    assert beta.rank == 1
    assert beta.previous_rank == 2
    assert beta.rank_change == 1
    assert beta.share_change == 10
    assert beta.gap_to_leader == 0
    assert beta.previous_gap_to_leader == 0
    assert beta.gap_change == 0


def test_gap_change_can_show_a_channel_closing_the_gap():
    previous = [
        CompetitionPoint("a", "Alpha", 400),
        CompetitionPoint("b", "Beta", 600),
    ]
    current = [
        CompetitionPoint("a", "Alpha", 550),
        CompetitionPoint("b", "Beta", 600),
    ]

    alpha = next(item for item in build_competition(current, previous) if item.channel_id == "a")

    assert alpha.gap_to_leader == 50
    assert alpha.previous_gap_to_leader == 200
    assert alpha.gap_change == -150


def test_momentum_rank_is_independent_of_audience_rank():
    standings = build_competition(
        [
            CompetitionPoint("a", "Alpha", 1000, momentum=2),
            CompetitionPoint("b", "Beta", 800, momentum=5),
            CompetitionPoint("c", "Gamma", 600, momentum=None),
        ]
    )

    alpha = next(item for item in standings if item.channel_id == "a")
    beta = next(item for item in standings if item.channel_id == "b")
    gamma = next(item for item in standings if item.channel_id == "c")

    assert alpha.momentum_rank == 2
    assert beta.momentum_rank == 1
    assert gamma.momentum_rank is None


def test_zero_total_has_no_share_or_gap_signal():
    standings = build_competition(
        [
            CompetitionPoint("a", "Alpha", 0),
            CompetitionPoint("b", "Beta", 0),
        ]
    )

    assert all(item.share is None for item in standings)
    assert all(item.gap_to_leader == 0 for item in standings)
