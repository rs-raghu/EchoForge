import { useEffect, useState } from "react";
import { cancelJob, fetchJobs, fetchRenderReadiness, projectMediaUrl, startProjectJob } from "../api";
import type { JobItem, RenderReadiness } from "../types";
import { JobList, type StudioPageProps } from "./ViewSharedComponents";

export function RenderQueueView({ project, onProjectChanged, setError }: StudioPageProps) {
  const [readiness, setReadiness] = useState<RenderReadiness | null>(null);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [jobPayload, readinessPayload] = await Promise.all([
        fetchJobs(project?.id),
        project ? fetchRenderReadiness(project.id).catch(() => null) : Promise.resolve(null),
      ]);
      setJobs(jobPayload);
      setReadiness(readinessPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Render data could not be loaded");
    }
  }

  useEffect(() => {
    void load();
  }, [project?.id]);

  async function requestRender(jobType: "render_preview" | "render_final") {
    if (!project) {
      return;
    }
    setBusy(jobType);
    setError(null);
    try {
      await startProjectJob(project.id, jobType);
      await load();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Render could not be requested");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="studio-workbench">
      <section className="panel">
        <div className="panel-header">
          <h2>Render</h2>
          <div className="form-actions">
            <button className="button" disabled={!project || busy === "render_preview"} onClick={() => void requestRender("render_preview")} type="button">
              Render Preview
            </button>
            <button className="button primary" disabled={!project || busy === "render_final"} onClick={() => void requestRender("render_final")} type="button">
              Render Final
            </button>
          </div>
        </div>
        {project && readiness ? (
          <div className="readiness-list">
            {readiness.checks.map((check) => (
              <div className={check.ok ? "check-item done" : "check-item"} key={check.key}>
                <span className="check-box">{check.ok ? "OK" : ""}</span>
                <span>{check.label}</span>
                {!check.ok ? <small>{check.fix}</small> : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <strong>Select a project</strong>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Preview</h2>
          <span className="muted-label">{project?.filesReady.final ? "Final ready" : project?.filesReady.preview ? "Preview ready" : "Waiting for render"}</span>
        </div>
        {project?.filesReady.final || project?.filesReady.preview ? (
          <div className="video-preview">
            <video
              controls
              key={`${project.id}-${project.filesReady.final ? "final" : "preview"}`}
              src={projectMediaUrl(project.id, project.filesReady.final ? "final" : "preview")}
            />
            <div className="preview-caption">
              <strong>{project.title}</strong>
              <span>{project.artist}</span>
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <strong>No rendered video yet</strong>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Jobs</h2>
          <button className="button small" onClick={() => void load()} type="button">
            Refresh
          </button>
        </div>
        <JobList jobs={jobs} onCancel={async (job) => {
          await cancelJob(job.id);
          await load();
        }} />
      </section>
    </section>
  );
}
