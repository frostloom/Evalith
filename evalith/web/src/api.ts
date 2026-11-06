import type { ModelConfig, Project, ProjectDetail } from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    let code = "http_error";
    try {
      const body = await response.json();
      message = body.error || body.detail || message;
      code = body.code || code;
    } catch {
      /* keep default */
    }
    throw new ApiError(message, code, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  listModels: () => request<{ items: ModelConfig[] }>("/api/model-configs"),
  createModel: (body: Record<string, unknown>) =>
    request<ModelConfig>("/api/model-configs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  testModel: (id: string) =>
    request<{ ok: boolean; message: string }>(`/api/model-configs/${id}/test`, {
      method: "POST",
    }),
  deleteModel: (id: string) =>
    request<void>(`/api/model-configs/${id}`, { method: "DELETE" }),

  listProjects: () => request<{ items: Project[] }>("/api/projects"),
  createProject: (body: Record<string, unknown>) =>
    request<ProjectDetail>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getProject: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}`),
  enterProject: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/enter`, { method: "POST" }),
  sendMessage: (id: string, content: string) =>
    request<ProjectDetail>(`/api/projects/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  continueProject: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/continue`, { method: "POST" }),
  rescan: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/rescan`, { method: "POST" }),
  reanalyse: (id: string) =>
    request<ProjectDetail>(`/api/projects/${id}/reanalyse`, { method: "POST" }),
  updateProjectModel: (id: string, modelConfigId: string | null) =>
    request<ProjectDetail>(`/api/projects/${id}/model`, {
      method: "PUT",
      body: JSON.stringify({ model_config_id: modelConfigId }),
    }),
  updateSources: (id: string, body: Record<string, unknown>) =>
    request<ProjectDetail>(`/api/projects/${id}/sources`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
