import json

import pytest

from mp4totext.domain import Segment, Transcript
from mp4totext.output import render_json, render_text, summarize


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


def test_render_text_prepends_summary(transcript: Transcript) -> None:
    assert render_text(transcript, "短い要約です。") == (
        "【要約】\n短い要約です。\n\n【文字起こし】\n最初の行\n次の行\n"
    )


def test_render_json(transcript: Transcript) -> None:
    document = json.loads(render_json(transcript))
    assert document["schema_version"] == 2
    assert document["summary"] is None
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


def test_summarize_selects_sentences_from_the_whole_text() -> None:
    text = "導入です。重要な議題を確認します。重要な議題を決定します。終了します。"

    summary = summarize(text, max_sentences=2)

    assert summary
    assert summary in text or all(sentence in text for sentence in summary.splitlines())
