export type Usage = {
  model_calls?: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
};
export type Check = {
  type: string;
  expected?: unknown;
  path?: string;
  description?: string;
  status?: string;
  actual?: unknown;
  reason?: string;
  score?: number | null;
  evidence?: string[];
  grader_name?: string;
  grader_version?: number;
  grader_id?: string;
  threshold?: number;
  judge_model?: string;
  uncertainties?: string[];
};
export type TaskDefinition = {
  title: string;
  category: string;
  objective: string;
  kind: "conversation" | "command" | "http";
  input: Record<string, unknown>;
  checks: Check[];
  rubric: string;
  source_refs: string[];
  uncertainties: string[];
};
export type EvalTask = {
  id: string;
  task_id: string;
  definition: TaskDefinition;
  version: number;
  version_id: string;
  calibration_state: string;
  source_digest: string;
  model: string;
  created_at: string;
  default_grader_ids?: string[];
};
export type Environment = {
  id: string;
  status: string;
  adapter: string;
  plan_digest: string;
  error?: string | null;
  events: { at: string; message: string }[];
  plan: {
    source_directory: string;
    write_directory: string;
    copy_scope: string;
    services: string[];
    network: string[];
    credential_sources: string[];
    cost_note: string;
    cleanup: string;
    limitations: string[];
  };
};
export type EvalResult = {
  id: string;
  task: EvalTask;
  status: string;
  score: number | null;
  checks: Check[];
  observation: Record<string, unknown> | null;
  error: string | null;
  duration_ms?: number | null;
};
export type EvalRun = {
  name?: string;
  test_set_id?: string | null;
  test_set_snapshot?: TestSet | null;
  id: string;
  status: string;
  tasks: EvalTask[];
  results: EvalResult[];
  error: string | null;
  created_at: string;
  graders?: Grader[];
  grading_source?: string;
  grading_plan?: GradingPlan;
  environment_id: string;
  environment_snapshot: Environment;
  models: {
    target: { model: string; name: string };
    judge: { model: string; name: string };
  };
  usage: Usage;
  budget: { max_model_calls: number; budget_usd: number | null };
  cleanup_status: string;
};
export type Analysis = {
  id: string;
  run_id: string;
  status: string;
  selection: string;
  result_ids: string[];
  created_at: string;
  model: string;
  usage: Usage;
  error: string | null;
  report: {
    summary: string;
    facts: { text: string; result_ids: string[] }[];
    hypotheses: { text: string; result_ids: string[] }[];
    recommendations: string[];
    limitations: string[];
  } | null;
};
export type GenerationJob = {
  id: string;
  status: string;
  count: number;
  error: string | null;
  usage: Usage | null;
  operation?: string;
  result?: {
    task_ids: string[];
    grader_ids: string[];
    test_set_id?: string | null;
  };
};

export type GraderDefinition = {
  name: string;
  description: string;
  rubric: string;
  steps: string[];
  check: Check;
  model_config_id: string | null;
  threshold: number;
  task_kinds?: string[];
  source_refs?: string[];
  uncertainties?: string[];
};
export type Grader = GraderDefinition & {
  id: string;
  version: number;
  calibration_state: string;
  created_at: string;
  status: string;
};
export type TestSet = {
  id: string;
  name: string;
  description: string;
  task_ids: string[];
  grader_ids: string[];
  created_at: string;
  status: string;
  origin?: string;
};

export type GradingPlan = {
  source: string;
  tasks: {
    task_id: string;
    version_id: string;
    title: string;
    source: string;
    checks: Check[];
    not_applicable: {
      grader_id: string;
      grader_name: string;
      reason: string;
    }[];
  }[];
};
export type RunPreview = {
  plan_digest: string;
  grading_plan: GradingPlan;
  models: EvalRun["models"];
};
