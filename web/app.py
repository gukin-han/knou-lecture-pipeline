from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from pipeline.processor import ProcessingError, Processor
from utils.logger import setup_root_logger
from web.job_manager import JobManager

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="KNOU 강의 변환기")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

job_manager = JobManager()
_settings = get_settings()

# One shared Processor instance — Whisper model is loaded lazily and cached
_processor: Processor | None = None
_processor_lock = threading.Lock()


def _get_processor() -> Processor:
    global _processor
    if _processor is None:
        with _processor_lock:
            if _processor is None:
                _processor = Processor(_settings)
    return _processor


@app.on_event("startup")
async def _startup() -> None:
    _settings.ensure_dirs()
    setup_root_logger(log_level=_settings.log_level, log_file=_settings.log_file)
    job_manager.set_loop(asyncio.get_running_loop())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.post("/upload")
async def upload(file: UploadFile) -> dict:
    """Accept an audio file, create a job, start background processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일명이 없습니다.")

    suffix = Path(file.filename).suffix.lower()
    allowed = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다: {suffix}",
        )

    job_id = job_manager.create_job(file.filename)

    # Save uploaded file as <input_dir>/<job_id><suffix>
    save_path = _settings.input_dir / f"{job_id}{suffix}"
    content = await file.read()
    save_path.write_bytes(content)

    # Derive a human-readable lecture title from the original filename
    original_stem = Path(file.filename).stem
    lecture_title = original_stem.replace("_", " ").replace("-", " ").title()

    # Launch processing in a daemon thread so it doesn't block the event loop
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, save_path, lecture_title),
        daemon=True,
        name=f"job-{job_id[:8]}",
    )
    thread.start()

    return {"job_id": job_id, "filename": file.filename}


@app.get("/status/{job_id}")
async def status_stream(job_id: str) -> StreamingResponse:
    """SSE stream of processing events for the given job."""
    if job_manager.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")

    async def event_generator():
        async for event in job_manager.subscribe(job_id):
            if event.get("heartbeat"):
                # SSE comment keeps the connection alive without triggering onmessage
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    """Download the generated Markdown file for a completed job."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다.")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="아직 처리가 완료되지 않았습니다.")

    output_path = job_manager.get_output_path(job_id)
    if output_path is None or not output_path.exists():
        raise HTTPException(status_code=404, detail="출력 파일을 찾을 수 없습니다.")

    # Use the original filename (stem) for the download, not the job UUID
    original_stem = Path(job.filename).stem
    download_name = f"{original_stem}.md"

    return FileResponse(
        path=output_path,
        media_type="text/markdown; charset=utf-8",
        filename=download_name,
    )


# ---------------------------------------------------------------------------
# Worker (runs in a thread)
# ---------------------------------------------------------------------------

def _run_job(job_id: str, audio_path: Path, lecture_title: str) -> None:
    def progress(status: str, message: str, percent: int) -> None:
        job_manager.push_event(job_id, status, message, percent)

    try:
        output_path = _get_processor().process(
            audio_path,
            progress_callback=progress,
            lecture_title=lecture_title,
        )
        job_manager.push_event(
            job_id,
            status="done",
            message="변환 완료! 다운로드 버튼을 눌러주세요.",
            percent=100,
            output_path=str(output_path),
        )
    except ProcessingError as exc:
        job_manager.push_event(
            job_id,
            status="failed",
            message="처리 중 오류가 발생했습니다.",
            percent=0,
            error=str(exc),
        )
    except Exception as exc:
        job_manager.push_event(
            job_id,
            status="failed",
            message="예기치 못한 오류가 발생했습니다.",
            percent=0,
            error=str(exc),
        )
