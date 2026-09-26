"""FastAPI entry point for the offline-first S.P.A.R.K. prototype."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from sih26170.api.repository import ArtifactRepository

app = FastAPI(
    title="S.P.A.R.K. API",
    description="Component burn-in anomaly and reliability screening API",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def repository() -> ArtifactRepository:
    return ArtifactRepository()


Repository = Annotated[ArtifactRepository, Depends(repository)]


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ready", "service": "spark-api", "version": "0.1.0"}


@app.get("/api/system/summary", tags=["screening"])
def system_summary(repo: Repository) -> dict[str, Any]:
    try:
        return repo.summary()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/screening/status", tags=["screening"])
def screening_status(repo: Repository) -> dict[str, Any]:
    """Return availability and final counts from existing pipeline outputs."""

    return repo.screening_status()


@app.get("/api/components/preview", tags=["screening"])
def component_preview(
    repo: Repository,
    limit: int = Query(default=24, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return {"components": repo.component_preview(limit)}
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/datasets/validate", tags=["datasets"])
async def validate_dataset(
    repo: Repository,
    dataset: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        content = await dataset.read()
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("Dataset exceeds the 50 MB prototype upload limit.")
        return repo.validate_upload(content, dataset.filename or "dataset.csv")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
