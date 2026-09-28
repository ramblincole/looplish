from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from looplish_api.domain.models import Transcript, Word

CUE_TIME = re.compile(
    r"(?P<start>(?:\d+:)?\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d+:)?\d{2}:\d{2}[,.]\d{3})"
)
TAG = re.compile(r"<[^>]+>")
SUBTITLE_SUFFIXES = {".srt", ".vtt"}


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def select_subtitle(paths: Sequence[Path], languages: tuple[str, ...]) -> Path | None:
    # 先稳定排序，再按用户语言偏好匹配，保证相同输入始终选择同一文件。
    candidates = sorted(
        (path for path in paths if path.suffix.casefold() in SUBTITLE_SUFFIXES),
        key=lambda path: path.name.casefold(),
    )
    for language in languages:
        marker = f".{language.casefold()}."
        match = next((path for path in candidates if marker in path.name.casefold()), None)
        if match is not None:
            return match
    if not candidates:
        return None
    # 没有语言匹配时选内容最多的字幕；大小相同按文件名，结果依旧确定。
    return min(candidates, key=lambda path: (-path.stat().st_size, path.name.casefold()))


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    hours, minutes, rest = ("0", *parts) if len(parts) == 2 else parts
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def _cues(content: str) -> list[Cue]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[Cue] = []
    index = 0
    while index < len(lines):
        match = CUE_TIME.search(lines[index])
        if match is None:
            index += 1
            continue
        # 时间行之后直到空行都属于当前 cue；样式标签不进入转写文本。
        text: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text.append(html.unescape(TAG.sub("", lines[index])).strip())
            index += 1
        value = " ".join(part for part in text if part)
        if value:
            cues.append(Cue(_seconds(match["start"]), _seconds(match["end"]), value))
    return cues


def _interpolate(cue: Cue) -> list[Word]:
    tokens = cue.text.split()
    # 用字符数分配 cue 时长；最小权重避免空白或极短 token 得到零时长。
    weights = [max(1, len(token)) for token in tokens]
    total = sum(weights)
    duration = max(0.001, cue.end - cue.start)
    elapsed = 0.0
    words: list[Word] = []
    for token, weight in zip(tokens, weights, strict=True):
        start = cue.start + duration * elapsed / total
        elapsed += weight
        end = cue.start + duration * elapsed / total
        words.append(Word(start, max(start + 0.001, end), f" {token}"))
    return words


def parse_subtitle(path: Path, duration: float) -> Transcript:
    parsed = _cues(path.read_text(encoding="utf-8-sig"))
    words: list[Word] = []
    previous_end = 0.0
    for cue in parsed:
        for word in _interpolate(cue):
            # 与上一词对齐并夹在媒体时长内，修正重叠 cue 和越界尾词。
            start = max(previous_end, word.start)
            if duration - start < 0.001:
                break
            end = min(duration, max(start + 0.001, word.end))
            words.append(Word(start, end, word.text))
            previous_end = end
    if not words:
        raise ValueError("subtitle contains no usable words")
    return Transcript(tuple(words), None, duration, f"subtitle:{path.name}")
