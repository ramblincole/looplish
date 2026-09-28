import codecs
from itertools import pairwise
from pathlib import Path

import pytest

from looplish_api.domain.models import SegmentationOptions
from looplish_api.domain.segmentation import build_sentences
from looplish_api.infrastructure.subtitles.parser import parse_subtitle, select_subtitle


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def touch(tmp_path: Path, name: str, size: int = 10) -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


def test_selects_first_configured_language(tmp_path: Path) -> None:
    paths = [
        touch(tmp_path, "source.en-GB.vtt"),
        touch(tmp_path, "source.en.vtt"),
        touch(tmp_path, "source.fr.srt"),
    ]

    assert select_subtitle(paths, ("en", "en-GB")) == tmp_path / "source.en.vtt"
    assert select_subtitle(paths, ("en-GB", "en")) == tmp_path / "source.en-GB.vtt"


def test_language_match_requires_whole_tag_and_ignores_case(tmp_path: Path) -> None:
    paths = [touch(tmp_path, "source.en-US.vtt", 5), touch(tmp_path, "source.EN.srt", 1)]

    # `.en.` 不应命中 `.en-US.`；大小写不同也算同一语言。
    assert select_subtitle(paths, ("en",)) == tmp_path / "source.EN.srt"


def test_falls_back_to_largest_subtitle_then_name(tmp_path: Path) -> None:
    paths = [
        touch(tmp_path, "source.de.vtt", 10),
        touch(tmp_path, "source.fr.vtt", 30),
        touch(tmp_path, "source.es.vtt", 30),
    ]

    assert select_subtitle(paths, ("en",)) == tmp_path / "source.es.vtt"
    assert select_subtitle(list(reversed(paths)), ("en",)) == tmp_path / "source.es.vtt"


def test_ignores_non_subtitle_files(tmp_path: Path) -> None:
    paths = [touch(tmp_path, "source.en.json3", 99), touch(tmp_path, "source.m4a", 99)]

    assert select_subtitle(paths, ("en",)) is None
    assert select_subtitle([], ("en",)) is None


def test_parses_srt_into_monotonic_words(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a.srt",
        "1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nSecond <i>line</i> here.\n",
    )

    transcript = parse_subtitle(path, 10.0)

    assert [word.text for word in transcript.words] == [
        " Hello",
        " world",
        " Second",
        " line",
        " here.",
    ]
    assert transcript.words[0].start == 1.0
    assert transcript.words[1].end == pytest.approx(2.0)
    assert transcript.words[2].start == pytest.approx(2.5)
    assert transcript.source == "subtitle:a.srt"
    assert transcript.duration == 10.0
    starts = [word.start for word in transcript.words]
    assert starts == sorted(starts)


def test_interpolates_by_character_weight(tmp_path: Path) -> None:
    path = write(tmp_path, "a.srt", "1\n00:00:00,000 --> 00:00:04,000\nI understand\n")

    first, second = parse_subtitle(path, 5.0).words

    # 「I」1 个字符、「understand」10 个字符，按 1:10 分配 4 秒。
    assert first.end == pytest.approx(4 / 11)
    assert second.start == pytest.approx(4 / 11)
    assert second.end == pytest.approx(4.0)


def test_parses_vtt_with_omitted_hours_settings_and_notes(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a.vtt",
        "WEBVTT\n\nNOTE generated\n\n"
        "00:01.500 --> 00:02.500 align:start position:0%\n<v Bob>Hi &amp; bye</v>\n\n"
        "01:00:00.000 --> 01:00:01.000\nLate\n",
    )

    words = parse_subtitle(path, 3700.0).words

    assert [word.text for word in words] == [" Hi", " &", " bye", " Late"]
    assert words[0].start == 1.5
    assert words[-1].start == 3600.0


def test_multiline_cue_and_crlf_are_joined(tmp_path: Path) -> None:
    path = tmp_path / "a.srt"
    # 文件以 UTF-8 BOM 开头；用 codecs 常量写出，源码里不出现不可见字符。
    path.write_bytes(codecs.BOM_UTF8 + b"1\r\n00:00:01,000 --> 00:00:03,000\r\nfirst\r\nsecond\r\n")

    assert [word.text for word in parse_subtitle(path, 5.0).words] == [" first", " second"]


@pytest.mark.parametrize(
    "timing",
    ["00:00:02,000 --> 00:00:02,000", "00:00:02,000 --> 00:00:01,000"],
    ids=["zero", "negative"],
)
def test_zero_or_negative_cue_duration_still_yields_valid_words(
    tmp_path: Path, timing: str
) -> None:
    path = write(tmp_path, "a.srt", f"1\n{timing}\nquick words\n")

    words = parse_subtitle(path, 5.0).words

    assert len(words) == 2
    assert all(word.end > word.start >= 2.0 for word in words)
    assert words[1].start >= words[0].end


def test_overlapping_cues_are_pushed_forward(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a.srt",
        "1\n00:00:01,000 --> 00:00:03,000\none two\n\n2\n00:00:02,000 --> 00:00:04,000\nthree\n",
    )

    words = parse_subtitle(path, 5.0).words

    assert words[2].start == pytest.approx(words[1].end)
    for previous, current in pairwise(words):
        assert current.start >= previous.end


def test_cue_touching_media_end_is_clamped(tmp_path: Path) -> None:
    path = write(tmp_path, "a.srt", "1\n00:00:08,000 --> 00:00:12,000\nending words here\n")

    words = parse_subtitle(path, 10.0).words

    assert words
    assert all(word.end <= 10.0 for word in words)
    assert words[-1].end == pytest.approx(10.0)


def test_words_starting_after_media_end_are_dropped(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a.srt",
        "1\n00:00:01,000 --> 00:00:02,000\nkept\n\n2\n00:00:11,000 --> 00:00:12,000\ndropped\n",
    )

    assert [word.text for word in parse_subtitle(path, 10.0).words] == [" kept"]


@pytest.mark.parametrize(
    "content",
    ["", "WEBVTT\n\n", "1\n00:00:01,000 --> 00:00:02,000\n\n", "just text\n"],
    ids=["empty", "header-only", "blank-cue", "no-timing"],
)
def test_subtitle_without_words_is_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError, match="no usable words"):
        parse_subtitle(write(tmp_path, "a.srt", content), 10.0)


def test_parsed_subtitle_feeds_segmentation(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "a.srt",
        "1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nHow are you?\n",
    )
    transcript = parse_subtitle(path, 7.0)

    sentences = build_sentences(transcript.words, transcript.duration, SegmentationOptions())

    assert [sentence.text for sentence in sentences] == ["Hello there.", "How are you?"]
