import { useEffect, useMemo, useRef, useState } from "react";
import { approveUpload, fetchJobs, fetchUploadMetadata, generateUploadMetadata, saveUploadMetadata } from "../api";
import type { JobItem, UploadMetadata } from "../types";
import { EmptyPanel, JobList, type StudioPageProps } from "./ViewSharedComponents";

export function UploadManagerView({ project, onProjectChanged, setError }: StudioPageProps) {
  const [metadata, setMetadata] = useState<UploadMetadata | null>(null);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState<string | null>(null);
  const tagsText = useMemo(() => (metadata?.tags ?? []).join(", "), [metadata?.tags]);

  async function load() {
    if (!project) {
      setMetadata(null);
      setJobs([]);
      return;
    }
    try {
      const [metadataPayload, jobPayload] = await Promise.all([fetchUploadMetadata(project.id), fetchJobs(project.id)]);
      setMetadata(metadataPayload);
      setJobs(jobPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload data could not be loaded");
    }
  }

  useEffect(() => {
    void load();
  }, [project?.id]);

  function updateMetadata(patch: Partial<UploadMetadata>) {
    if (!metadata) {
      return;
    }
    setMetadata({ ...metadata, ...patch });
  }

  async function generate() {
    if (!project) {
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy("generate");
    setError(null);
    try {
      setMetadata(await generateUploadMetadata(project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Metadata could not be generated");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function save() {
    if (!project || !metadata) {
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy("save");
    setError(null);
    try {
      setMetadata(await saveUploadMetadata(project.id, metadata));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Metadata could not be saved");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function upload(privacy: UploadMetadata["privacy"]) {
    if (!project || !metadata) {
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(`upload-${privacy}`);
    setError(null);
    try {
      const nextMetadata = { ...metadata, privacy };
      const result = await approveUpload(project.id, nextMetadata);
      setMetadata(result.metadata);
      await load();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload could not be requested");
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  if (!project) {
    return <EmptyPanel title="Select a project" />;
  }

  return (
    <fieldset disabled={Boolean(busy)} className="mutation-lock"><section className="studio-workbench">
      <section className="panel">
        <div className="panel-header">
          <h2>Upload</h2>
          <div className="form-actions">
            <button className="button" disabled={busy === "generate"} onClick={() => void generate()} type="button">
              Generate Metadata
            </button>
            <button className="button primary" disabled={busy === "save"} onClick={() => void save()} type="button">
              Save Metadata
            </button>
          </div>
        </div>
        {metadata ? (
          <div className="upload-form">
            <label>
              Title
              <input value={metadata.title} onChange={(event) => updateMetadata({ title: event.target.value })} />
            </label>
            <label>
              Description
              <textarea value={metadata.description} onChange={(event) => updateMetadata({ description: event.target.value })} />
            </label>
            <label>
              Tags
              <input
                value={tagsText}
                onChange={(event) =>
                  updateMetadata({ tags: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) })
                }
              />
            </label>
            <div className="settings-grid">
              <label>
                Privacy
                <select value={metadata.privacy} onChange={(event) => updateMetadata({ privacy: event.target.value as UploadMetadata["privacy"] })}>
                  <option value="private">private</option>
                  <option value="unlisted">unlisted</option>
                  <option value="public">public</option>
                </select>
              </label>
              <label>
                Playlist
                <input value={metadata.playlist} onChange={(event) => updateMetadata({ playlist: event.target.value })} />
              </label>
              <label>
                Schedule
                <input value={metadata.scheduleTime} onChange={(event) => updateMetadata({ scheduleTime: event.target.value })} />
              </label>
            </div>
            <label className="toggle-row">
              <input checked={metadata.madeForKids} onChange={(event) => updateMetadata({ madeForKids: event.target.checked })} type="checkbox" />
              Made for kids
            </label>
            <div className="warning-note">Confirm rights before public upload.</div>
            <div className="form-actions">
              <button className="button" disabled={busy?.startsWith("upload")} onClick={() => void upload("private")} type="button">
                Upload Private
              </button>
              <button className="button" disabled={busy?.startsWith("upload")} onClick={() => void upload("unlisted")} type="button">
                Upload Unlisted
              </button>
              <button className="button danger" disabled={busy?.startsWith("upload")} onClick={() => void upload("public")} type="button">
                Upload Public
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Upload Jobs</h2>
        </div>
        <JobList jobs={jobs.filter((job) => job.jobType === "upload_youtube")} />
        {metadata?.publishedUrl ? <div className="success-note">{metadata.publishedUrl}</div> : null}
      </section>
    </section></fieldset>
  );
}
