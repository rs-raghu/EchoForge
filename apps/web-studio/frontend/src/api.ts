import type {
  AppSettings,
  DashboardPayload,
  JobItem,
  LogItem,
  LyricLine,
  LyricsPayload,
  ProjectDesign,
  ProjectDetail,
  ProjectSummary,
  RenderReadiness,
  TemplateOption,
  TimestampCheckPayload,
  TimestampSegment,
  TimestampsPayload,
  UploadMetadata,
} from "./types";

declare global {
  interface Window {
    __ECHOFORGE_API_BASE__?: string;
  }
}

const apiBase = (window.__ECHOFORGE_API_BASE__ || window.localStorage.getItem("echoforgeApiBase") || "").replace(/\/$/, "");

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

export function projectMediaUrl(projectId: string, kind: "audio" | "preview" | "final"): string {
  return `${apiBase}/api/projects/${encodeURIComponent(projectId)}/media/${kind}`;
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

export function fetchLyrics(projectId: string): Promise<LyricsPayload> {
  return request<LyricsPayload>(`/api/projects/${encodeURIComponent(projectId)}/lyrics`);
}

export function saveLyrics(projectId: string, lines: LyricLine[], draft: boolean): Promise<LyricsPayload> {
  return request<LyricsPayload>(`/api/projects/${encodeURIComponent(projectId)}/lyrics?draft=${draft ? "true" : "false"}`, {
    method: "PUT",
    body: JSON.stringify({ lines }),
  });
}

export function approveLyrics(projectId: string, lines: LyricLine[]): Promise<LyricsPayload> {
  return request<LyricsPayload>(`/api/projects/${encodeURIComponent(projectId)}/lyrics/approve`, {
    method: "POST",
    body: JSON.stringify({ lines }),
  });
}

export function fetchTimestamps(projectId: string): Promise<TimestampsPayload> {
  return request<TimestampsPayload>(`/api/projects/${encodeURIComponent(projectId)}/timestamps`);
}

export function saveTimestamps(
  projectId: string,
  segments: TimestampSegment[],
  draft: boolean,
): Promise<TimestampsPayload> {
  return request<TimestampsPayload>(`/api/projects/${encodeURIComponent(projectId)}/timestamps?draft=${draft ? "true" : "false"}`, {
    method: "PUT",
    body: JSON.stringify({ segments }),
  });
}

export function validateTimestamps(projectId: string, segments: TimestampSegment[]): Promise<TimestampCheckPayload> {
  return request<TimestampCheckPayload>(`/api/projects/${encodeURIComponent(projectId)}/timestamps/validate`, {
    method: "POST",
    body: JSON.stringify({ segments }),
  });
}

export function shiftTimestamps(
  projectId: string,
  segments: TimestampSegment[],
  delta: number,
  segmentIds: string[],
): Promise<TimestampCheckPayload> {
  return request<TimestampCheckPayload>(`/api/projects/${encodeURIComponent(projectId)}/timestamps/shift`, {
    method: "POST",
    body: JSON.stringify({ segments, delta, segmentIds, scope: segmentIds.length ? "selected" : "all" }),
  });
}

export function approveTimestamps(projectId: string, segments: TimestampSegment[]): Promise<TimestampsPayload> {
  return request<TimestampsPayload>(`/api/projects/${encodeURIComponent(projectId)}/timestamps/approve`, {
    method: "POST",
    body: JSON.stringify({ segments }),
  });
}

export function fetchTemplates(): Promise<TemplateOption[]> {
  return request<TemplateOption[]>("/api/templates");
}

export function fetchProjectDesign(projectId: string): Promise<ProjectDesign> {
  return request<ProjectDesign>(`/api/projects/${encodeURIComponent(projectId)}/design`);
}

export function saveProjectDesign(projectId: string, payload: Partial<ProjectDesign>): Promise<ProjectDesign> {
  return request<ProjectDesign>(`/api/projects/${encodeURIComponent(projectId)}/design`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function fetchRenderReadiness(projectId: string): Promise<RenderReadiness> {
  return request<RenderReadiness>(`/api/projects/${encodeURIComponent(projectId)}/render-readiness`);
}

export function fetchJobs(projectId?: string): Promise<JobItem[]> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return request<JobItem[]>(`/api/jobs${suffix}`);
}

export function startProjectJob(projectId: string, jobType: string, payload: Record<string, unknown> = {}): Promise<JobItem> {
  return request<JobItem>(`/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobType)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function cancelJob(jobId: number): Promise<JobItem> {
  return request<JobItem>(`/api/jobs/${jobId}/cancel`, {
    method: "POST",
    body: "{}",
  });
}

export function fetchUploadMetadata(projectId: string): Promise<UploadMetadata> {
  return request<UploadMetadata>(`/api/projects/${encodeURIComponent(projectId)}/upload/metadata`);
}

export function saveUploadMetadata(projectId: string, payload: UploadMetadata): Promise<UploadMetadata> {
  return request<UploadMetadata>(`/api/projects/${encodeURIComponent(projectId)}/upload/metadata`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function generateUploadMetadata(projectId: string): Promise<UploadMetadata> {
  return request<UploadMetadata>(`/api/projects/${encodeURIComponent(projectId)}/upload/metadata/generate`, {
    method: "POST",
    body: "{}",
  });
}

export function approveUpload(projectId: string, payload: UploadMetadata): Promise<{ metadata: UploadMetadata; job: JobItem; project: ProjectDetail }> {
  return request<{ metadata: UploadMetadata; job: JobItem; project: ProjectDetail }>(
    `/api/projects/${encodeURIComponent(projectId)}/upload/approve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function fetchSettings(): Promise<AppSettings> {
  return request<AppSettings>("/api/settings");
}

export function saveSettings(payload: Partial<AppSettings>): Promise<AppSettings> {
  return request<AppSettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
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
