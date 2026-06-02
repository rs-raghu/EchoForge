export type Tone = "neutral" | "review" | "warning" | "success" | "danger" | "muted" | "processing";

export type SummaryCard = {
  key: string;
  label: string;
  value: number;
  tone: Tone;
};

export type ChecklistItem = {
  key: string;
  label: string;
  done: boolean;
};

export type ReadyFiles = {
  audio: boolean;
  lyrics: boolean;
  timestamps: boolean;
  draftTimestamps: boolean;
  preview: boolean;
  final: boolean;
  published: boolean;
  design: boolean;
};

export type ProjectSummary = {
  id: string;
  videoId: string;
  title: string;
  artist: string;
  sourceUrl: string;
  rawState: string;
  studioState: string;
  statusLabel: string;
  statusTone: Tone;
  microState: string;
  targetState: string;
  workspacePath: string;
  updatedAt: string;
  progress: number;
  nextAction: string;
  primaryAction: string | null;
  checklist: ChecklistItem[];
  filesReady: ReadyFiles;
};

export type ProjectFile = {
  name: string;
  relativePath: string;
  size: number;
  updatedAt: string;
  kind: string;
};

export type LogItem = {
  time: string;
  level: "info" | "warning" | "error";
  projectId?: string | null;
  message: string;
  eventType?: string;
};

export type DashboardPayload = {
  summary: SummaryCard[];
  activeProjects: ProjectSummary[];
  queue: ProjectSummary[];
  recentProjects: ProjectSummary[];
  stateCounts: Record<string, number>;
  logs: LogItem[];
};

export type ProjectDetail = ProjectSummary & {
  files: ProjectFile[];
  logs: LogItem[];
};

export type LyricLineType = "lyric" | "section_label" | "instrumental" | "note";

export type LyricLine = {
  id: string;
  index: number;
  type: LyricLineType;
  text: string;
  timestamp?: string | null;
  raw?: string;
};

export type LyricWarning = {
  lineId: string;
  index: number;
  severity: "info" | "warning" | "danger";
  message: string;
};

export type LyricsVersion = {
  id: number;
  filePath: string;
  versionLabel: string;
  createdAt: string;
  createdBy: string;
  notes?: string | null;
  isApproved: boolean;
};

export type LyricsPayload = {
  projectId: string;
  source: "current" | "draft";
  sourcePath: string;
  activePath: string;
  draftPath: string;
  format: "text" | "lrc";
  hasDraft: boolean;
  rawText: string;
  lines: LyricLine[];
  warnings: LyricWarning[];
  versions: LyricsVersion[];
};
