import pytest

from shouldercheck.memory.stats import mcnemar_exact, median, wilson


@pytest.mark.parametrize(
    ("a", "b", "p"),
    [(15, 5, 0.041), (5, 15, 0.041), (33, 17, 0.033), (32, 18, 0.065), (0, 0, 1.0), (3, 3, 1.0)],
)
def test_mcnemar_matches_values_computed_by_hand(a, b, p):
    assert round(mcnemar_exact(a, b), 3) == p


def test_mcnemar_clears_0_05_first_at_33_17_for_50_discordant_pairs():
    cleared = [a for a in range(25, 51) if mcnemar_exact(a, 50 - a) < 0.05]
    assert min(cleared) == 33


def test_wilson_interval_of_five_in_twenty():
    low, high = wilson(5, 20)
    assert (round(low, 2), round(high, 2)) == (0.11, 0.47)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(10, 10)[1] == 1.0


def test_median():
    assert median([]) is None
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 10.0]) == 2.5
