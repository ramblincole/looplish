from datetime import datetime
from typing import Any

from looplish_api.domain.models import (
    Job,
    JobOptions,
    JobResult,
    JobStage,
    JobStatus,
    Problem,
    SegmentationOptions,
    Sentence,
    SubtitleSource,
    Word,
)


def job_to_dict(job: Job) -> dict[str, Any]:
    options = None
    if job.options is not None:
        options = {
            "asrBackend": job.options.asr_backend,
            "asrModel": job.options.asr_model,
            "language": job.options.language,
            "subtitleSource": job.options.subtitle_source.value,
            "subtitleLanguages": list(job.options.subtitle_languages),
            "makeClips": job.options.make_clips,
            "segmentation": {
                "minDuration": job.options.segmentation.min_duration,
                "maxDuration": job.options.segmentation.max_duration,
                "hardPause": job.options.segmentation.hard_pause,
                "leadPad": job.options.segmentation.lead_pad,
                "tailPad": job.options.segmentation.tail_pad,
                "minWords": job.options.segmentation.min_words,
            },
        }
    return {
        "id": job.id,
        "source": job.source,
        "title": job.title,
        "status": job.status.value,
        "stage": job.stage.value if job.stage else None,
        "progress": job.progress,
        "message": job.message,
        "error": (
            {"code": job.error.code, "detail": job.error.detail} if job.error is not None else None
        ),
        "createdAt": job.created_at.isoformat().replace("+00:00", "Z"),
        "updatedAt": job.updated_at.isoformat().replace("+00:00", "Z"),
        "sentenceCount": job.sentence_count,
        "options": options,
    }


def job_from_dict(value: dict[str, Any]) -> Job:
    # 旧任务可能没有 options；存在时必须逐层恢复强类型字段。
    raw_options = value.get("options")
    options = None
    if raw_options is not None:
        raw_seg = raw_options["segmentation"]
        options = JobOptions(
            asr_backend=raw_options["asrBackend"],
            asr_model=raw_options["asrModel"],
            language=raw_options.get("language"),
            subtitle_source=SubtitleSource(raw_options["subtitleSource"]),
            subtitle_languages=tuple(raw_options["subtitleLanguages"]),
            make_clips=bool(raw_options["makeClips"]),
            segmentation=SegmentationOptions(
                min_duration=float(raw_seg["minDuration"]),
                max_duration=float(raw_seg["maxDuration"]),
                hard_pause=float(raw_seg["hardPause"]),
                lead_pad=float(raw_seg["leadPad"]),
                tail_pad=float(raw_seg["tailPad"]),
                min_words=int(raw_seg["minWords"]),
            ),
        )
    raw_error = value.get("error")
    return Job(
        id=value["id"],
        source=value["source"],
        title=value["title"],
        status=JobStatus(value["status"]),
        stage=JobStage(value["stage"]) if value.get("stage") else None,
        progress=float(value["progress"]),
        message=value["message"],
        error=Problem(**raw_error) if raw_error else None,
        created_at=datetime.fromisoformat(value["createdAt"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(value["updatedAt"].replace("Z", "+00:00")),
        sentence_count=int(value["sentenceCount"]),
        options=options,
    )


def word_to_dict(word: Word) -> dict[str, Any]:
    return {
        "start": word.start,
        "end": word.end,
        "text": word.text,
        "probability": word.probability,
    }


def word_from_dict(value: dict[str, Any]) -> Word:
    probability = value.get("probability")
    return Word(
        start=float(value["start"]),
        end=float(value["end"]),
        text=str(value["text"]),
        probability=float(probability) if probability is not None else None,
    )


def sentence_to_dict(sentence: Sentence) -> dict[str, Any]:
    return {
        "index": sentence.index,
        "start": sentence.start,
        "end": sentence.end,
        "speechStart": sentence.speech_start,
        "speechEnd": sentence.speech_end,
        "duration": sentence.duration,
        "text": sentence.text,
        "words": [word_to_dict(word) for word in sentence.words],
    }


def sentence_from_dict(value: dict[str, Any]) -> Sentence:
    return Sentence(
        index=int(value["index"]),
        start=float(value["start"]),
        end=float(value["end"]),
        speech_start=float(value["speechStart"]),
        speech_end=float(value["speechEnd"]),
        text=str(value["text"]),
        words=tuple(word_from_dict(item) for item in value["words"]),
    )


def job_result_to_dict(result: JobResult) -> dict[str, Any]:
    return {
        "jobId": result.job_id,
        "title": result.title,
        "sourceUrl": result.source_url,
        "uploader": result.uploader,
        "thumbnailUrl": result.thumbnail_url,
        "duration": result.duration,
        "language": result.language,
        "transcriptSource": result.transcript_source,
        "audioArtifact": result.audio_artifact,
        "createdAt": result.created_at.isoformat().replace("+00:00", "Z"),
        "sentenceCount": result.sentence_count,
        "hasClips": result.has_clips,
        "sentences": [sentence_to_dict(item) for item in result.sentences],
    }


def job_result_from_dict(value: dict[str, Any]) -> JobResult:
    return JobResult(
        job_id=str(value["jobId"]),
        title=str(value["title"]),
        source_url=value.get("sourceUrl"),
        uploader=value.get("uploader"),
        thumbnail_url=value.get("thumbnailUrl"),
        duration=float(value["duration"]),
        language=value.get("language"),
        transcript_source=str(value["transcriptSource"]),
        audio_artifact=str(value["audioArtifact"]),
        created_at=datetime.fromisoformat(str(value["createdAt"]).replace("Z", "+00:00")),
        sentences=tuple(sentence_from_dict(item) for item in value["sentences"]),
        has_clips=bool(value["hasClips"]),
    )
