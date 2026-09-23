import pytest

from mp4totext.domain.processing_history import (
    ProcessingMetrics,
    estimate_seconds,
    retain_history,
)


def test_estimate_uses_model_specific_median_rate() -> None:
    history = (
        ProcessingMetrics("small", 1000, 10.0),
        ProcessingMetrics("small", 1000, 20.0),
        ProcessingMetrics("tiny", 1000, 1.0),
    )

    assert estimate_seconds("small", 2000, history) == pytest.approx(30.0)
    assert estimate_seconds("medium", 2000, history) is None


@pytest.mark.parametrize("elapsed", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_samples_do_not_affect_estimates(elapsed: float) -> None:
    valid = ProcessingMetrics("small", 1000, 10.0)
    history = (valid, ProcessingMetrics("small", 1000, elapsed))
    assert retain_history(history) == (valid,)
    assert estimate_seconds("small", 2000, history) == pytest.approx(20.0)
    assert estimate_seconds("small", 0, history) is None


def test_retention_keeps_latest_twenty_per_model_in_original_order() -> None:
    history = tuple(
        ProcessingMetrics(model, 1000, float(index + 1))
        for index in range(25)
        for model in ("small", "tiny")
    )
    assert retain_history(history) == history[10:]
