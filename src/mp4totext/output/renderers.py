import json

from mp4totext.domain import Transcript

SCHEMA_VERSION = 2


def render_text(transcript: Transcript, summary: str | None = None) -> str:
    text = transcript.text
    if summary:
        return f"【要約】\n{summary}\n\n【文字起こし】\n{text}\n"
    return f"{text}\n" if text else ""


def render_json(transcript: Transcript, summary: str | None = None) -> str:
    document = {
        "schema_version": SCHEMA_VERSION,
        "summary": summary,
        "language": transcript.language,
        "language_probability": transcript.language_probability,
        "duration_seconds": transcript.duration_seconds,
        "text": transcript.text,
        "segments": [
            {
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text.strip(),
            }
            for segment in transcript.segments
        ],
        "metadata": dict(transcript.metadata),
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
