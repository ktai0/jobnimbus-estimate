"""
FastAPI server for CloudNimbus roof measurement and estimation.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import OUTPUT_DIR
from models.schemas import PropertyReport
from pipeline.orchestrator import analyze_from_photos, analyze_property
from pipeline.pdf_report import generate_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# In-memory store for reports and job status
reports_store = {}
jobs = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CloudNimbus API starting up")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yield
    logger.info("CloudNimbus API shutting down")


app = FastAPI(
    title="CloudNimbus API",
    description="Aerial Roof Measurement & Auto-Estimating",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve output files (screenshots, reports)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


class AnalyzeRequest(BaseModel):
    address: str


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    address: str
    report: PropertyReport | None = None
    error: str | None = None


async def _run_analysis(job_id: str, address: str):
    """Background task to run the full analysis pipeline."""
    jobs[job_id]["status"] = "running"
    try:
        report = await analyze_property(address)
        reports_store[job_id] = report
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["report"] = report
    except Exception as e:
        logger.error("Analysis failed for %s: %s", address, e)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


async def _run_upload_analysis(job_id: str, aerial_paths: list[str], streetview_paths: list[str], address: str):
    """Background task to run analysis from uploaded photos."""
    jobs[job_id]["status"] = "running"
    report_dir = os.path.join(OUTPUT_DIR, job_id)
    try:
        report = await analyze_from_photos(aerial_paths, streetview_paths, address, report_dir)
        reports_store[job_id] = report
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["report"] = report
    except Exception as e:
        logger.error("Upload analysis failed for job %s: %s", job_id, e)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Start analysis for a property address."""
    if not request.address.strip():
        raise HTTPException(status_code=400, detail="Address is required")

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + str(hash(request.address) % 10000)
    jobs[job_id] = {
        "status": "pending",
        "address": request.address,
        "report": None,
        "error": None,
    }

    background_tasks.add_task(_run_analysis, job_id, request.address)

    return AnalyzeResponse(
        job_id=job_id,
        status="pending",
        message=f"Analysis started for: {request.address}",
    )


@app.post("/api/analyze/upload", response_model=AnalyzeResponse)
async def analyze_upload(
    background_tasks: BackgroundTasks,
    aerial_photos: list[UploadFile] = File(default=[]),
    streetview_photos: list[UploadFile] = File(default=[]),
    address: str = Form(default=""),
):
    """Start analysis from user-uploaded aerial and streetview photos."""
    if not aerial_photos and not streetview_photos:
        raise HTTPException(status_code=400, detail="At least one photo is required")

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + "upload_" + str(hash(str(id(aerial_photos))) % 10000)
    upload_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(upload_dir, exist_ok=True)

    # Save uploaded files to disk
    aerial_paths: list[str] = []
    for i, photo in enumerate(aerial_photos):
        ext = os.path.splitext(photo.filename or "photo.jpg")[1] or ".jpg"
        path = os.path.join(upload_dir, f"aerial_{i}{ext}")
        content = await photo.read()
        with open(path, "wb") as f:
            f.write(content)
        aerial_paths.append(path)

    streetview_paths: list[str] = []
    for i, photo in enumerate(streetview_photos):
        ext = os.path.splitext(photo.filename or "photo.jpg")[1] or ".jpg"
        path = os.path.join(upload_dir, f"streetview_{i}{ext}")
        content = await photo.read()
        with open(path, "wb") as f:
            f.write(content)
        streetview_paths.append(path)

    label = address.strip() or "Uploaded Photos"
    jobs[job_id] = {
        "status": "pending",
        "address": label,
        "report": None,
        "error": None,
    }

    background_tasks.add_task(_run_upload_analysis, job_id, aerial_paths, streetview_paths, label)

    return AnalyzeResponse(
        job_id=job_id,
        status="pending",
        message=f"Upload analysis started ({len(aerial_paths)} aerial, {len(streetview_paths)} streetview photos)",
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    """Check the status of an analysis job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        address=job["address"],
        report=job.get("report"),
        error=job.get("error"),
    )


@app.get("/api/reports")
async def list_reports():
    """List all completed reports."""
    return [
        {
            "job_id": jid,
            "address": job["address"],
            "status": job["status"],
            "total_sqft": job["report"].measurements.total_roof_sqft if job.get("report") else None,
        }
        for jid, job in jobs.items()
    ]


@app.get("/api/reports/{job_id}", response_model=PropertyReport)
async def get_report(job_id: str):
    """Get the full report for a completed analysis."""
    if job_id not in reports_store:
        raise HTTPException(status_code=404, detail="Report not found")
    return reports_store[job_id]


@app.get("/api/reports/{job_id}/pdf")
async def get_report_pdf(job_id: str):
    """Generate and download a PDF report for a completed analysis."""
    if job_id not in reports_store:
        raise HTTPException(status_code=404, detail="Report not found")

    report = reports_store[job_id]
    address = jobs[job_id]["address"]
    safe_name = "".join(c if c.isalnum() else "_" for c in address)[:60]
    report_dir = os.path.join(OUTPUT_DIR, safe_name)

    try:
        pdf_path = generate_pdf(report, report_dir)
    except Exception as e:
        logger.error("PDF generation failed for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail="PDF generation failed") from e

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"CloudNimbus_Report_{safe_name}.pdf",
    )


class BatchRequest(BaseModel):
    addresses: list[str]


@app.post("/api/batch")
async def batch_analyze(request: BatchRequest, background_tasks: BackgroundTasks):
    """Start batch analysis for multiple addresses."""
    job_ids = []
    for addr in request.addresses:
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + str(hash(addr) % 10000)
        jobs[job_id] = {
            "status": "pending",
            "address": addr,
            "report": None,
            "error": None,
        }
        background_tasks.add_task(_run_analysis, job_id, addr)
        job_ids.append({"job_id": job_id, "address": addr})
    return {"jobs": job_ids}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
