"""FastAPI entry point for EchoForge Web Studio."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import service


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled Project")
    artist: str = Field(default="Unknown Artist")
    sourceUrl: str = Field(default="")
    videoId: str | None = None


class ActionRequest(BaseModel):
    action: str
    target: str | None = None


class DiscoveryRequest(BaseModel):
    limit: int = 20
    country: str = "US"
    force: bool = False


class LyricsSaveRequest(BaseModel):
    lines: list[dict[str, Any]] | None = None
    text: str | None = None
    clearDraft: bool = True


app = FastAPI(title="EchoForge Web Studio", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8765", "http://127.0.0.1:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    service.init_web_studio()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return service.health()


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return service.dashboard()


@app.get("/api/projects")
def list_projects(limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
    return service.list_projects(limit=limit, state=state)


@app.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    return service.create_project(payload.model_dump())


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/api/projects/{project_id}/actions")
def project_action(project_id: str, payload: ActionRequest) -> dict[str, Any]:
    try:
        return service.run_project_action(project_id, payload.action, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/files")
def project_files(project_id: str) -> list[dict[str, Any]]:
    try:
        return service.list_project_files(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.get("/api/projects/{project_id}/lyrics")
def get_lyrics(project_id: str) -> dict[str, Any]:
    try:
        return service.get_lyrics(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.put("/api/projects/{project_id}/lyrics")
def save_lyrics(project_id: str, payload: LyricsSaveRequest, draft: bool = False) -> dict[str, Any]:
    try:
        return service.save_lyrics(project_id, payload.model_dump(exclude_none=True), draft=draft)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/api/projects/{project_id}/lyrics/approve")
def approve_lyrics(project_id: str, payload: LyricsSaveRequest | None = None) -> dict[str, Any]:
    try:
        data = payload.model_dump(exclude_none=True) if payload else {}
        return service.approve_lyrics(project_id, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.get("/api/projects/{project_id}/lyrics/versions")
def lyrics_versions(project_id: str) -> list[dict[str, Any]]:
    try:
        return service.list_lyrics_versions(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.get("/api/logs")
def logs(project_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    return service.read_logs(project_id=project_id, limit=limit)


@app.post("/api/discovery/youtube-charts")
def discovery(payload: DiscoveryRequest) -> dict[str, Any]:
    return service.run_discovery(limit=payload.limit, country=payload.country, force=payload.force)


@app.post("/api/queue/stage-next")
def stage_next() -> dict[str, Any]:
    project = service.stage_next_project()
    if not project:
        raise HTTPException(status_code=404, detail="Queue is empty")
    return project
