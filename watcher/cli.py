from __future__ import annotations

import sys
from pathlib import Path

import click

from config.settings import get_settings
from pipeline.processor import ProcessingError, Processor
from utils.logger import setup_root_logger
from watcher.folder_watcher import watch_folder


def _make_processor() -> Processor:
    settings = get_settings()
    settings.ensure_dirs()
    setup_root_logger(log_level=settings.log_level, log_file=settings.log_file)
    return Processor(settings)


@click.group()
def cli() -> None:
    """KNOU lecture MP3 → Markdown pipeline."""


@cli.command()
def watch() -> None:
    """Watch the input folder and automatically process new audio files."""
    processor = _make_processor()
    settings = get_settings()
    watch_folder(settings.input_dir, processor)


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
def process(files: tuple[str, ...]) -> None:
    """Process one or more audio files immediately.

    \b
    Example:
        knou-pipeline process lecture_01.mp3
        knou-pipeline process *.mp3
    """
    processor = _make_processor()
    failed: list[str] = []

    for file_str in files:
        path = Path(file_str)
        try:
            output = processor.process(path)
            click.echo(f"✓ {path.name} → {output}")
        except ProcessingError as exc:
            click.echo(f"✗ {path.name}: {exc}", err=True)
            failed.append(file_str)

    if failed:
        click.echo(f"\n{len(failed)} file(s) failed. Check data/failed/ and logs.", err=True)
        sys.exit(1)


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path())
def resume(files: tuple[str, ...]) -> None:
    """Resume processing from the last incomplete stage.

    \b
    The file can be in data/input/, data/failed/, or any path.
    Intermediate files (.stt.txt, .clean.txt) are reused if they exist.

    \b
    Example:
        knou-pipeline resume lecture_01.mp3
    """
    processor = _make_processor()
    failed: list[str] = []

    for file_str in files:
        path = Path(file_str)
        try:
            output = processor.resume(path)
            click.echo(f"✓ {path.name} → {output}")
        except (ProcessingError, FileNotFoundError) as exc:
            click.echo(f"✗ {path.name}: {exc}", err=True)
            failed.append(file_str)

    if failed:
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
