from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise

from looplish_api.domain.models import TIMELINE_TOLERANCE, SegmentationOptions, Sentence, Word

TERMINAL = re.compile(r"[?!。！？]$|(?<!\.)\.$")
CLAUSE = re.compile(r"[,;:，；：]$")
# 右双引号、右单引号用转义书写，避免与普通引号混淆。
CLOSING = "\"'\u201d\u2019)]）」』"
ABBREVIATIONS = {
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "prof.",
    "sr.",
    "jr.",
    "e.g.",
    "i.e.",
    "u.s.",
}
# 人名首字母只认大写；代词 `I.` 通常就是句末，不当作首字母。
INITIAL = re.compile(r"^[A-HJ-Z]\.$")
INTERNAL_DOTS = re.compile(r"^(?:[A-Za-z]\.){2,}$")
DECIMAL_HEAD = re.compile(r"\d\.$")
# 平均每 40 词至少一个句末标点才算有标点；更稀疏时句末信号不可靠，只能按停顿切。
PUNCTUATION_DENSITY = 40
# 句末标点在 20 词以内（左右各算）的词才算处在有标点的区域，与每 40 词一个句末的密度相对应；
# 一份转写里可能前半有标点、后半一长段没有，不能整份只判断一次。
PUNCTUATION_WINDOW = PUNCTUATION_DENSITY // 2
# 兜底拆分只在真实停顿或子句标点处下刀；紧挨着的两个词之间多半是连读，切下去会削掉音节。
MIN_SPLIT_PAUSE = 0.15


def _is_terminal(words: Sequence[Word], index: int) -> bool:
    stripped = words[index].text.strip()
    current = stripped.lower()
    # 缩写、首字母和内部点号优先于句号规则，避免误切。
    if current in ABBREVIATIONS or INITIAL.fullmatch(stripped) or INTERNAL_DOTS.fullmatch(current):
        return False
    # 引号、括号包住的句末标点（如 `"Stop!"`）同样结束句子。
    current = current.rstrip(CLOSING)
    if not TERMINAL.search(current):
        return False
    if current.endswith(".") and index + 1 < len(words):
        pause = words[index + 1].start - words[index].end
        next_text = words[index + 1].text.lstrip()
        # 小数被拆成 `3.` 与 `14` 两个 token 时，句号属于数字。
        if DECIMAL_HEAD.search(current) and next_text[:1].isdigit():
            return False
        if next_text[:1].islower() and pause < 0.25:
            return False
    return True


def _can_cut(words: Sequence[Word], index: int) -> bool:
    # 只在不重叠的词之间断开；否则相邻切片无法既包住语音又互不重叠。
    return index + 1 >= len(words) or words[index + 1].start >= words[index].end


def is_punctuated(words: Sequence[Word]) -> bool:
    cleaned = tuple(word for word in words if word.text.strip())
    if not cleaned:
        return False
    terminals = sum(1 for index in range(len(cleaned)) if _is_terminal(cleaned, index))
    return terminals * PUNCTUATION_DENSITY >= len(cleaned)


def _locally_punctuated(words: Sequence[Word]) -> tuple[bool, ...]:
    # 前后各扫一遍求到最近句末的距离，O(n) 而不是对每个词再去找窗口内的句末。
    size = len(words)
    unreachable = size + PUNCTUATION_WINDOW + 1
    nearest = [unreachable] * size
    last: int | None = None
    for index in range(size):
        if _is_terminal(words, index):
            last = index
        if last is not None:
            nearest[index] = index - last
    last = None
    for index in range(size - 1, -1, -1):
        if _is_terminal(words, index):
            last = index
        if last is not None:
            nearest[index] = min(nearest[index], last - index)
    return tuple(distance <= PUNCTUATION_WINDOW for distance in nearest)


def _continues(words: Sequence[Word], index: int) -> bool:
    # 左侧没说完、右侧小写续接：多是 VAD 拼接把时间戳拉开的假停顿，不当作句界。
    return words[index + 1].text.lstrip()[:1].islower()


def _initial_groups(
    words: Sequence[Word], hard_pause: float, local: Sequence[bool]
) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for index, word in enumerate(words):
        current.append(word)
        pause = words[index + 1].start - word.end if index + 1 < len(words) else 0.0
        paused = pause >= hard_pause and not (local[index] and _continues(words, index))
        if (_is_terminal(words, index) or paused) and _can_cut(words, index):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _duration(group: Sequence[Word]) -> float:
    return group[-1].end - group[0].start


def _best_split(group: Sequence[Word], options: SegmentationOptions) -> int | None:
    best: tuple[float, int] | None = None
    for index in range(options.min_words, len(group) - options.min_words + 1):
        left = group[:index]
        right = group[index:]
        if not _can_cut(group, index - 1):
            continue
        if _duration(left) < options.min_duration or _duration(right) < options.min_duration:
            continue
        pause = max(0.0, right[0].start - left[-1].end)
        clause = CLAUSE.search(left[-1].text.strip()) is not None
        if pause < MIN_SPLIT_PAUSE and not clause:
            continue
        punctuation_bonus = 1.5 if clause else 0.0
        balance_penalty = abs(_duration(left) - _duration(right)) * 0.05
        # 长停顿权重最高，子句标点次之，同时轻微偏好长度均衡。
        score = pause * 3 + punctuation_bonus - balance_penalty
        candidate = (score, index)
        if best is None or candidate > best:
            best = candidate
    return None if best is None else best[1]


def _split_long(group: list[Word], options: SegmentationOptions) -> list[list[Word]]:
    if _duration(group) <= options.max_duration:
        return [group]
    split = _best_split(group, options)
    if split is None:
        return [group]
    return _split_long(group[:split], options) + _split_long(group[split:], options)


def _group_is_complete(group: Sequence[Word]) -> bool:
    return _is_terminal(group, len(group) - 1)


def _can_merge(left: Sequence[Word], right: Sequence[Word], options: SegmentationOptions) -> bool:
    # 左侧已是完整句时合并会跨过句末标点，所以只允许左侧不完整。
    return not _group_is_complete(left) and right[-1].end - left[0].start <= options.max_duration


def _merge_short(
    groups: list[list[Word]], options: SegmentationOptions, relaxed: list[bool]
) -> list[list[Word]]:
    result = [list(group) for group in groups]
    index = 0
    while index < len(result):
        group = result[index]
        # 有标点的区域里没说完的组不论长短都并入邻句；组尾处在无标点区域时只有短碎片需要合并。
        settled = _group_is_complete(group) or (
            relaxed[index] and _duration(group) >= options.min_duration
        )
        if settled:
            index += 1
            continue
        previous_ok = index > 0 and _can_merge(result[index - 1], group, options)
        next_ok = index + 1 < len(result) and _can_merge(group, result[index + 1], options)
        if not previous_ok and not next_ok:
            index += 1
            continue
        previous_pause = group[0].start - result[index - 1][-1].end if previous_ok else float("inf")
        next_pause = result[index + 1][0].start - group[-1].end if next_ok else float("inf")
        # 两侧都可合并时选择停顿更短的一侧；相等时稳定地向前合并。
        if previous_pause <= next_pause:
            result[index - 1].extend(group)
            # 合并后的末词来自当前组，标志也跟着走。
            relaxed[index - 1] = relaxed[index]
            result.pop(index)
            relaxed.pop(index)
            index = max(0, index - 1)
        else:
            group.extend(result[index + 1])
            relaxed[index] = relaxed[index + 1]
            result.pop(index + 1)
            relaxed.pop(index + 1)
    return result


def _text(group: Sequence[Word]) -> str:
    return "".join(word.text for word in group).strip()


def _sentences(
    groups: Sequence[Sequence[Word]],
    media_duration: float,
    options: SegmentationOptions,
) -> tuple[Sentence, ...]:
    output: list[Sentence] = []
    for index, group in enumerate(groups):
        speech_start = group[0].start
        speech_end = group[-1].end
        start = max(0.0, speech_start - options.lead_pad)
        # 末词在容差内越过媒体时长时，切片至少要包住语音本身。
        end = min(max(media_duration, speech_end), speech_end + options.tail_pad)
        # 留白可以用满句间空隙，但不覆盖邻句的语音；相邻窗口因此可能重叠，逐句播放不受影响。
        if index > 0:
            start = max(start, groups[index - 1][-1].end)
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start)
        output.append(
            Sentence(
                index=index,
                start=start,
                end=end,
                speech_start=speech_start,
                speech_end=speech_end,
                text=_text(group),
                words=tuple(group),
            )
        )
    return tuple(output)


def build_sentences(
    words: Sequence[Word],
    media_duration: float,
    options: SegmentationOptions,
) -> tuple[Sentence, ...]:
    cleaned = tuple(word for word in words if word.text.strip())
    if not cleaned:
        return ()
    if media_duration <= 0:
        raise ValueError("media_duration must be positive")
    if any(word.end > media_duration + TIMELINE_TOLERANCE for word in cleaned):
        raise ValueError("word exceeds media duration")
    for previous, current in pairwise(cleaned):
        if current.start < previous.start:
            raise ValueError("word timeline must be monotonic")
    # 流程固定为初分组、拆长、并短、加留白，确保同输入得到同结果。
    local = _locally_punctuated(cleaned)
    initial = _initial_groups(cleaned, options.hard_pause, local)
    split = [part for group in initial for part in _split_long(group, options)]
    # 各组按顺序恰好划分 cleaned，用累计偏移找到每组末词的位置。
    relaxed: list[bool] = []
    offset = 0
    for group in split:
        offset += len(group)
        relaxed.append(not local[offset - 1])
    merged = _merge_short(split, options, relaxed)
    return _sentences(merged, media_duration, options)
