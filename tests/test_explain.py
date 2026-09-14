from metrics.explain import explain_index
from metrics.stx_index import STXSignals, calculate_stx_index


def test_explanation_is_sorted_by_score_impact():
    result = calculate_stx_index(STXSignals(audience=90, growth=60, momentum=50))
    explanation = explain_index(result)
    assert [item.name for item in explanation] == ["audience", "growth", "momentum"]
    assert sum(item.weighted_contribution for item in explanation) == result.score
    assert sum(item.share_of_score for item in explanation) == 100


def test_explanation_is_empty_without_index_score():
    result = calculate_stx_index(STXSignals())
    assert explain_index(result) == ()
