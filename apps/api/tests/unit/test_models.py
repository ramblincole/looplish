from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from looplish_api.domain.errors import DomainError, InvalidJobOptions, JobNotFound
from looplish_api.domain.models import (
    Job,
    JobResult,
    JobStage,
    JobStatus,
    Problem,
    SegmentationOptions,
    Sentence,
    Transcript,
    Word,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_word_requires_positive_ordered_timestamps() -> None:
    with pytest.raises(ValueError, match="end must be greater"):
        Word(start=1.0, end=1.0, text="bad")


def test_word_rejects_negative_start_and_empty_text() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Word(start=-0.1, end=1.0, text="bad")
    with pytest.raises(ValueError, match="must not be empty"):
        Word(start=0.0, end=1.0, text="")


def test_valid_transcript_can_be_constructed() -> None:
    words = (Word(0.0, 0.4, "Hello", 0.9), Word(0.9, 1.3, "world"))
    transcript = Transcript(words=words, language="en", duration=2.0, source="asr")

    assert transcript.words == words
    assert transcript.duration == 2.0


def test_transcript_rejects_word_beyond_duration() -> None:
    with pytest.raises(ValueError, match="exceeds transcript duration"):
        Transcript(words=(Word(0.0, 2.5, "late"),), language="en", duration=2.0, source="asr")


def test_transcript_rejects_backward_timeline() -> None:
    words = (Word(1.0, 1.5, "second"), Word(0.5, 0.8, "first"))
    with pytest.raises(ValueError, match="monotonic"):
        Transcript(words=words, language="en", duration=2.0, source="asr")


def test_transcript_requires_positive_duration() -> None:
    with pytest.raises(ValueError, match="duration must be positive"):
        Transcript(words=(), language=None, duration=0.0, source="asr")


def test_sentence_requires_nested_speech_bounds() -> None:
    with pytest.raises(ValueError, match="sentence boundaries"):
        Sentence(
            index=0,
            start=1.0,
            end=2.0,
            speech_start=0.9,
            speech_end=1.8,
            text="Bad",
            words=(),
        )


def test_valid_sentence_reports_padded_duration() -> None:
    sentence = Sentence(
        index=0,
        start=0.8,
        end=2.4,
        speech_start=1.0,
        speech_end=2.0,
        text="Hello world",
        words=(Word(1.0, 1.4, "Hello"), Word(1.5, 2.0, "world")),
    )

    assert sentence.duration == pytest.approx(1.6)


def test_default_segmentation_options_are_valid() -> None:
    options = SegmentationOptions()

    assert options.min_duration < options.max_duration


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"min_duration": 0.1}, "min_duration"),
        ({"max_duration": 61}, "max_duration"),
        ({"min_duration": 5, "max_duration": 5}, "lower than max_duration"),
        ({"hard_pause": 0.05}, "hard_pause"),
        ({"tail_pad": 2.5}, "padding"),
        ({"min_words": 0}, "min_words"),
    ],
)
def test_segmentation_options_reject_out_of_range_values(
    changes: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SegmentationOptions(**changes)  # type: ignore[arg-type]


def test_new_job_is_queued() -> None:
    job = Job.new("01JABCDEF123", "source", "title", NOW)

    assert job.status is JobStatus.QUEUED
    assert job.stage is None
    assert job.progress == 0.0
    assert job.error is None
    assert job.created_at == job.updated_at == NOW


def test_job_only_allows_forward_transition() -> None:
    now = datetime.now(UTC)
    job = Job.new("01JABCDEF123", "source", "title", now)
    running = job.transition(JobStatus.RUNNING, now)
    assert running.status is JobStatus.RUNNING
    with pytest.raises(ValueError, match="invalid job transition"):
        running.transition(JobStatus.QUEUED, now)


def test_job_completes_full_forward_lifecycle() -> None:
    later = NOW + timedelta(seconds=5)
    job = Job.new("01JABCDEF123", "source", "title", NOW)

    running = job.transition(JobStatus.RUNNING, NOW, stage=JobStage.TRANSCRIBING, progress=0.5)
    done = running.transition(JobStatus.SUCCEEDED, later, stage=None, sentence_count=3)

    assert running.stage is JobStage.TRANSCRIBING
    assert done.status is JobStatus.SUCCEEDED
    assert done.sentence_count == 3
    assert done.created_at == NOW
    assert done.updated_at == later
    assert job.status is JobStatus.QUEUED


@pytest.mark.parametrize("start", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_job_can_fail_from_active_states(start: JobStatus) -> None:
    job = Job.new("01JABCDEF123", "source", "title", NOW)
    if start is JobStatus.RUNNING:
        job = job.transition(JobStatus.RUNNING, NOW)

    failed = job.transition(JobStatus.FAILED, NOW, error=Problem("BOOM", "failed"))

    assert failed.status is JobStatus.FAILED
    assert failed.error == Problem("BOOM", "failed")


@pytest.mark.parametrize("terminal", [JobStatus.SUCCEEDED, JobStatus.FAILED])
def test_terminal_job_has_no_successor(terminal: JobStatus) -> None:
    job = Job.new("01JABCDEF123", "source", "title", NOW).transition(JobStatus.RUNNING, NOW)
    finished = job.transition(terminal, NOW)

    for target in JobStatus:
        with pytest.raises(ValueError, match="invalid job transition"):
            finished.transition(target, NOW)


def test_queued_job_cannot_skip_to_succeeded() -> None:
    job = Job.new("01JABCDEF123", "source", "title", NOW)

    with pytest.raises(ValueError, match="invalid job transition"):
        job.transition(JobStatus.SUCCEEDED, NOW)


def test_job_is_immutable() -> None:
    job = Job.new("01JABCDEF123", "source", "title", NOW)

    with pytest.raises(FrozenInstanceError):
        job.status = JobStatus.RUNNING  # type: ignore[misc]


def test_job_status_values_are_stable() -> None:
    assert [status.value for status in JobStatus] == ["queued", "running", "succeeded", "failed"]


def test_job_result_counts_sentences() -> None:
    sentence = Sentence(0, 0.0, 1.5, 0.2, 1.2, "Hi there", (Word(0.2, 1.2, "Hi"),))
    result = JobResult(
        job_id="01JABCDEF123",
        title="title",
        source_url=None,
        uploader=None,
        thumbnail_url=None,
        duration=10.0,
        language="en",
        transcript_source="asr",
        audio_artifact="audio.m4a",
        created_at=NOW,
        sentences=(sentence,),
    )

    assert result.sentence_count == 1
    assert result.has_clips is False


def test_domain_errors_expose_stable_code_and_status() -> None:
    not_found = JobNotFound()
    invalid = InvalidJobOptions("bad model")

    assert isinstance(not_found, DomainError)
    assert (not_found.code, not_found.status) == ("JOB_NOT_FOUND", 404)
    assert (invalid.code, invalid.detail, invalid.status) == (
        "INVALID_JOB_OPTIONS",
        "bad model",
        422,
    )
    assert str(invalid) == "INVALID_JOB_OPTIONS: bad model"
