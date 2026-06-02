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

export type TimestampWord = {
  word: string;
  start: number;
  end: number;
};

export type TimestampSegment = {
  id: string;
  index: number;
  start: number;
  end: number;
  text: string;
  words: TimestampWord[];
};

export type TimestampWarning = {
  segmentId: string;
  index: number;
  severity: "info" | "warning" | "danger";
  message: string;
};

export type TimestampVersion = {
  id: number;
  filePath: string;
  versionLabel: string;
  createdAt: string;
  createdBy: string;
  notes?: string | null;
  isApproved: boolean;
};

export type TimestampsPayload = {
  projectId: string;
  source: "current" | "draft";
  sourcePath: string;
  activePath: string;
  draftPath: string;
  hasDraft: boolean;
  segmentCount: number;
  duration: number;
  segments: TimestampSegment[];
  warnings: TimestampWarning[];
  versions: TimestampVersion[];
};

export type TimestampCheckPayload = {
  projectId: string;
  segmentCount: number;
  duration: number;
  segments: TimestampSegment[];
  warnings: TimestampWarning[];
};

export type TemplateOption = {
  id: number;
  name: string;
  description: string;
  aspectRatio: string;
  settings: DesignSettings;
  createdAt: string;
  updatedAt: string;
  isDefault: boolean;
};

export type DesignSettings = {
  template: string;
  aspectRatio: string;
  resolution: string;
  fps: number;
  backgroundType: string;
  backgroundColor: string;
  fontFamily: string;
  fontSize: number;
  textColor: string;
  highlightColor: string;
  animation: string;
  textPosition: string;
  watermark: boolean;
};

export type ProjectDesign = {
  projectId: string;
  templateId?: number | null;
  templateName: string;
  settings: DesignSettings;
  isSaved: boolean;
  updatedAt?: string;
  designPath: string;
  renderPropsPath: string;
};

export type RenderReadinessCheck = {
  key: string;
  label: string;
  ok: boolean;
  fix: string;
};

export type RenderReadiness = {
  projectId: string;
  ready: boolean;
  checks: RenderReadinessCheck[];
  freeDiskBytes: number;
  warnings: TimestampWarning[];
  renderOptions: Record<string, string | number | boolean>;
};

export type JobItem = {
  id: number;
  projectId: string;
  jobType: string;
  status: string;
  progress: number;
  message?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  errorMessage?: string | null;
  logPath?: string | null;
  cancelRequested: boolean;
  createdAt: string;
};

export type UploadMetadata = {
  projectId?: string;
  title: string;
  description: string;
  tags: string[];
  privacy: "private" | "unlisted" | "public";
  madeForKids: boolean;
  playlist: string;
  thumbnailPath: string;
  scheduleTime: string;
  metadataPath?: string;
  publishedUrl?: string;
};

export type AppSettings = {
  theme: string;
  defaultCountry: string;
  defaultPrivacy: "private" | "unlisted" | "public";
  autosaveSeconds: number;
  renderQuality: string;
  previewResolution: string;
  workspaceRoot: string;
  databasePath: string;
  remotionPath: string;
};
