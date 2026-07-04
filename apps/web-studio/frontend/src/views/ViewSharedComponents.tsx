import type { JobItem, ProjectDetail } from "../types";

export type StudioPageProps = {
  project: ProjectDetail | null;
  onProjectChanged: () => Promise<void>;
  setError: (message: string | null) => void;
};

export function JobList({ jobs, onCancel }: { jobs: JobItem[]; onCancel?: (job: JobItem) => Promise<void> }) {
  if (jobs.length === 0) {
    return (
      <div className="empty-state">
        <strong>No jobs</strong>
      </div>
    );
  }
  return (
    <div className="job-list">
      {jobs.map((job) => (
        <div className="job-row" key={job.id}>
          <span>
            <strong>{job.jobType.replaceAll("_", " ")}</strong>
            <small>{job.message ?? job.status}</small>
          </span>
          <div className="progress-wrap">
            <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} />
          </div>
          <small>{formatDate(job.createdAt)}</small>
          {onCancel && !job.cancelRequested && ["queued", "requested", "running"].includes(job.status) ? (
            <button className="button small danger subtle" onClick={() => void onCancel(job)} type="button">
              Cancel
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function EmptyPanel({ title }: { title: string }) {
  return (
    <section className="panel">
      <div className="empty-state">
        <strong>{title}</strong>
      </div>
    </section>
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
