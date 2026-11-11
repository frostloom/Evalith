import { request } from "./api";
import type {
  Analysis,
  Environment,
  EvalRun,
  EvalTask,
  GenerationJob,
  TaskDefinition,
} from "./evaluationTypes";
const base = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
const send = (body: unknown) => ({
  method: "POST",
  body: JSON.stringify(body),
});
export const evaluationApi = {
  tasks: (id: string) => request<{ items: EvalTask[] }>(`${base(id)}/tasks`),
  jobs: (id: string) => request<{ items: GenerationJob[] }>(`${base(id)}/jobs`),
  generate: (id: string, count: number, direction: string) =>
    request<GenerationJob>(`${base(id)}/generate`, send({ count, direction })),
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
