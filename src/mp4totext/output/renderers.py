import json

from mp4totext.domain import Transcript

SCHEMA_VERSION = 3


def render_text(transcript: Transcript) -> str:
    text = transcript.text
    return f"{text}\n" if text else ""


def render_json(transcript: Transcript) -> str:
    document = {
        "schema_version": SCHEMA_VERSION,
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
