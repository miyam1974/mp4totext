from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from threading import Lock


class QueueState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QueueItem:
    source: Path
    state: QueueState = QueueState.PENDING


class TranscriptionQueue:
    """One ordered queue shared by the UI and worker; mutations are atomic."""

    def __init__(self, sources: tuple[Path, ...] = ()) -> None:
        self._lock = Lock()
        self._items = [QueueItem(source) for source in dict.fromkeys(sources)]

    def snapshot(self) -> tuple[QueueItem, ...]:
        with self._lock:
            return tuple(self._items)

    def pending(self) -> tuple[Path, ...]:
        return tuple(item.source for item in self.snapshot() if item.state is QueueState.PENDING)

    def add(self, sources: tuple[Path, ...]) -> None:
        with self._lock:
            known = {item.source for item in self._items}
            for source in sources:
                if source not in known:
                    self._items.append(QueueItem(source))
                    known.add(source)

    def claim_next(self) -> Path | None:
        with self._lock:
            for index, item in enumerate(self._items):
                if item.state is QueueState.PENDING:
                    self._items[index] = replace(item, state=QueueState.ACTIVE)
                    return item.source
            return None

    def set_state(self, source: Path, state: QueueState) -> None:
        with self._lock:
            for index, item in enumerate(self._items):
                if item.source == source:
                    self._items[index] = replace(item, state=state)
                    return

    def remove(self, source: Path, *, pending_only: bool = False) -> bool:
        with self._lock:
            for index, item in enumerate(self._items):
                if item.source == source and item.state is not QueueState.ACTIVE:
                    if pending_only and item.state is not QueueState.PENDING:
                        return False
                    self._items.pop(index)
                    return True
            return False

    def move(self, source: Path, offset: int) -> bool:
        with self._lock:
            index = next((i for i, item in enumerate(self._items) if item.source == source), -1)
            target = index + offset
            if index < 0 or not 0 <= target < len(self._items):
                return False
            if any(self._items[i].state is not QueueState.PENDING for i in (index, target)):
                return False
            self._items[index], self._items[target] = self._items[target], self._items[index]
            return True

    def reorder_pending(self, sources: tuple[Path, ...]) -> bool:
        with self._lock:
            indices = [i for i, item in enumerate(self._items) if item.state is QueueState.PENDING]
            if len(sources) != len(indices) or set(sources) != {
                self._items[i].source for i in indices
            }:
                return False
            for index, source in zip(indices, sources, strict=True):
                self._items[index] = QueueItem(source)
            return True
