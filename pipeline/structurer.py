from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pipeline.llm_client import LLMClient
from utils.file_utils import continuation_hint, split_into_chunks
from utils.retry import llm_retry

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger("knou.structurer")

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "pass2_structure.txt"

# chunk_progress_fn(current: int, total: int) -> None
ChunkProgressFn = Callable[[int, int], None]


class Structurer:
    """
    LLM Pass 2: Convert clean text into structured Markdown.
    All content must be preserved; no summarisation allowed.
    """

    def __init__(self, llm: LLMClient, settings: "Settings") -> None:
        self._llm = llm
        self._settings = settings
        self._system_prompt = _PROMPT_FILE.read_text(encoding="utf-8")

    def structure(
        self,
        clean_text: str,
        lecture_title: str = "",
        chunk_progress_fn: ChunkProgressFn | None = None,
        chunk_cache_dir: Path | None = None,
    ) -> str:
        """
        Split clean text into chunks and run Pass 2 markdown structuring on each.

        Args:
            clean_text: Pass 1 corrected text.
            lecture_title: Used as the H1 header in the output document.
            chunk_progress_fn: Optional callback(current, total) called after each chunk.
            chunk_cache_dir: If provided, each completed chunk is saved as
                ``chunk_cache_dir/struct.NNNN.txt`` immediately after the LLM call.
                On resume, already-saved chunks are loaded from disk so a mid-run
                shutdown loses at most one chunk.

        Returns the final markdown document.
        """
        chunks = split_into_chunks(
            clean_text,
            chunk_size=self._settings.chunk_size,
            overlap=self._settings.chunk_overlap,
        )
        total = len(chunks)
        logger.info("Pass 2: processing %d chunk(s)", total)

        if chunk_cache_dir:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)

        md_chunks: list[str] = []
        prev_chunk = ""

        for i, chunk in enumerate(chunks):
            cache_file = chunk_cache_dir / f"struct.{i:04d}.txt" if chunk_cache_dir else None

            if cache_file and cache_file.exists() and cache_file.stat().st_size > 0:
                logger.debug("Pass 2 chunk %d/%d — loaded from cache", i + 1, total)
                result = cache_file.read_text(encoding="utf-8")
            else:
                logger.debug("Pass 2 chunk %d/%d (%d chars)", i + 1, total, len(chunk))
                result = self._structure_chunk(chunk, prev_chunk)
                if cache_file:
                    cache_file.write_text(result, encoding="utf-8")

            md_chunks.append(result)
            prev_chunk = result
            if chunk_progress_fn:
                chunk_progress_fn(i + 1, total)

        body = "\n\n".join(md_chunks)
        header = f"# {lecture_title}\n\n" if lecture_title else ""
        return header + body

    @llm_retry(max_attempts=5, min_wait=2.0, max_wait=60.0)
    def _structure_chunk(self, chunk: str, previous: str) -> str:
        hint = continuation_hint(previous)
        if hint:
            user_prompt = f"[이전 내용 힌트:]\n{hint}\n\n[구조화할 텍스트:]\n{chunk}"
        else:
            user_prompt = chunk

        return self._llm.call(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            max_tokens=4096,
            temperature=0.3,
        )
