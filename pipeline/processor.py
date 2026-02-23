from __future__ import annotations

import logging
import shutil
import time
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pipeline.cleaner import Cleaner
from pipeline.llm_client import get_llm_client
from pipeline.structurer import Structurer
from pipeline.transcriber import Transcriber

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger("knou.processor")

# progress_callback(status, message, percent)
ProgressCallback = Callable[[str, str, int], None]


class Stage(Enum):
    TRANSCRIBE = auto()
    CLEAN = auto()
    STRUCTURE = auto()
    DONE = auto()


class ProcessingError(Exception):
    """Raised when a pipeline stage fails permanently."""


class Processor:
    """
    Orchestrates the full MP3 → Markdown pipeline with fault tolerance.

    Intermediate files:
      <intermediate_dir>/<stem>.stt.txt   — STT output
      <intermediate_dir>/<stem>.clean.txt — Pass 1 output

    Restartability:
      If intermediate files already exist, their stages are skipped.
      Use `process(path, resume=True)` or the `knou-pipeline resume` CLI
      command to re-run only the remaining stages.
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._transcriber: Transcriber | None = None
        self._cleaner: Cleaner | None = None
        self._structurer: Structurer | None = None

    # ------------------------------------------------------------------
    # Lazy initialisation of heavy components
    # ------------------------------------------------------------------

    def _get_transcriber(self) -> Transcriber:
        if self._transcriber is None:
            self._transcriber = Transcriber(self._settings)
        return self._transcriber

    def _get_cleaner(self) -> Cleaner:
        if self._cleaner is None:
            llm = get_llm_client(self._settings)
            self._cleaner = Cleaner(llm, self._settings)
        return self._cleaner

    def _get_structurer(self) -> Structurer:
        if self._structurer is None:
            llm = get_llm_client(self._settings)
            self._structurer = Structurer(llm, self._settings)
        return self._structurer

    # ------------------------------------------------------------------
    # Intermediate file paths
    # ------------------------------------------------------------------

    def _stt_path(self, stem: str) -> Path:
        return self._settings.intermediate_dir / f"{stem}.stt.txt"

    def _clean_path(self, stem: str) -> Path:
        return self._settings.intermediate_dir / f"{stem}.clean.txt"

    def _output_path(self, stem: str) -> Path:
        return self._settings.output_dir / f"{stem}.md"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        audio_path: Path,
        progress_callback: ProgressCallback | None = None,
        lecture_title: str = "",
    ) -> Path:
        """
        Run the full pipeline for *audio_path*.

        Args:
            audio_path: Path to the audio file.
            progress_callback: Optional callable(status, message, percent).
            lecture_title: Override the H1 title in the output markdown.

        Returns the path to the generated .md file.
        Raises ProcessingError on unrecoverable failure (file moved to failed/).
        """
        audio_path = audio_path.resolve()
        stem = audio_path.stem
        logger.info("=== Processing: %s ===", audio_path.name)

        self._settings.ensure_dirs()

        def cb(status: str, message: str, percent: int) -> None:
            if progress_callback:
                progress_callback(status, message, percent)

        try:
            output_md = self._run_pipeline(audio_path, stem, cb, lecture_title)
        except Exception as exc:
            logger.error("Pipeline failed for %s: %s", audio_path.name, exc, exc_info=True)
            self._move_to_failed(audio_path)
            raise ProcessingError(f"Failed to process {audio_path.name}") from exc

        self._move_to_processed(audio_path)
        logger.info("=== Done: %s → %s ===", audio_path.name, output_md)
        return output_md

    def resume(
        self,
        audio_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """
        Resume processing from the earliest incomplete stage.
        If the MP3 is in processed/ it is NOT moved again.
        """
        audio_path = audio_path.resolve()
        if not audio_path.exists():
            candidate = self._settings.processed_dir / audio_path.name
            if candidate.exists():
                audio_path = candidate
            else:
                raise FileNotFoundError(f"Audio file not found: {audio_path}")
        return self.process(audio_path, progress_callback=progress_callback)

    # ------------------------------------------------------------------
    # Internal pipeline stages
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        audio_path: Path,
        stem: str,
        cb: ProgressCallback,
        lecture_title: str,
    ) -> Path:
        stt_file = self._stt_path(stem)
        clean_file = self._clean_path(stem)
        output_file = self._output_path(stem)

        # --- Stage 1: Transcription ---
        if stt_file.exists() and stt_file.stat().st_size > 0:
            logger.info("[SKIP] STT already exists: %s", stt_file.name)
            cb("transcribing", "음성 변환 결과 재사용", 35)
            stt_text = stt_file.read_text(encoding="utf-8")
        else:
            cb("transcribing", "음성을 텍스트로 변환 중...", 5)
            logger.info("[RUN ] Stage 1 — Transcription")

            transcribe_start = time.time()

            def segment_progress(processed_sec: float, total_sec: float) -> None:
                if total_sec <= 0:
                    return
                ratio = min(processed_sec / total_sec, 1.0)
                pct = 5 + int(ratio * 30)          # 5 % → 35 %

                # 남은 시간 추정
                elapsed = time.time() - transcribe_start
                speed = processed_sec / elapsed if elapsed > 0.5 else 0
                if speed > 0:
                    remaining_sec = (total_sec - processed_sec) / speed
                    if remaining_sec >= 60:
                        eta = f"약 {int(remaining_sec / 60)}분 남음"
                    else:
                        eta = f"약 {int(remaining_sec)}초 남음"
                else:
                    eta = "계산 중..."

                done_min = int(processed_sec // 60)
                done_sec = int(processed_sec % 60)
                total_min = int(total_sec // 60)
                total_sec_r = int(total_sec % 60)
                msg = (
                    f"음성 변환 중... "
                    f"{done_min}:{done_sec:02d} / {total_min}:{total_sec_r:02d} "
                    f"({eta})"
                )
                cb("transcribing", msg, pct)

            # output_file을 넘기면 세그먼트마다 즉시 디스크에 기록됨
            # → docker compose down으로 중단해도 부분 결과가 보존됨
            stt_text = self._get_transcriber().transcribe(
                audio_path,
                segment_progress_fn=segment_progress,
                output_file=stt_file,
            )
            logger.info("STT saved: %s (%d chars)", stt_file.name, len(stt_text))
            cb("transcribing", "음성 변환 완료", 35)

        # --- Stage 2: LLM Pass 1 — Clean ---
        if clean_file.exists() and clean_file.stat().st_size > 0:
            logger.info("[SKIP] Clean text already exists: %s", clean_file.name)
            cb("cleaning", "텍스트 정제 결과 재사용", 65)
            clean_text = clean_file.read_text(encoding="utf-8")
        else:
            cb("cleaning", "텍스트 정제 중...", 40)
            logger.info("[RUN ] Stage 2 — LLM Pass 1 (cleanup)")

            def clean_progress(current: int, total: int) -> None:
                pct = 40 + int((current / total) * 25)
                cb("cleaning", f"텍스트 정제 중... ({current}/{total} 청크)", pct)

            clean_chunk_dir = self._settings.intermediate_dir / f"{stem}.clean_chunks"
            clean_text = self._get_cleaner().clean(
                stt_text,
                chunk_progress_fn=clean_progress,
                chunk_cache_dir=clean_chunk_dir,
            )
            clean_file.write_text(clean_text, encoding="utf-8")
            logger.info("Clean text saved: %s (%d chars)", clean_file.name, len(clean_text))
            cb("cleaning", "텍스트 정제 완료", 65)

        # --- Stage 3: LLM Pass 2 — Structure ---
        if output_file.exists() and output_file.stat().st_size > 0:
            logger.info("[SKIP] Markdown already exists: %s", output_file.name)
            cb("structuring", "마크다운 구조화 결과 재사용", 95)
        else:
            cb("structuring", "마크다운 구조화 중...", 70)
            logger.info("[RUN ] Stage 3 — LLM Pass 2 (structuring)")

            title = lecture_title or stem.replace("_", " ").replace("-", " ").title()

            def struct_progress(current: int, total: int) -> None:
                pct = 70 + int((current / total) * 25)
                cb("structuring", f"마크다운 구조화 중... ({current}/{total} 청크)", pct)

            struct_chunk_dir = self._settings.intermediate_dir / f"{stem}.struct_chunks"
            md_text = self._get_structurer().structure(
                clean_text,
                lecture_title=title,
                chunk_progress_fn=struct_progress,
                chunk_cache_dir=struct_chunk_dir,
            )
            output_file.write_text(md_text, encoding="utf-8")
            logger.info("Markdown saved: %s (%d chars)", output_file.name, len(md_text))
            cb("structuring", "마크다운 구조화 완료", 95)

        return output_file

    # ------------------------------------------------------------------
    # File management helpers
    # ------------------------------------------------------------------

    def _move_to_processed(self, audio_path: Path) -> None:
        dest = self._settings.processed_dir / audio_path.name
        try:
            shutil.move(str(audio_path), str(dest))
            logger.info("Moved to processed/: %s", audio_path.name)
        except Exception as exc:
            logger.warning("Could not move %s to processed/: %s", audio_path.name, exc)

    def _move_to_failed(self, audio_path: Path) -> None:
        dest = self._settings.failed_dir / audio_path.name
        try:
            shutil.move(str(audio_path), str(dest))
            logger.warning("Moved to failed/: %s", audio_path.name)
        except Exception as exc:
            logger.warning("Could not move %s to failed/: %s", audio_path.name, exc)
