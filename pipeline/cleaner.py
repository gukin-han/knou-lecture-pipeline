from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pipeline.llm_client import LLMClient
from utils.file_utils import continuation_hint, split_into_chunks
from utils.retry import llm_retry

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger("knou.cleaner")

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "pass1_cleanup.txt"

# chunk_progress_fn(current: int, total: int) -> None
ChunkProgressFn = Callable[[int, int], None]


class Cleaner:
    """
    LLM Pass 1: Correct STT output — punctuation, filler removal, mis-recognition.
    Does NOT summarise or restructure; every piece of information is preserved.
    """

    def __init__(self, llm: LLMClient, settings: "Settings") -> None:
        self._llm = llm
        self._settings = settings
        self._system_prompt = _PROMPT_FILE.read_text(encoding="utf-8")

    def clean(
        self,
        stt_text: str,
        chunk_progress_fn: ChunkProgressFn | None = None,
        chunk_cache_dir: Path | None = None,
    ) -> str:
        """
        Split the raw STT text into chunks and run Pass 1 correction on each.

        Args:
            stt_text: Raw transcription text.
            chunk_progress_fn: Optional callback(current, total) called after each chunk.
            chunk_cache_dir: If provided, each completed chunk is saved as
                ``chunk_cache_dir/clean.NNNN.txt`` immediately after the LLM call.
                On resume, already-saved chunks are loaded from disk instead of
                re-calling the LLM, so a mid-run shutdown loses at most one chunk.

        Returns the fully corrected text (chunks joined with double newlines).
        """
        chunks = split_into_chunks(
            stt_text,
            chunk_size=self._settings.chunk_size,
            overlap=self._settings.chunk_overlap,
        )
        total = len(chunks)
        logger.info("Pass 1: processing %d chunk(s)", total)

        if chunk_cache_dir:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)

        cleaned_chunks: list[str] = []
        prev_chunk = ""

        for i, chunk in enumerate(chunks):
            cache_file = chunk_cache_dir / f"clean.{i:04d}.txt" if chunk_cache_dir else None

            if cache_file and cache_file.exists() and cache_file.stat().st_size > 0:
                logger.debug("Pass 1 chunk %d/%d — loaded from cache", i + 1, total)
                result = cache_file.read_text(encoding="utf-8")
            else:
                logger.debug("Pass 1 chunk %d/%d (%d chars)", i + 1, total, len(chunk))
                result = self._clean_chunk(chunk, prev_chunk)
                if cache_file:
                    cache_file.write_text(result, encoding="utf-8")

            cleaned_chunks.append(result)
            prev_chunk = result
            if chunk_progress_fn:
                chunk_progress_fn(i + 1, total)

        return "\n\n".join(cleaned_chunks)

    @llm_retry(max_attempts=5, min_wait=2.0, max_wait=60.0)
    def _clean_chunk(self, chunk: str, previous: str) -> str:
        hint = continuation_hint(previous)
        if hint:
            user_prompt = f"[이전 내용 힌트:]\n{hint}\n\n[교정할 텍스트:]\n{chunk}"
        else:
            user_prompt = chunk

        return self._llm.call(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            max_tokens=4096,
            temperature=0.2,
        )
