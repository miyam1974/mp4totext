import re
from collections import Counter

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])\s*|\n+")


def summarize(text: str, max_sentences: int = 3) -> str:
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(text)
        if sentence.strip()
    ]
    if len(sentences) <= max_sentences:
        return "".join(sentences)

    frequencies = Counter(
        sentence[index : index + 2]
        for sentence in sentences
        for index in range(max(len(sentence) - 1, 0))
        if not sentence[index : index + 2].isspace()
    )
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            -sum(frequencies[item[1][index : index + 2]] for index in range(len(item[1]) - 1))
            / max(len(item[1]), 1),
            item[0],
        ),
    )[:max_sentences]
    return "\n".join(sentence for _, sentence in sorted(ranked))