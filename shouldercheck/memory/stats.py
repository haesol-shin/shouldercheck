"""The two statistics the measures use, in the standard library only."""

from math import comb, sqrt

Z95 = 1.96


def wilson(hits: int, total: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval of a share; (0, 1) when there is nothing to count."""
    if total <= 0:
        return 0.0, 1.0
    share = hits / total
    denom = 1 + z * z / total
    centre = (share + z * z / (2 * total)) / denom
    half = z * sqrt(share * (1 - share) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact p-value of paired hits: `only_a` pairs A hit and B missed, `only_b` the
    reverse. Binomial with p 0.5 over the discordant pairs."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    low = min(only_a, only_b)
    tail = sum(comb(n, i) for i in range(low + 1))
    return min(1.0, 2 * tail / 2**n)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
