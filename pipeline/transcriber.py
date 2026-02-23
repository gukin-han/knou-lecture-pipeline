from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger("knou.transcriber")

# segment_progress_fn(processed_seconds, total_seconds)
SegmentProgressFn = Callable[[float, float], None]

# initial_prompt로 CS 어휘를 미리 주입하면 small 모델의 오인식률이 크게 낮아짐
KNOU_INITIAL_PROMPT = (
    "이 강의는 한국방송통신대학교 컴퓨터과학 전공 강의입니다. "
    "자료구조, 알고리즘, 운영체제, 데이터베이스, 컴퓨터 네트워크, 소프트웨어 공학, "
    "프로그래밍 언어, 컴파일러, 인공지능, 이산수학 과목이며 "
    "스택, 큐, 트리, 그래프, 해시, 정렬, 탐색, 재귀, 시간복잡도, 빅오 표기법, "
    "프로세스, 스레드, 메모리, 캐시, 페이지, 세마포어, 교착상태, "
    "TCP/IP, HTTP, 라우터, 프로토콜, SQL, 트랜잭션, 인덱스, 정규화, "
    "객체지향, 클래스, 인터페이스, 상속, 다형성, 캡슐화 등의 용어가 사용됩니다."
)


class Transcriber:
    """Transcribes MP3/audio files to Korean text using faster-whisper."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._model = None

    def _load_model(self) -> None:
        if self._model is not None:
            return

        from faster_whisper import WhisperModel

        device = self._settings.whisper_device
        compute_type = self._settings.whisper_compute_type

        # Resolve "auto" device: prefer CUDA, fall back to CPU
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # Resolve "auto" compute type based on device
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(
            "Loading Whisper model: size=%s device=%s compute_type=%s",
            self._settings.whisper_model_size,
            device,
            compute_type,
        )
        self._model = WhisperModel(
            self._settings.whisper_model_size,
            device=device,
            compute_type=compute_type,
        )
        logger.info("Whisper model loaded.")

    def transcribe(
        self,
        audio_path: Path,
        segment_progress_fn: SegmentProgressFn | None = None,
        output_file: Path | None = None,
    ) -> str:
        """
        Transcribe an audio file and return the full Korean text.

        Args:
            audio_path: Path to the MP3 or audio file.
            segment_progress_fn: Optional callback(processed_sec, total_sec)
                called after each Whisper segment so the caller can report
                real-time progress.
            output_file: If provided, each segment is appended to this file
                immediately after processing so partial results survive a
                mid-transcription shutdown (graceful resume support).

        Returns:
            Transcribed text as a single string.
        """
        self._load_model()

        logger.info("Transcribing: %s", audio_path.name)
        segments, info = self._model.transcribe(
            str(audio_path),
            language="ko",
            initial_prompt=KNOU_INITIAL_PROMPT,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
            },
            beam_size=5,
            best_of=5,
            temperature=0.0,
            word_timestamps=False,
        )

        logger.info(
            "Detected language: %s (probability=%.2f), duration=%.1fs",
            info.language,
            info.language_probability,
            info.duration,
        )

        text_parts: list[str] = []

        # Open output file once and flush after every segment
        out_fh = open(output_file, "w", encoding="utf-8") if output_file else None
        try:
            for segment in segments:
                text = segment.text.strip()
                text_parts.append(text)

                if out_fh:
                    out_fh.write(text + "\n")
                    out_fh.flush()          # 셧다운 시 OS 버퍼 손실 방지

                if segment_progress_fn:
                    segment_progress_fn(segment.end, info.duration)
        finally:
            if out_fh:
                out_fh.close()

        full_text = " ".join(text_parts)
        logger.info(
            "Transcription complete: %d characters from %s",
            len(full_text),
            audio_path.name,
        )
        return full_text
