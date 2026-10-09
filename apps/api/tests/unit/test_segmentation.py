import random
from collections.abc import Sequence

import pytest

from looplish_api.domain.models import SegmentationOptions, Sentence, Transcript, Word
from looplish_api.domain.segmentation import build_sentences, is_punctuated


def words(*items: tuple[float, float, str]) -> tuple[Word, ...]:
    return tuple(Word(start, end, text) for start, end, text in items)


def spoken(
    *tokens: str, start: float = 0.0, length: float = 0.3, gap: float = 0.05
) -> tuple[Word, ...]:
    # 等长等距的词流，便于只关注标点规则。
    result: list[Word] = []
    cursor = start
    for token in tokens:
        result.append(Word(cursor, cursor + length, token))
        cursor += length + gap
    return tuple(result)


def assert_invariants(
    result: Sequence[Sentence], source: Sequence[Word], media_duration: float
) -> None:
    for index, sentence in enumerate(result):
        assert sentence.index == index
        assert 0 <= sentence.start <= sentence.speech_start
        assert sentence.speech_start < sentence.speech_end <= sentence.end <= media_duration
        assert sentence.text == "".join(word.text for word in sentence.words).strip()
        if index:
            previous = result[index - 1]
            # 留白可以用满句间空隙、相邻窗口可能重叠，但窗口绝不覆盖邻句的语音。
            assert previous.end <= sentence.speech_start
            assert previous.speech_end <= sentence.start
    # 切句只分组，不增删、不改写、不重排任何词。
    kept = [word for word in source if word.text.strip()]
    assert [word for sentence in result for word in sentence.words] == kept


def segment(
    source: Sequence[Word],
    media_duration: float,
    options: SegmentationOptions | None = None,
) -> tuple[Sentence, ...]:
    result = build_sentences(source, media_duration, options or SegmentationOptions())
    assert_invariants(result, source, media_duration)
    return result


def texts(result: Sequence[Sentence]) -> list[str]:
    return [sentence.text for sentence in result]


def test_empty_input_returns_empty() -> None:
    assert build_sentences((), 10, SegmentationOptions()) == ()


def test_whitespace_only_words_return_empty() -> None:
    assert build_sentences(words((0.0, 0.5, " "), (0.6, 1.0, "  ")), 2, SegmentationOptions()) == ()


def test_keeps_complete_one_word_sentences_separate() -> None:
    result = build_sentences(
        words((0.2, 0.5, "Yes."), (0.7, 1.0, "No.")),
        2,
        SegmentationOptions(),
    )
    assert [item.text for item in result] == ["Yes.", "No."]


def test_abbreviation_does_not_end_sentence() -> None:
    result = build_sentences(
        words(
            (0.0, 0.2, "Mr."),
            (0.21, 0.5, "Smith"),
            (0.51, 0.8, "left."),
        ),
        1,
        SegmentationOptions(),
    )
    assert len(result) == 1


def test_hard_pause_creates_boundary_without_punctuation() -> None:
    # 两段都不短于 minDuration，否则它们会作为短碎片再被合并回去。
    result = build_sentences(
        words((0.0, 1.2, "hello"), (2.1, 3.3, "again")),
        4,
        SegmentationOptions(hard_pause=0.75),
    )
    assert len(result) == 2


def test_short_fragments_split_by_hard_pause_are_merged_back() -> None:
    result = segment(words((0.0, 0.4, " hello"), (1.3, 1.6, " again")), 2)

    assert texts(result) == ["hello again"]


def test_pause_below_hard_pause_keeps_words_together() -> None:
    result = segment(words((0.0, 0.4, " hello"), (1.1, 1.6, " again")), 2)

    assert texts(result) == ["hello again"]


def test_clip_windows_never_cover_neighbour_speech() -> None:
    result = build_sentences(
        words((0.5, 1.0, "One."), (1.2, 1.8, "Two.")),
        2,
        SegmentationOptions(lead_pad=0.2, tail_pad=0.4),
    )
    assert result[0].end == pytest.approx(1.2)
    assert result[1].start == pytest.approx(1.0)
    assert result[0].start >= 0
    assert result[-1].end <= 2


def test_same_input_is_stable() -> None:
    source = words((0.0, 0.3, "This"), (0.4, 0.8, "works."))
    options = SegmentationOptions()
    assert build_sentences(source, 1, options) == build_sentences(source, 1, options)


@pytest.mark.parametrize("mark", [".", "?", "!", "。", "！", "？"])
def test_terminal_punctuation_ends_sentence(mark: str) -> None:
    source = spoken(" We", " are", f" here{mark}", " Then", " we", " left.")

    assert texts(segment(source, 5)) == [f"We are here{mark}", "Then we left."]


@pytest.mark.parametrize(
    "tokens",
    [
        (" I", " met", " Mr.", " Smith", " today."),
        (" I", " met", " Dr.", " Jones", " today."),
        (" Eat", " fruit,", " e.g.", " Apples", " daily."),
        (" The", " U.S.", " Economy", " grew."),
        (" John", " J.", " Smith", " arrived."),
        (" It", " costs", " 3.", "14", " dollars."),
    ],
    ids=["mr", "dr", "e.g.", "u.s.", "initial", "decimal"],
)
def test_non_terminal_periods_do_not_split(tokens: tuple[str, ...]) -> None:
    result = segment(spoken(*tokens), 5)

    assert texts(result) == ["".join(tokens).strip()]


def test_lowercase_continuation_after_short_pause_is_not_a_boundary() -> None:
    source = words(
        (0.0, 0.3, " He"), (0.35, 0.7, " left."), (0.8, 1.1, " and"), (1.15, 1.6, " sat.")
    )

    assert texts(segment(source, 3)) == ["He left. and sat."]


def test_lowercase_word_after_long_enough_pause_starts_new_sentence() -> None:
    source = words(
        (0.0, 0.3, " He"), (0.35, 0.7, " left."), (1.0, 1.3, " and"), (1.35, 1.8, " sat.")
    )

    assert texts(segment(source, 3)) == ["He left.", "and sat."]


def test_pronoun_i_with_period_ends_sentence() -> None:
    source = spoken(" So", " am", " I.", " Then", " we", " left.")

    assert texts(segment(source, 5)) == ["So am I.", "Then we left."]


def test_terminal_inside_closing_quote_ends_sentence() -> None:
    source = spoken(" He", " said", ' "Stop!"', " Then", " he", " left.")

    assert texts(segment(source, 5)) == ['He said "Stop!"', "Then he left."]


def test_ellipsis_is_not_a_sentence_end() -> None:
    source = spoken(" Well...", " maybe", " not.")

    assert texts(segment(source, 5)) == ["Well... maybe not."]


def test_two_complete_short_sentences_are_not_merged() -> None:
    source = words((0.0, 0.3, " Hi."), (0.4, 0.8, " Bye."))

    assert texts(segment(source, 2)) == ["Hi.", "Bye."]


def test_long_sentence_splits_after_clause_punctuation() -> None:
    tokens = [f" w{index}" for index in range(16)]
    tokens[5] = " w5,"
    source = spoken(*tokens, length=0.4, gap=0.1)

    result = segment(source, 10, SegmentationOptions(max_duration=6.0))

    assert len(result) == 2
    assert result[0].text.endswith("w5,")
    assert all(sentence.speech_end - sentence.speech_start <= 6.0 for sentence in result)


def test_long_sentence_splits_at_longest_pause() -> None:
    first = spoken(*[f" a{index}" for index in range(7)], length=0.4, gap=0.1)
    second = spoken(*[f" b{index}" for index in range(7)], start=first[-1].end + 0.6, length=0.4)

    result = segment(first + second, 10, SegmentationOptions(max_duration=6.0))

    assert [sentence.words for sentence in result] == [first, second]


def test_long_sentence_is_split_recursively_until_within_limit() -> None:
    source = spoken(*[f" w{index}" for index in range(40)], length=0.4, gap=0.2)

    result = segment(source, 25, SegmentationOptions(max_duration=5.0))

    assert len(result) >= 4
    assert all(sentence.speech_end - sentence.speech_start <= 5.0 for sentence in result)


def test_without_legal_split_point_sentence_may_exceed_max_duration() -> None:
    # 只有两个词，任何切点都会让一侧少于 minWords；宁可超长也不切坏单词。
    source = words((0.0, 8.0, " Loooong"), (8.1, 16.0, " words."))

    result = segment(source, 20, SegmentationOptions(max_duration=14.0))

    assert len(result) == 1
    assert result[0].speech_end - result[0].speech_start > 14.0


def test_split_respects_min_duration_on_both_sides() -> None:
    # 唯一满足 minWords 的切点会留下不足 minDuration 的一侧，所以保持原句。
    source = words((0.0, 0.2, " a"), (0.25, 0.4, " b"), (0.45, 7.0, " c"), (7.05, 7.2, " d"))

    result = segment(source, 8, SegmentationOptions(max_duration=3.0, min_duration=1.0))

    assert len(result) == 1


def fragment_case(before: float, after: float, first: str = " we walked home") -> tuple[Word, ...]:
    # 三个由长停顿分开的句段，中间是不足 minDuration 的无标点碎片。
    # 无标点转写，覆盖按停顿切的兜底路径。
    head = spoken(*first.split(" ")[1:], length=0.5, gap=0.1)
    head = tuple(Word(word.start, word.end, f" {word.text}") for word in head)
    middle_start = head[-1].end + before
    middle = (Word(middle_start, middle_start + 0.3, " and"),)
    tail = spoken(" it", " rained", start=middle[0].end + after, length=0.5, gap=0.1)
    return head + middle + tail


def test_short_fragment_merges_toward_shorter_previous_pause() -> None:
    result = segment(fragment_case(before=0.8, after=1.2), 10)

    assert texts(result) == ["we walked home and", "it rained"]


def test_short_fragment_merges_toward_shorter_next_pause() -> None:
    result = segment(fragment_case(before=1.2, after=0.8), 10)

    assert texts(result) == ["we walked home", "and it rained"]


def test_equal_pauses_merge_fragment_backward() -> None:
    # 用二进制可精确表示的时间，保证两侧停顿严格相等。
    source = words(
        (0.0, 0.5, " we"),
        (0.5, 1.5, " walked"),
        (2.5, 2.75, " and"),
        (3.75, 4.5, " it"),
        (4.5, 5.0, " rained"),
    )

    assert texts(segment(source, 10)) == ["we walked and", "it rained"]


def test_fragment_never_merges_across_terminal_punctuation() -> None:
    # 前一句已完整，即使前侧停顿更短也只能向后合并。
    result = segment(fragment_case(before=0.8, after=1.2, first=" we went home."), 10)

    assert texts(result) == ["we went home.", "and it rained"]


def test_punctuation_density_threshold() -> None:
    sparse = spoken(*[f" w{index}" for index in range(40)], " end.")
    dense = spoken(*[f" w{index}" for index in range(39)], " end.")

    assert not is_punctuated(sparse)
    assert is_punctuated(dense)
    assert not is_punctuated(())


def test_lowercase_continuation_across_long_pause_stays_in_sentence() -> None:
    # 实测：VAD 拼接把「So I」和「just realized」的时间戳拉开 2.3 秒，其实是连着说的。
    head = spoken(" This", " is", " a", " game", " changer.", " So", " I")
    tail = spoken(" just", " realized", " something.", start=head[-1].end + 2.3)

    assert texts(segment(head + tail, 10)) == [
        "This is a game changer.",
        "So I just realized something.",
    ]


def test_incomplete_group_merges_regardless_of_duration() -> None:
    head = spoken(" I", " was", " worried", " that", " it", " would", " be", " cold,", " but...")
    tail = spoken(" So", " I", " got", " black", " nails.", start=head[-1].end + 1.0)

    assert texts(segment(head + tail, 10)) == [
        "I was worried that it would be cold, but... So I got black nails."
    ]


def test_incomplete_group_does_not_merge_past_max_duration() -> None:
    head = spoken(" I", " was", " worried,", " but...")
    tail = spoken(" So", " I", " got", " nails.", start=head[-1].end + 3.0)

    result = segment(head + tail, 10, SegmentationOptions(max_duration=4.0))

    assert texts(result) == ["I was worried, but...", "So I got nails."]


def test_unpunctuated_transcript_still_splits_on_pause() -> None:
    first = spoken(" so", " I", " went", " home", length=0.4)
    second = spoken(" and", " then", " I", " slept", start=first[-1].end + 1.0, length=0.4)

    assert texts(segment(first + second, 10)) == ["so I went home", "and then I slept"]


def test_long_split_never_cuts_between_touching_words() -> None:
    source = spoken(*[f" w{index}" for index in range(20)], length=0.4, gap=0.0)

    result = segment(source, 10, SegmentationOptions(max_duration=4.0))

    assert len(result) == 1


def test_long_split_uses_a_real_pause() -> None:
    first = spoken(*[f" a{index}" for index in range(8)], length=0.4, gap=0.0)
    second = spoken(
        *[f" b{index}" for index in range(8)], start=first[-1].end + 0.2, length=0.4, gap=0.0
    )

    result = segment(first + second, 10, SegmentationOptions(max_duration=4.0))

    assert [sentence.words for sentence in result] == [first, second]


def test_trailing_fragment_after_complete_sentence_stays_alone() -> None:
    source = spoken(" It", " rained.") + words((2.0, 2.3, " so"))

    assert texts(segment(source, 3)) == ["It rained.", "so"]


def test_merge_never_exceeds_max_duration() -> None:
    head = spoken(*[f" w{index}" for index in range(8)], length=0.5, gap=0.1)
    fragment = words((head[-1].end + 0.8, head[-1].end + 1.1, " and"))

    result = segment(head + fragment, 10, SegmentationOptions(max_duration=5.0))

    assert result[-1].words == fragment


def test_first_and_last_padding_are_clamped_to_media() -> None:
    result = segment(words((0.1, 0.5, " Hi."), (0.9, 1.9, " There.")), 2.0)

    assert result[0].start == 0.0
    assert result[-1].end == 2.0


def test_padding_uses_configured_amount_away_from_media_edges() -> None:
    result = segment(
        words((1.0, 1.5, " Hi."), (3.0, 3.5, " There.")),
        10,
        SegmentationOptions(lead_pad=0.2, tail_pad=0.4),
    )

    assert result[0].start == pytest.approx(0.8)
    assert result[0].end == pytest.approx(1.9)
    assert result[1].start == pytest.approx(2.8)
    assert result[1].end == pytest.approx(3.9)


def test_padding_may_use_the_whole_gap() -> None:
    result = segment(
        words((0.0, 0.5, " Hi."), (0.8, 1.2, " There.")),
        2,
        SegmentationOptions(lead_pad=0.3, tail_pad=0.4),
    )

    assert result[0].end == pytest.approx(0.8)
    assert result[1].start == pytest.approx(0.5)


def test_overlapping_words_are_never_separated() -> None:
    # 前一个词还没结束下一个词就开始时，无论标点如何都不能在它们之间断句。
    source = words((0.0, 0.6, " One."), (0.5, 1.0, " Two."), (1.2, 1.6, " Three."))

    assert texts(segment(source, 2)) == ["One. Two.", "Three."]


def test_long_group_is_not_split_between_overlapping_words() -> None:
    source = spoken(*[f" w{index}" for index in range(12)], length=0.5, gap=0.2)
    overlapped = (
        source[:6]
        + tuple(Word(word.start - 0.25, word.end, word.text) for word in source[6:7])
        + source[7:]
    )

    result = segment(overlapped, 10, SegmentationOptions(max_duration=4.0))

    assert len(result) >= 2
    for sentence in result:
        assert sentence.words[0].text != " w6"


def test_accepts_any_valid_transcript_within_duration_tolerance() -> None:
    # Transcript 允许末词在容差内越过时长，切句必须接受同一份数据。
    transcript = Transcript(
        words=words((8.0, 9.0, " Almost"), (9.1, 10.0005, " done.")),
        language="en",
        duration=10.0,
        source="asr",
    )

    result = build_sentences(transcript.words, transcript.duration, SegmentationOptions())

    assert texts(result) == ["Almost done."]
    assert result[-1].speech_end == 10.0005
    assert result[-1].end == 10.0005


@pytest.mark.parametrize(
    ("source", "duration", "message"),
    [
        (words((0.0, 0.5, " Hi.")), 0.0, "media_duration"),
        (words((0.0, 2.5, " Hi.")), 2.0, "exceeds media duration"),
        (words((0.0, 2.002, " Hi.")), 2.0, "exceeds media duration"),
        (words((1.0, 1.5, " Hi."), (0.5, 0.8, " There.")), 2.0, "monotonic"),
    ],
)
def test_invalid_input_is_rejected(source: tuple[Word, ...], duration: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_sentences(source, duration, SegmentationOptions())


def test_sequence_type_does_not_change_result() -> None:
    source = spoken(" This", " is", " one.", " And", " two.")
    options = SegmentationOptions()

    assert build_sentences(list(source), 5, options) == build_sentences(source, 5, options)


TOKENS = [
    " the",
    " cat",
    " sat,",
    " on",
    " Mr.",
    " U.S.",
    " J.",
    " 3.",
    "14",
    " mat.",
    " why?",
    " Yes!",
    " I.",
    " and",
    " so",
]


def random_timeline(generator: random.Random) -> tuple[tuple[Word, ...], float]:
    result: list[Word] = []
    cursor = generator.uniform(0.0, 1.0)
    for _ in range(generator.randint(1, 80)):
        # 混合正常间隔、长停顿和少量重叠，覆盖真实 ASR 的时间轴形态。
        start = max(0.0, cursor + generator.choice([0.02, 0.1, 0.3, 0.8, 2.0, -0.05]))
        if result:
            start = max(start, result[-1].start)
        end = start + generator.uniform(0.05, 1.2)
        result.append(Word(start, end, generator.choice(TOKENS)))
        cursor = end
    return tuple(result), result[-1].end + generator.uniform(0.0, 1.0)


@pytest.mark.parametrize("seed", range(300))
def test_random_timelines_satisfy_invariants(seed: int) -> None:
    generator = random.Random(seed)
    source, duration = random_timeline(generator)
    options = SegmentationOptions(
        min_duration=generator.choice([0.5, 1.0, 2.0]),
        max_duration=generator.choice([3.0, 6.0, 14.0]),
        hard_pause=generator.choice([0.5, 0.75, 1.5]),
    )

    result = segment(source, duration, options)

    assert build_sentences(source, duration, options) == result
