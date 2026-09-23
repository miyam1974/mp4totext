"""QSettings persistence for processing history; keep the existing v1 data format."""

import json
from dataclasses import asdict

from PySide6.QtCore import QSettings

from mp4totext.domain.processing_history import ProcessingMetrics, retain_history

_HISTORY_KEY = "processing/history/v1"


def load_history(settings: QSettings) -> tuple[ProcessingMetrics, ...]:
    raw = str(settings.value(_HISTORY_KEY, "", type=str))
    if not raw:
        return ()
    try:
        records = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(records, list):
        return ()
    samples: list[ProcessingMetrics] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("model_name"), str):
            continue
        try:
            sample = ProcessingMetrics(
                model_name=record["model_name"],
                file_size_bytes=int(record["file_size_bytes"]),
                elapsed_seconds=float(record["elapsed_seconds"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        samples.append(sample)
    return retain_history(tuple(samples))


def append_history(settings: QSettings, sample: ProcessingMetrics) -> None:
    retained = retain_history((*load_history(settings), sample))
    settings.setValue(
        _HISTORY_KEY, json.dumps([asdict(item) for item in retained], allow_nan=False),
    )
