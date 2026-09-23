from pathlib import Path

from mp4totext.application.queue import QueueState, TranscriptionQueue


def test_claimed_file_cannot_be_removed_or_moved_before_ui_receives_event() -> None:
    first, second = Path("first.mp4"), Path("second.mp4")
    queue = TranscriptionQueue((first, second))
    assert queue.claim_next() == first
    assert not queue.remove(first)
    assert not queue.move(second, -1)
    assert not queue.reorder_pending((second, first))
    assert queue.pending() == (second,)
    assert queue.snapshot()[0].state is QueueState.ACTIVE


def test_pending_move_changes_actual_claim_order() -> None:
    first, second, third = (Path(f"{name}.mp4") for name in ("first", "second", "third"))
    queue = TranscriptionQueue((first, second, third))
    assert queue.claim_next() == first
    assert queue.move(third, -1)
    assert queue.claim_next() == third
    assert queue.claim_next() == second


def test_late_addition_and_duplicate_active_file() -> None:
    source, late = Path("first.mp4"), Path("late.mp4")
    queue = TranscriptionQueue((source,))
    assert queue.claim_next() == source
    queue.add((source, source))
    assert queue.pending() == ()
    queue.set_state(source, QueueState.COMPLETED)
    assert queue.claim_next() is None
    queue.add((late, late))
    assert queue.claim_next() == late
    assert len(queue.snapshot()) == 2
