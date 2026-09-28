from pathlib import Path

from looplish_api.domain.models import Transcript, Word
from looplish_api.domain.ports import ProgressCallback


class FakeTranscriptionBackend:
    name = "fake"

    def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        progress: ProgressCallback | None,
    ) -> Transcript:
        if progress is not None:
            progress(1.0, "测试识别完成")
        return Transcript(
            words=(
                Word(0.20, 0.60, " Listen."),
                Word(0.90, 1.30, " Learn."),
            ),
            language=language or "en",
            duration=2.0,
            source="asr:fake:fixture",
        )
