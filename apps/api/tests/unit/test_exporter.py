import csv
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from looplish_api.application.exporter import (
    ArtifactExporter,
    render_anki,
    render_srt,
    render_text,
    render_vtt,
)
from looplish_api.domain.models import JobResult, Sentence, Word
from looplish_api.infrastructure.storage.file_artifact_store import FileArtifactStore

JOB_ID = "01JABCDEF123"


def result(*extra: Sentence) -> JobResult:
    sentence = Sentence(
        index=0,
        start=1.0,
        end=2.5,
        speech_start=1.2,
        speech_end=2.2,
        text="Hello, world!",
        words=(Word(1.2, 1.6, "Hello"), Word(1.7, 2.2, ", world!")),
    )
    return JobResult(
        job_id=JOB_ID,
        title="Lesson",
        source_url=None,
        uploader=None,
        thumbnail_url=None,
        duration=3.0,
        language="en",
        transcript_source="asr:fake:test",
        audio_artifact="audio.m4a",
        created_at=datetime.now(UTC),
        sentences=(sentence, *extra),
    )


def second_sentence(text: str = "Second one.") -> Sentence:
    return Sentence(1, 2.5, 4.0, 2.6, 3.8, text, (Word(2.6, 3.8, text),))


class FakeMediaProcessor:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[Path, Path, float, float]] = []
        self.fail = fail

    def probe_duration(self, source: Path) -> float:
        return 3.0

    def to_web_audio(self, source: Path, target: Path) -> Path:
        return target

    def to_asr_wav(self, source: Path, target: Path) -> Path:
        return target

    def to_asr_mp3(self, source: Path, target: Path) -> Path:
        return target

    def slice_asr_mp3(self, source: Path, target: Path, start: float, duration: float) -> Path:
        return target

    def slice_audio(self, source: Path, target: Path, start: float, duration: float) -> Path:
        self.calls.append((source, target, start, duration))
        target.write_bytes(b"partial")
        if self.fail:
            raise RuntimeError("ffmpeg crashed")
        target.write_bytes(f"clip {start:.3f} {duration:.3f}".encode())
        return target


def exporter(tmp_path: Path, media: FakeMediaProcessor | None = None) -> ArtifactExporter:
    return ArtifactExporter(FileArtifactStore(tmp_path), media or FakeMediaProcessor())


def test_srt_uses_speech_bounds() -> None:
    assert render_srt(result().sentences) == ("1\n00:00:01,200 --> 00:00:02,200\nHello, world!\n")


def test_vtt_has_header() -> None:
    assert render_vtt(result().sentences).startswith("WEBVTT\n\n")


def test_vtt_uses_speech_bounds_and_separates_cues() -> None:
    assert render_vtt(result(second_sentence()).sentences) == (
        "WEBVTT\n\n"
        "00:00:01.200 --> 00:00:02.200\nHello, world!\n"
        "\n"
        "00:00:02.600 --> 00:00:03.800\nSecond one.\n"
    )


def test_srt_numbers_cues_from_one_and_separates_with_blank_line() -> None:
    assert render_srt(result(second_sentence()).sentences) == (
        "1\n00:00:01,200 --> 00:00:02,200\nHello, world!\n"
        "\n"
        "2\n00:00:02,600 --> 00:00:03,800\nSecond one.\n"
    )


def test_timestamps_round_to_milliseconds_and_cover_hours() -> None:
    sentence = Sentence(0, 3723.0, 3725.0, 3723.4564, 3724.9996, "Late.", ())

    assert "01:02:03,456 --> 01:02:05,000" in render_srt((sentence,))
    assert "01:02:03.456 --> 01:02:05.000" in render_vtt((sentence,))


def test_text_formats_keep_each_sentence_on_one_line() -> None:
    sentences = result(second_sentence("Line one\n\nline  two")).sentences

    assert render_text(sentences) == "Hello, world!\nLine one line two\n"
    assert "\nLine one line two\n" in render_srt(sentences)
    assert "\nLine one line two\n" in render_vtt(sentences)


def test_vtt_escapes_markup_characters() -> None:
    sentences = result(second_sentence("Tom & <Jerry> -> fun")).sentences

    assert "Tom &amp; &lt;Jerry&gt; -&gt; fun" in render_vtt(sentences)


def test_empty_result_renders_valid_empty_documents() -> None:
    assert render_srt(()) == ""
    assert render_vtt(()) == "WEBVTT\n\n"
    assert render_text(()) == ""
    assert render_anki(()) == ""


def test_anki_references_one_based_clip_name() -> None:
    assert render_anki(result().sentences) == "[sound:000001.mp3]\tHello, world!\r\n"


def test_anki_round_trips_tabs_quotes_newlines_and_unicode() -> None:
    tricky = 'Tab\there, "quoted", new\nline, café 你好'
    rendered = render_anki(result(second_sentence(tricky)).sentences)

    rows = list(csv.reader(io.StringIO(rendered, newline=""), dialect="excel-tab"))

    assert rows == [
        ["[sound:000001.mp3]", "Hello, world!"],
        ["[sound:000002.mp3]", tricky],
    ]


def test_write_text_artifacts_writes_utf8_files(tmp_path: Path) -> None:
    job = result(second_sentence("Café 你好."))

    exporter(tmp_path).write_text_artifacts(job)

    job_dir = tmp_path / JOB_ID
    assert (job_dir / "subtitles.srt").read_text(encoding="utf-8") == render_srt(job.sentences)
    assert (job_dir / "subtitles.vtt").read_text(encoding="utf-8") == render_vtt(job.sentences)
    assert (job_dir / "sentences.txt").read_text(encoding="utf-8") == render_text(job.sentences)
    assert (job_dir / "anki_import.tsv").read_bytes() == render_anki(job.sentences).encode()
    assert not list(job_dir.glob(".*"))


def test_ensure_clip_uses_padded_bounds_and_one_based_name(tmp_path: Path) -> None:
    media = FakeMediaProcessor()

    clip = exporter(tmp_path, media).ensure_clip(result(), 0)

    assert clip == tmp_path.resolve() / JOB_ID / "clips" / "000001.mp3"
    [(source, _, start, duration)] = media.calls
    assert source == tmp_path.resolve() / JOB_ID / "audio.m4a"
    assert (start, duration) == (1.0, 1.5)
    assert clip.read_bytes() == b"clip 1.000 1.500"


def test_ensure_clip_reuses_existing_file(tmp_path: Path) -> None:
    media = FakeMediaProcessor()
    service = exporter(tmp_path, media)

    first = service.ensure_clip(result(), 0)
    second = service.ensure_clip(result(), 0)

    assert first == second
    assert len(media.calls) == 1


def test_failed_slice_leaves_no_clip_to_be_reused(tmp_path: Path) -> None:
    service = exporter(tmp_path, FakeMediaProcessor(fail=True))

    with pytest.raises(RuntimeError, match="ffmpeg crashed"):
        service.ensure_clip(result(), 0)

    assert list((tmp_path / JOB_ID / "clips").iterdir()) == []
    media = FakeMediaProcessor()
    exporter(tmp_path, media).ensure_clip(result(), 0)
    assert len(media.calls) == 1


@pytest.mark.parametrize("index", [-1, 1, 5])
def test_ensure_clip_rejects_out_of_range_index(tmp_path: Path, index: int) -> None:
    media = FakeMediaProcessor()

    with pytest.raises(IndexError):
        exporter(tmp_path, media).ensure_clip(result(), index)
    assert media.calls == []


def test_bundle_contains_only_fixed_paths(tmp_path: Path) -> None:
    job = result(second_sentence())

    bundle = exporter(tmp_path).build_bundle(job)

    with zipfile.ZipFile(bundle) as archive:
        names = sorted(archive.namelist())
        assert archive.read("subtitles.srt").decode() == render_srt(job.sentences)
        assert archive.read("clips/000002.mp3") == b"clip 2.500 1.500"
    assert names == [
        "README.txt",
        "anki_import.tsv",
        "clips/000001.mp3",
        "clips/000002.mp3",
        "sentences.txt",
        "subtitles.srt",
        "subtitles.vtt",
    ]
    assert bundle == tmp_path.resolve() / JOB_ID / "bundle.zip"


def test_bundle_without_clips_has_no_clip_entries(tmp_path: Path) -> None:
    media = FakeMediaProcessor()

    bundle = exporter(tmp_path, media).build_bundle(result(), include_clips=False)

    with zipfile.ZipFile(bundle) as archive:
        assert not [name for name in archive.namelist() if name.startswith("clips/")]
    assert media.calls == []


def test_bundle_fills_only_missing_clips(tmp_path: Path) -> None:
    media = FakeMediaProcessor()
    service = exporter(tmp_path, media)
    job = result(second_sentence())
    service.ensure_clip(job, 0)

    service.build_bundle(job)

    # 第一句已有切片，打包时只为第二句补切一次。
    assert [start for _, _, start, _ in media.calls] == [1.0, 2.5]


def test_bundle_ignores_stray_files_in_clips_directory(tmp_path: Path) -> None:
    service = exporter(tmp_path)
    clips = service.store.clips_dir(JOB_ID)
    (clips / "000099.mp3").write_bytes(b"stale")
    (clips / ".000001.abc.mp3").write_bytes(b"temporary")
    (clips / "evil.mp3").write_bytes(b"x")

    bundle = service.build_bundle(result())

    with zipfile.ZipFile(bundle) as archive:
        assert [name for name in archive.namelist() if name.startswith("clips/")] == [
            "clips/000001.mp3"
        ]


def test_rebuilding_bundle_replaces_previous_and_leaves_no_temp(tmp_path: Path) -> None:
    service = exporter(tmp_path)
    service.build_bundle(result(), include_clips=False)

    bundle = service.build_bundle(result(second_sentence()), include_clips=False)

    with zipfile.ZipFile(bundle) as archive:
        assert "Second one." in archive.read("sentences.txt").decode()
    assert not [path for path in (tmp_path / JOB_ID).iterdir() if path.name.startswith(".")]


def test_failed_bundle_keeps_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = exporter(tmp_path)
    bundle = service.build_bundle(result(), include_clips=False)
    previous = bundle.read_bytes()

    def broken_writestr(self: zipfile.ZipFile, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", broken_writestr)
    with pytest.raises(OSError, match="disk full"):
        service.build_bundle(result(), include_clips=False)

    assert bundle.read_bytes() == previous
    assert not [path for path in (tmp_path / JOB_ID).iterdir() if path.name.startswith(".")]
