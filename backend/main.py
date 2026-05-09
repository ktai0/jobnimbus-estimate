"""
FastAPI server for CloudNimbus roof measurement and estimation.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import OUTPUT_DIR
from models.schemas import PropertyReport
from pipeline.orchestrator import analyze_property

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
