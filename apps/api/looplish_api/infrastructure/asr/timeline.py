from __future__ import annotations

from collections.abc import Iterable

from looplish_api.domain.errors import ProcessingFailure
from looplish_api.domain.models import Transcript, Word

MIN_WORD_SECONDS = 0.001
# 识别器给出的原始词：开始、结束、文本、置信度。
RawWord = tuple[float, float, str, float | None]


def build_transcript(
    raw_words: Iterable[RawWord],
    language: str | None,
    duration: float,
    source: str,
) -> Transcript:
    # 识别器偶尔给出零时长、时间倒退或越过音频末尾的词；逐个修正，而不是让一个词拖垮整次识别。
    words: list[Word] = []
    previous_start = 0.0
    for start, end, text, probability in raw_words:
        if not text.strip():
            continue
        start = max(start, previous_start)
        if duration - start < MIN_WORD_SECONDS:
            continue
        end = min(duration, max(end, start + MIN_WORD_SECONDS))
        # 切句按原文拼接词文本，词与词之间的空格由词自己携带。
        spaced = text if text[0].isspace() else f" {text}"
        words.append(Word(start, end, spaced, probability))
        previous_start = start
    if not words:
        raise ProcessingFailure("TRANSCRIPTION_FAILED", "识别结果缺少词级时间戳。", 502)
    return Transcript(tuple(words), language, duration, source)
