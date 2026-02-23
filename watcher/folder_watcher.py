from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.processor import Processor

logger = logging.getLogger("knou.watcher")

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}


def watch_folder(input_dir: Path, processor: "Processor") -> None:
    """
    Watch *input_dir* for new audio files and process each one automatically.

    Uses `watchfiles` (macOS FSEvents under the hood) for low-latency detection.
    Blocks until the process is interrupted (Ctrl+C).
    """
    from watchfiles import Change, watch

    logger.info("Watching for new audio files in: %s", input_dir.resolve())
    logger.info("Supported formats: %s", ", ".join(sorted(_AUDIO_EXTENSIONS)))
    logger.info("Press Ctrl+C to stop.")

    # Process any files already sitting in input/ on startup
    _process_existing(input_dir, processor)

    try:
        for changes in watch(str(input_dir), recursive=False):
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type in (Change.added, Change.modified):
                    if path.suffix.lower() in _AUDIO_EXTENSIONS:
                        _handle_file(path, processor)
    except KeyboardInterrupt:
        logger.info("Watcher stopped.")


def _process_existing(input_dir: Path, processor: "Processor") -> None:
    """Process any audio files already present in the input directory."""
    existing = [
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
    ]
    if existing:
        logger.info("Found %d existing file(s) in input/ — processing now.", len(existing))
        for path in sorted(existing):
            _handle_file(path, processor)


def _handle_file(path: Path, processor: "Processor") -> None:
    logger.info("Detected new file: %s", path.name)
    try:
        processor.process(path)
    except Exception as exc:
        logger.error("Failed to process %s: %s", path.name, exc)
