export type ModelConfig = {
  id: string;
  name: string;
  provider: "stub" | "openai_compatible" | "codex_local";
  base_url: string | null;
  model_name: string;
  has_api_key: boolean;
  last_test_ok: number | null;
  last_test_message: string | null;
  last_test_at: string | null;
  created_at: string;
};

export type SourceRef = {
  path: string;
  sha256?: string;
  size?: number;
  sent?: boolean;
  reason?: string;
  redactions?: number;
  supplemental?: boolean;
};

export type UnderstandingItem = {
  text?: string;
  source?: string;
  basis?: string;
  why?: string;
};

export type Understanding = {
  stale: boolean;
  summary: string;
  agent_or_flow: string;
  known: Array<UnderstandingItem | string>;
  inferred: Array<UnderstandingItem | string>;
  unknowns: Array<UnderstandingItem | string>;
  sources: SourceRef[];
  sufficient: boolean;
  user_continued: boolean;
  sufficient_reason: string;
  model: string | null;
  error: string | null;
  updated_at: string;
  snapshot_id: string;
};

export type SnapshotFile = {
  path: string;
  sha256: string;
  size: number;
  binary: boolean;
  redactions: number;
  context_included: boolean;
  reason: string | null;
};

export type Snapshot = {
  id: string;
  digest: string;
  root: string;
  created_at: string;
  files: SnapshotFile[];
  excluded: Array<{ path: string; reason: string }>;
  read_errors: Array<{ path: string; error: string; code: string }>;
  selected_scope: string[];
  file_count: number;
  excluded_count: number;
  read_error_count: number;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  payload: {
    kind?: string;
    understanding?: Understanding;
    sent_scope?: SentScope;
    message?: string;
    stage?: string;
    [key: string]: unknown;
  } | null;
  model: string | null;
  sent_scope: SentScope | null;
  created_at: string;
};

export type SentScope = {
  root: string;
  snapshot_digest: string;
  files_sent: number;
  files_listed: number;
  bytes_sent: number;
  redactions: number;
  sources: SourceRef[];
};

export type Project = {
  id: string;
  name: string;
  root_path: string;
  include_paths: string[];
  exclude_patterns: string[];
  supplemental: Array<{ title: string; content: string }>;
  model_config_id: string | null;
  snapshot_id: string | null;
  analysis_error: string | null;
  created_at: string;
  updated_at: string;
  file_count: number;
  snapshot_digest: string | null;
};

export type Readiness = {
  generation_allowed: boolean;
  generation_implemented: boolean;
  unknowns_confirmed: boolean;
  reason: string;
};

export type ProjectDetail = {
  project: Project;
  session: { id: string; project_id: string; kind: string; created_at: string };
  messages: Message[];
  snapshot: Snapshot | null;
  understanding: Understanding | null;
  readiness: Readiness;
};

export type WorkspaceTab = "overview" | "conversation" | "sources" | "tasks" | "runs" | "analyses" | "graders" | "sets";

export type ExecutorDefinition = {
  name: string;
  backend: "local_command" | "http_api" | "harbor";
  command: string[];
  working_directory: string | null;
  base_url: string | null;
  timeout_seconds: number;
};
export type ExecutorConfig = ExecutorDefinition & {
  id: string;
  created_at: string;
  updated_at: string;
  verified: false;
  execution_available: false;
};
