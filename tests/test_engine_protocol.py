import pytest

from mp4totext.engine import CancellationToken, TranscriptionCancelled


def test_cancellation_token_raises_after_cancel() -> None:
    token = CancellationToken()
    assert not token.is_cancelled

    token.cancel()

    assert token.is_cancelled
    with pytest.raises(TranscriptionCancelled):
        token.raise_if_cancelled()
