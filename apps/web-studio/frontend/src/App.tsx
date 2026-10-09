import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  createProject,
  fetchCharts,
  fetchDashboard,
  fetchLogs,
  fetchProject,
  fetchProjects,
  runProjectAction,
  stageNextProject,
} from "./api";
import { LyricsEditor } from "./editors/LyricsEditor";
import { SyncEditor } from "./editors/SyncEditor";
import { RenderQueueView } from "./views/RenderQueueView";
import { SettingsView } from "./views/SettingsView";
import { TemplatesView } from "./views/TemplatesView";
import { UploadManagerView } from "./views/UploadManagerView";
import type { DashboardPayload, LogItem, ProjectDetail, ProjectSummary, SummaryCard } from "./types";

type ViewKey =
  | "dashboard"
  | "discover"
  | "queue"
  | "projects"
  | "lyrics"
  | "sync"
  | "templates"
  | "render"
  | "upload"
  | "settings"
  | "logs";

const navItems: Array<{ key: ViewKey; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "discover", label: "Discover" },
  { key: "queue", label: "Queue" },
  { key: "projects", label: "Projects" },
  { key: "lyrics", label: "Lyrics" },
  { key: "sync", label: "Sync" },
  { key: "templates", label: "Templates" },
  { key: "render", label: "Render Queue" },
  { key: "upload", label: "Upload Manager" },
  { key: "settings", label: "Settings" },
  { key: "logs", label: "Logs" },
];

const primaryLabels: Record<string, string> = {
  stage: "Stage",
  run_full: "Run Full",
  fetch_lyrics: "Fetch Lyrics",
  approve_lyrics: "Approve Lyrics",
  assets_only: "Build Assets",
  render_preview: "Render Preview",
  render_final: "Render Final",
  upload_youtube: "Upload",
  approve_sync: "Approve Sync",
  continue_video: "Continue",
  approve_video: "Approve Upload",
  retry: "Retry",
};

export function App() {
  const [view, setView] = useState<ViewKey>("dashboard");
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;
  const [selected, setSelected] = useState<ProjectDetail | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"simple" | "advanced">("simple");

  const refresh = useCallback(async () => {
    try {
      const [dashboardPayload, projectPayload, logPayload] = await Promise.all([
        fetchDashboard(),
        fetchProjects(),
        fetchLogs(),
      ]);
      setDashboard(dashboardPayload);
      setProjects(projectPayload);
      setLogs(logPayload);
      if (selectedId) {
        const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load Web Studio data");
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId && projects.length > 0) {
      setSelectedId(projects[0].id);
    }
  }, [projects, selectedId]);

  const selectedProjectName = useMemo(() => {
    if (!selectedId) {
      return "No project selected";
    }
    return projects.find((project) => project.id === selectedId)?.title ?? selectedId;
  }, [projects, selectedId]);

  async function executeAction(project: ProjectSummary, action: string, target?: string) {
    const key = `${project.id}:${action}`;
    setBusyKey(key);
    setError(null);
    try {
      const detail = await runProjectAction(project.id, action, target);
      setSelectedId(project.id);
      setSelected(detail);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyKey(null);
    }
  }

  async function stageNext() {
    setBusyKey("stage-next");
    setError(null);
    try {
      const detail = await stageNextProject();
      setSelectedId(detail.id);
      setSelected(detail);
      setView("projects");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Queue is empty");
    } finally {
      setBusyKey(null);
    }
  }

  async function openProject(projectId: string) {
    selectedIdRef.current = projectId;
    setSelected(null);
    setSelectedId(projectId);
    setView("projects");
    try {
      const next = await fetchProject(projectId);
      if (selectedIdRef.current === next.id) setSelected(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project could not be opened");
    }
  }

  async function openLyrics(projectId: string) {
    selectedIdRef.current = projectId;
    setSelected(null);
    setSelectedId(projectId);
    setView("lyrics");
    try {
      const next = await fetchProject(projectId);
      if (selectedIdRef.current === next.id) setSelected(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project could not be opened");
    }
  }

  async function openSync(projectId: string) {
    selectedIdRef.current = projectId;
    setSelected(null);
    setSelectedId(projectId);
    setView("sync");
    try {
      const next = await fetchProject(projectId);
      if (selectedIdRef.current === next.id) setSelected(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project could not be opened");
    }
  }

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">EF</div>
          <div>
            <div className="brand-title">EchoForge</div>
            <div className="brand-subtitle">Web Studio</div>
          </div>
        </div>
        <nav className="nav-list" aria-label="Studio navigation">
          {navItems.map((item) => (
            <button
              className={item.key === view ? "nav-item active" : "nav-item"}
              key={item.key}
              onClick={() => setView(item.key)}
              type="button"
            >
              <span className="nav-dot" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="mode-switch" aria-label="Mode">
          <button className={mode === "simple" ? "selected" : ""} onClick={() => setMode("simple")} type="button">
            Simple
          </button>
          <button className={mode === "advanced" ? "selected" : ""} onClick={() => setMode("advanced")} type="button">
            Advanced
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">Current Project</div>
            <h1>{selectedProjectName}</h1>
          </div>
          <div className="topbar-actions">
            <JobIndicator count={dashboard?.activeProjects.length ?? 0} />
            <button className="button ghost" onClick={() => void refresh()} type="button">
              Refresh
            </button>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {view === "dashboard" ? (
          <DashboardView
            dashboard={dashboard}
            projects={projects}
            busyKey={busyKey}
            onAction={executeAction}
            onOpen={openProject}
            onOpenLyrics={openLyrics}
            onOpenSync={openSync}
            onStageNext={stageNext}
            onSwitchView={setView}
          />
        ) : null}
        {view === "discover" ? <DiscoverView onRefresh={refresh} setError={setError} setBusyKey={setBusyKey} busyKey={busyKey} /> : null}
        {view === "queue" ? (
          <QueueView
            dashboard={dashboard}
            busyKey={busyKey}
            onAction={executeAction}
            onOpen={openProject}
            onOpenLyrics={openLyrics}
            onOpenSync={openSync}
            onStageNext={stageNext}
          />
        ) : null}
        {view === "projects" ? (
          <ProjectsView
            projects={projects}
            selected={selected}
            selectedId={selectedId}
            busyKey={busyKey}
            mode={mode}
            onOpen={openProject}
            onOpenLyrics={openLyrics}
            onOpenSync={openSync}
            onSwitchView={setView}
            onAction={executeAction}
            onCreated={async (project) => {
              setSelectedId(project.id);
              setSelected(project);
              await refresh();
            }}
            setBusyKey={setBusyKey}
            setError={setError}
          />
        ) : null}
        {view === "lyrics" ? (
          <LyricsEditor
            key={selected?.id ?? "none"}
            project={selected}
            setError={setError}
            onProjectChanged={async () => {
              await refresh();
              if (selectedId) {
                const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
              }
            }}
          />
        ) : null}
        {view === "sync" ? (
          <SyncEditor
            key={selected?.id ?? "none"}
            project={selected}
            setError={setError}
            onProjectChanged={async () => {
              await refresh();
              if (selectedId) {
                const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
              }
            }}
          />
        ) : null}
        {view === "templates" ? (
          <TemplatesView
            key={selected?.id ?? "none"}
            project={selected}
            setError={setError}
            onProjectChanged={async () => {
              await refresh();
              if (selectedId) {
                const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
              }
            }}
          />
        ) : null}
        {view === "render" ? (
          <RenderQueueView
            key={selected?.id ?? "none"}
            project={selected}
            setError={setError}
            onProjectChanged={async () => {
              await refresh();
              if (selectedId) {
                const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
              }
            }}
          />
        ) : null}
        {view === "upload" ? (
          <UploadManagerView
            key={selected?.id ?? "none"}
            project={selected}
            setError={setError}
            onProjectChanged={async () => {
              await refresh();
              if (selectedId) {
                const next = await fetchProject(selectedId);
        if (selectedIdRef.current === next.id) setSelected(next);
              }
            }}
          />
        ) : null}
        {view === "settings" ? <SettingsView setError={setError} /> : null}
        {view === "logs" ? <LogsView logs={logs} /> : null}
      </main>
    </div>
  );
}

function DashboardView({
  dashboard,
  projects,
  busyKey,
  onAction,
  onOpen,
  onOpenLyrics,
  onOpenSync,
  onStageNext,
  onSwitchView,
}: {
  dashboard: DashboardPayload | null;
  projects: ProjectSummary[];
  busyKey: string | null;
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onOpen: (projectId: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
  onStageNext: () => Promise<void>;
  onSwitchView: (view: ViewKey) => void;
}) {
  const summary = dashboard?.summary ?? [];
  const active = dashboard?.activeProjects ?? [];
  const recent = dashboard?.recentProjects ?? projects.slice(0, 6);

  return (
    <section className="view-stack">
      <div className="summary-grid">
        {summary.map((card) => (
          <SummaryTile card={card} key={card.key} />
        ))}
      </div>
      <div className="command-row">
        <button className="button primary" onClick={() => onSwitchView("discover")} type="button">
          Discover Songs
        </button>
        <button className="button" onClick={() => onSwitchView("projects")} type="button">
          Create Manual Project
        </button>
        <button className="button" disabled={busyKey === "stage-next"} onClick={() => void onStageNext()} type="button">
          Continue Queue
        </button>
        <button className="button" onClick={() => onSwitchView("render")} type="button">
          Render Queue
        </button>
      </div>

      <section className="split-layout">
        <Panel title="Active Projects">
          {active.length === 0 ? (
            <EmptyState title="No active projects" action="Discover Songs" onClick={() => onSwitchView("discover")} />
          ) : (
            <div className="project-grid">
              {active.map((project) => (
                <ProjectCard
                  busyKey={busyKey}
                  key={project.id}
                  project={project}
                  onAction={onAction}
                  onOpen={onOpen}
                  onOpenLyrics={onOpenLyrics}
                  onOpenSync={onOpenSync}
                />
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Recent Projects">
          <div className="compact-list">
            {recent.map((project) => (
              <button className="compact-row" key={project.id} onClick={() => void onOpen(project.id)} type="button">
                <span>
                  <strong>{project.title}</strong>
                  <small>{project.artist}</small>
                </span>
                <StatusBadge tone={project.statusTone}>{project.statusLabel}</StatusBadge>
              </button>
            ))}
          </div>
        </Panel>
      </section>
    </section>
  );
}

function DiscoverView({
  onRefresh,
  setError,
  setBusyKey,
  busyKey,
}: {
  onRefresh: () => Promise<void>;
  setError: (message: string | null) => void;
  setBusyKey: (key: string | null) => void;
  busyKey: string | null;
}) {
  const [country, setCountry] = useState("US");
  const [limit, setLimit] = useState(10);
  const [message, setMessage] = useState<string | null>(null);

  async function runCharts(force = false) {
    setBusyKey("discover");
    setMessage(null);
    setError(null);
    try {
      const result = await fetchCharts({ country, limit, force });
      setMessage(result.message ?? `Added ${result.added} new song${result.added === 1 ? "" : "s"}.`);
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <section className="view-stack">
      <Panel title="Discover">
        <div className="form-grid">
          <label>
            Country
            <select value={country} onChange={(event) => setCountry(event.target.value)}>
              <option value="US">United States</option>
              <option value="IN">India</option>
              <option value="GLOBAL">Global</option>
              <option value="GB">United Kingdom</option>
            </select>
          </label>
          <label>
            Limit
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </label>
          <div className="form-actions">
            <button className="button primary" disabled={busyKey === "discover"} onClick={() => void runCharts(false)} type="button">
              Fetch Trending Songs
            </button>
            <button className="button" disabled={busyKey === "discover"} onClick={() => void runCharts(true)} type="button">
              Refresh
            </button>
          </div>
        </div>
        <div className="warning-note">Confirm audio and lyrics rights before uploading publicly.</div>
        {message ? <div className="success-note">{message}</div> : null}
      </Panel>
    </section>
  );
}

function QueueView({
  dashboard,
  busyKey,
  onAction,
  onOpen,
  onOpenLyrics,
  onOpenSync,
  onStageNext,
}: {
  dashboard: DashboardPayload | null;
  busyKey: string | null;
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onOpen: (projectId: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
  onStageNext: () => Promise<void>;
}) {
  const queue = dashboard?.queue ?? [];
  return (
    <section className="view-stack">
      <div className="command-row">
        <button className="button primary" disabled={busyKey === "stage-next"} onClick={() => void onStageNext()} type="button">
          Start Next
        </button>
      </div>
      <Panel title="Queue">
        {queue.length === 0 ? (
          <EmptyState title="Queue is empty" />
        ) : (
          <div className="table-list">
            {queue.map((project) => (
              <ProjectRow
                busyKey={busyKey}
                key={project.id}
                project={project}
                onAction={onAction}
                onOpen={onOpen}
                onOpenLyrics={onOpenLyrics}
                onOpenSync={onOpenSync}
              />
            ))}
          </div>
        )}
      </Panel>
    </section>
  );
}

function ProjectsView({
  projects,
  selected,
  selectedId,
  busyKey,
  mode,
  onOpen,
  onOpenLyrics,
  onOpenSync,
  onSwitchView,
  onAction,
  onCreated,
  setBusyKey,
  setError,
}: {
  projects: ProjectSummary[];
  selected: ProjectDetail | null;
  selectedId: string | null;
  busyKey: string | null;
  mode: "simple" | "advanced";
  onOpen: (projectId: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
  onSwitchView: (view: ViewKey) => void;
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onCreated: (project: ProjectDetail) => Promise<void>;
  setBusyKey: (key: string | null) => void;
  setError: (message: string | null) => void;
}) {
  return (
    <section className="project-layout">
      <Panel title="Projects">
        <ManualProjectForm onCreated={onCreated} setBusyKey={setBusyKey} setError={setError} />
        <div className="project-list">
          {projects.map((project) => (
            <button
              className={project.id === selectedId ? "project-list-row selected" : "project-list-row"}
              key={project.id}
              onClick={() => void onOpen(project.id)}
              type="button"
            >
              <span>
                <strong>{project.title}</strong>
                <small>{project.artist}</small>
              </span>
              <StatusBadge tone={project.statusTone}>{project.statusLabel}</StatusBadge>
            </button>
          ))}
        </div>
      </Panel>
      <ProjectDetailPanel
        busyKey={busyKey}
        mode={mode}
        project={selected}
        onAction={onAction}
        onOpenLyrics={onOpenLyrics}
        onOpenSync={onOpenSync}
        onSwitchView={onSwitchView}
      />
    </section>
  );
}

function ProjectDetailPanel({
  project,
  busyKey,
  mode,
  onAction,
  onOpenLyrics,
  onOpenSync,
  onSwitchView,
}: {
  project: ProjectDetail | null;
  busyKey: string | null;
  mode: "simple" | "advanced";
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
  onSwitchView: (view: ViewKey) => void;
}) {
  if (!project) {
    return (
      <Panel title="Overview">
        <EmptyState title="Select a project" />
      </Panel>
    );
  }

  return (
    <section className="detail-stack">
      <Panel title="Overview">
        <div className="project-heading">
          <div>
            <h2>{project.title}</h2>
            <p>{project.artist}</p>
          </div>
          <StatusBadge tone={project.statusTone}>{project.statusLabel}</StatusBadge>
        </div>
        <ProgressBar value={project.progress} />
        <div className="action-strip">
          {project.filesReady.lyrics || project.rawState === "LYRICS_REVIEW_PENDING" ? (
            <button className="button primary" onClick={() => void onOpenLyrics(project.id)} type="button">
              Edit Lyrics
            </button>
          ) : null}
          {project.filesReady.timestamps || project.filesReady.draftTimestamps || project.rawState === "ASSETS_READY" ? (
            <button className="button primary" onClick={() => void onOpenSync(project.id)} type="button">
              Open Sync
            </button>
          ) : null}
          {project.filesReady.timestamps || project.rawState === "ASSETS_READY" || project.filesReady.design ? (
            <button className="button" onClick={() => onSwitchView("templates")} type="button">
              Design
            </button>
          ) : null}
          {project.rawState === "ASSETS_READY" || project.rawState === "PREVIEW_PENDING" || project.filesReady.final ? (
            <button className="button" onClick={() => onSwitchView("render")} type="button">
              Render
            </button>
          ) : null}
          {project.rawState === "PREVIEW_PENDING" || project.filesReady.final ? (
            <button className="button" onClick={() => onSwitchView("upload")} type="button">
              Upload
            </button>
          ) : null}
          {project.primaryAction ? (
            <button
              className={project.primaryAction === "approve_lyrics" ? "button" : "button primary"}
              disabled={busyKey === `${project.id}:${project.primaryAction}`}
              onClick={() =>
                project.primaryAction === "approve_lyrics"
                  ? void onOpenLyrics(project.id)
                  : void onAction(project, project.primaryAction ?? "")
              }
              type="button"
            >
              {project.primaryAction === "approve_lyrics" ? "Open Lyrics" : primaryLabels[project.primaryAction] ?? project.nextAction}
            </button>
          ) : null}
          {project.rawState === "STAGED" || project.rawState === "PAUSED" ? (
            <button
              className="button"
              disabled={busyKey === `${project.id}:assets_only`}
              onClick={() => void onAction(project, "assets_only", "ASSETS_READY")}
              type="button"
            >
              Assets Only
            </button>
          ) : null}
          {["STAGED", "AUDIO_FETCHED", "LYRICS_APPROVED", "ASSETS_READY", "VIDEO_APPROVED"].includes(project.rawState) ? (
            <>
              <button className="button" onClick={() => void onAction(project, "pause")} type="button">
                Pause
              </button>
              <button className="button danger" onClick={() => void onAction(project, "abort")} type="button">
                Abort
              </button>
            </>
          ) : null}
          {!["PUBLISHED", "DISCARDED"].includes(project.rawState) ? (
            <button className="button danger subtle" onClick={() => void onAction(project, "discard")} type="button">
              Discard
            </button>
          ) : null}
        </div>
      </Panel>

      <Panel title="Workflow">
        <div className="checklist">
          {project.checklist.map((item) => (
            <div className={item.done ? "check-item done" : "check-item"} key={item.key}>
              <span className="check-box">{item.done ? "OK" : ""}</span>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      </Panel>

      {mode === "advanced" ? (
        <Panel title="Files">
          <div className="file-list">
            {project.files.length === 0 ? (
              <EmptyState title="No files yet" />
            ) : (
              project.files.map((file) => (
                <div className="file-row" key={file.relativePath}>
                  <span>
                    <strong>{file.name}</strong>
                    <small>{file.relativePath}</small>
                  </span>
                  <small>{formatBytes(file.size)}</small>
                </div>
              ))
            )}
          </div>
        </Panel>
      ) : null}
    </section>
  );
}

function ManualProjectForm({
  onCreated,
  setBusyKey,
  setError,
}: {
  onCreated: (project: ProjectDetail) => Promise<void>;
  setBusyKey: (key: string | null) => void;
  setError: (message: string | null) => void;
}) {
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusyKey("create-project");
    setError(null);
    try {
      const project = await createProject({ title, artist, sourceUrl });
      setTitle("");
      setArtist("");
      setSourceUrl("");
      await onCreated(project);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project could not be created");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <form className="manual-form" onSubmit={(event) => void submit(event)}>
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Song title" />
      <input value={artist} onChange={(event) => setArtist(event.target.value)} placeholder="Artist" />
      <input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="YouTube URL" />
      <button className="button primary" type="submit">
        Create
      </button>
    </form>
  );
}

function LogsView({ logs }: { logs: LogItem[] }) {
  return (
    <section className="view-stack">
      <Panel title="Logs">
        <div className="log-list">
          {logs.map((item, index) => (
            <div className={`log-row ${item.level}`} key={`${item.time}-${index}`}>
              <span>{item.time ? formatDate(item.time) : ""}</span>
              <code>{item.message}</code>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function ProjectCard({
  project,
  busyKey,
  onAction,
  onOpen,
  onOpenLyrics,
  onOpenSync,
}: {
  project: ProjectSummary;
  busyKey: string | null;
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onOpen: (projectId: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
}) {
  return (
    <article className="project-card">
      <button className="card-open" onClick={() => void onOpen(project.id)} type="button">
        <span>
          <strong>{project.title}</strong>
          <small>{project.artist}</small>
        </span>
        <StatusBadge tone={project.statusTone}>{project.statusLabel}</StatusBadge>
      </button>
      <ProgressBar value={project.progress} />
      <div className="card-actions">
        {project.primaryAction ? (
          <button
            className="button primary small"
            disabled={busyKey === `${project.id}:${project.primaryAction}`}
            onClick={() =>
              project.primaryAction === "approve_lyrics"
                ? void onOpenLyrics(project.id)
                : void onAction(project, project.primaryAction ?? "")
            }
            type="button"
          >
            {project.primaryAction === "approve_lyrics" ? "Open Lyrics" : primaryLabels[project.primaryAction] ?? project.nextAction}
          </button>
        ) : null}
        {project.filesReady.timestamps || project.filesReady.draftTimestamps ? (
          <button className="button small" onClick={() => void onOpenSync(project.id)} type="button">
            Sync
          </button>
        ) : null}
        <button className="button small" onClick={() => void onOpen(project.id)} type="button">
          Open
        </button>
      </div>
    </article>
  );
}

function ProjectRow({
  project,
  busyKey,
  onAction,
  onOpen,
  onOpenLyrics,
  onOpenSync,
}: {
  project: ProjectSummary;
  busyKey: string | null;
  onAction: (project: ProjectSummary, action: string, target?: string) => Promise<void>;
  onOpen: (projectId: string) => Promise<void>;
  onOpenLyrics: (projectId: string) => Promise<void>;
  onOpenSync: (projectId: string) => Promise<void>;
}) {
  return (
    <div className="table-row">
      <button className="row-title" onClick={() => void onOpen(project.id)} type="button">
        <strong>{project.title}</strong>
        <small>{project.artist}</small>
      </button>
      <StatusBadge tone={project.statusTone}>{project.statusLabel}</StatusBadge>
      <span>{formatDate(project.updatedAt)}</span>
      <div className="row-actions">
        {project.primaryAction ? (
          <button
            className="button small primary"
            disabled={busyKey === `${project.id}:${project.primaryAction}`}
            onClick={() =>
              project.primaryAction === "approve_lyrics"
                ? void onOpenLyrics(project.id)
                : void onAction(project, project.primaryAction ?? "")
            }
            type="button"
          >
            {project.primaryAction === "approve_lyrics" ? "Open Lyrics" : primaryLabels[project.primaryAction] ?? project.nextAction}
          </button>
        ) : null}
        {project.filesReady.timestamps || project.filesReady.draftTimestamps ? (
          <button className="button small" onClick={() => void onOpenSync(project.id)} type="button">
            Sync
          </button>
        ) : null}
        <button className="button small" onClick={() => void onOpen(project.id)} type="button">
          Open
        </button>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function SummaryTile({ card }: { card: SummaryCard }) {
  return (
    <div className={`summary-card ${card.tone}`}>
      <span>{card.label}</span>
      <strong>{card.value}</strong>
    </div>
  );
}

function StatusBadge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="progress-wrap" aria-label={`Progress ${value}%`}>
      <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

function JobIndicator({ count }: { count: number }) {
  return (
    <div className={count > 0 ? "job-indicator running" : "job-indicator"}>
      <span className="pulse" />
      <span>{count} running</span>
    </div>
  );
}

function EmptyState({ title, action, onClick }: { title: string; action?: string; onClick?: () => void }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {action && onClick ? (
        <button className="button small" onClick={onClick} type="button">
          {action}
        </button>
      ) : null}
    </div>
  );
}

function formatDate(value: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
