import json

import pytest

from mp4totext.domain import Segment, Transcript
from mp4totext.output import render_json, render_text


@pytest.fixture
def transcript() -> Transcript:
    return Transcript(
        language="ja",
        language_probability=0.98,
        duration_seconds=65.432,
        segments=(
            Segment(0.0, 1.2346, " 最初の行 "),
            Segment(61.001, 65.432, "次の行"),
        ),
        metadata={"model": "small"},
    )


def test_render_text(transcript: Transcript) -> None:
    assert render_text(transcript) == "最初の行\n次の行\n"


def test_render_json(transcript: Transcript) -> None:
    document = json.loads(render_json(transcript))
    assert document["schema_version"] == 3
    assert document["language"] == "ja"
    assert document["text"] == "最初の行\n次の行"
    assert document["segments"][0] == {
        "start_seconds": 0.0,
        "end_seconds": 1.2346,
        "text": "最初の行",
    }


def test_segment_rejects_invalid_time_range() -> None:
    with pytest.raises(ValueError):
        Segment(2.0, 1.0, "invalid")
