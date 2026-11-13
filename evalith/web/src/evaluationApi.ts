import { request } from "./api";
import type {
  RunPreview,
  Analysis,
  Environment,
  EvalRun,
  EvalTask,
  GenerationJob,
  TaskDefinition,
  Grader,
  GraderDefinition,
  TestSet,
} from "./evaluationTypes";
const base = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
const send = (body: unknown) => ({
  method: "POST",
  body: JSON.stringify(body),
});
export const evaluationApi = {
  getSet: (id: string, sid: string) =>
    request<TestSet>(`${base(id)}/test-sets/${encodeURIComponent(sid)}`),
  graders: (id: string) => request<{ items: Grader[] }>(`${base(id)}/graders`),
  saveGrader: (id: string, body: GraderDefinition, gid?: string) =>
    request<Grader>(`${base(id)}/graders${gid ? "/" + gid : ""}`, {
      ...send(body),
      method: gid ? "PUT" : "POST",
    }),
  archiveGrader: (id: string, gid: string) =>
    request<void>(`${base(id)}/graders/${gid}`, { method: "DELETE" }),
  sets: (id: string) => request<{ items: TestSet[] }>(`${base(id)}/test-sets`),
  saveSet: (
    id: string,
    body: Pick<TestSet, "name" | "description" | "task_ids" | "grader_ids">,
    sid?: string,
  ) =>
    request<TestSet>(`${base(id)}/test-sets${sid ? "/" + sid : ""}`, {
      ...send(body),
      method: sid ? "PUT" : "POST",
    }),
  tasks: (id: string) => request<{ items: EvalTask[] }>(`${base(id)}/tasks`),
  jobs: (id: string) => request<{ items: GenerationJob[] }>(`${base(id)}/jobs`),
  generate: (id: string, count: number, direction: string) =>
    request<GenerationJob>(`${base(id)}/generate`, send({ count, direction })),
  prepare: (id: string, count: number, direction: string) =>
    request<GenerationJob>(
      `${base(id)}/preparations`,
      send({ count, direction }),
    ),
  synthesizeGrader: (id: string, description: string) =>
    request<{ draft: GraderDefinition; usage: unknown }>(
      `${base(id)}/graders/synthesize`,
      send({ description }),
    ),
  preview: (id: string, body: unknown) =>
    request<RunPreview>(`${base(id)}/runs/preview`, send(body)),
  edit: (id: string, task: string, body: TaskDefinition) =>
    request<EvalTask>(`${base(id)}/tasks/${task}`, {
      ...send(body),
      method: "PUT",
    }),
  versions: (id: string, task: string) =>
    request<{ items: EvalTask[] }>(`${base(id)}/tasks/${task}/versions`),
  environments: (id: string) =>
    request<{ items: Environment[] }>(`${base(id)}/environments`),
  plan: (id: string, body: unknown) =>
    request<Environment>(`${base(id)}/environments/plan`, send(body)),
  confirm: (id: string, env: Environment) =>
    request<Environment>(
      `${base(id)}/environments/${env.id}/confirm`,
      send({ plan_digest: env.plan_digest }),
    ),
  runs: (id: string) => request<{ items: EvalRun[] }>(`${base(id)}/runs`),
  run: (id: string, run: string) => request<EvalRun>(`${base(id)}/runs/${run}`),
  start: (id: string, body: unknown) =>
    request<EvalRun>(`${base(id)}/runs`, send(body)),
  cancel: (id: string, run: string) =>
    request<EvalRun>(`${base(id)}/runs/${run}/cancel`, send({})),
  analyses: (id: string) =>
    request<{ items: Analysis[] }>(`${base(id)}/analyses`),
  analyze: (id: string, run: string, body: unknown) =>
    request<Analysis>(`${base(id)}/runs/${run}/analyses`, send(body)),
};
