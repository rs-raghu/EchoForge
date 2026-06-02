import type { DashboardPayload, LogItem, ProjectDetail, ProjectSummary } from "./types";

const apiBase = window.location.port === "5173" ? "http://127.0.0.1:8765" : "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(body.error || body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function fetchDashboard(): Promise<DashboardPayload> {
  return request<DashboardPayload>("/api/dashboard");
}

export function fetchProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>("/api/projects?limit=200");
}

export function fetchProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function fetchLogs(): Promise<LogItem[]> {
  return request<LogItem[]>("/api/logs?limit=120");
}

export function createProject(payload: { title: string; artist: string; sourceUrl: string }): Promise<ProjectDetail> {
  return request<ProjectDetail>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runProjectAction(projectId: string, action: string, target?: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}/actions`, {
    method: "POST",
    body: JSON.stringify({ action, target }),
  });
}

export function stageNextProject(): Promise<ProjectDetail> {
  return request<ProjectDetail>("/api/queue/stage-next", {
    method: "POST",
    body: "{}",
  });
}

export function fetchCharts(payload: { limit: number; country: string; force?: boolean }) {
  return request<{ added: number; count?: number; skipped?: boolean; message?: string }>("/api/discovery/youtube-charts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

