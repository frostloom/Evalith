import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({
  tasks: vi.fn(),
  jobs: vi.fn(),
  runs: vi.fn(),
  analyses: vi.fn(),
  environments: vi.fn(),
  versions: vi.fn(),
  generate: vi.fn(),
  edit: vi.fn(),
  plan: vi.fn(),
  confirm: vi.fn(),
  start: vi.fn(),
  cancel: vi.fn(),
  analyze: vi.fn(),
}));
vi.mock("./evaluationApi", () => ({ evaluationApi: mock }));
vi.mock("./api", () => ({
  api: { listExecutorConfigs: vi.fn().mockResolvedValue({ items: [] }) },
}));
import { EvaluationWorkspace } from "./EvaluationWorkspace";
import type { ProjectDetail } from "./types";
const task = {
  id: "t1",
  version: 2,
  version_id: "v2",
  task_id: "t1",
  model: "openai_compatible:gpt-6-luna",
  calibration_state: "unverified",
  source_digest: "hash",
  created_at: "2026-11-11T00:00:00Z",
  definition: {
    title: "余额查询",
    category: "查询",
    objective: "读取合成余额",
    kind: "conversation",
    input: { turns: ["查余额"] },
    checks: [{ type: "contains", expected: "2000" }],
    rubric: "依据工具结果",
    source_refs: ["README.md"],
    uncertainties: [],
  },
};
const detail = {
  project: { id: "p1", name: "Gateway" },
  readiness: { generation_allowed: true },
} as ProjectDetail;
beforeEach(() => {
  vi.clearAllMocks();
  mock.tasks.mockResolvedValue({ items: [task] });
  for (const key of ["jobs", "runs", "analyses", "environments"] as const)
    mock[key].mockResolvedValue({ items: [] });
  mock.versions.mockResolvedValue({ items: [task] });
});
it("opens the selected revision and saves an edited definition as a new version", async () => {
  const user = userEvent.setup();
  mock.edit.mockResolvedValue({ ...task, version: 3 });
  render(
    <EvaluationWorkspace detail={detail} section="tasks" onSection={vi.fn()} />,
  );
  await user.click(
    await screen.findByRole("button", { name: "查看题目 余额查询" }),
  );
  await user.click(screen.getByRole("button", { name: "编辑题目" }));
  const title = screen.getByRole("textbox", { name: "题目名称" });
  await user.clear(title);
  await user.type(title, "准确查询余额");
  const expected = screen.getByRole("textbox", { name: "期望值" });
  await user.clear(expected);
  await user.type(expected, "2500");
  await user.click(screen.getByRole("button", { name: "保存新版本" }));
  await waitFor(() =>
    expect(mock.edit).toHaveBeenCalledWith(
      "p1",
      "t1",
      expect.objectContaining({
        title: "准确查询余额",
        checks: [
          expect.objectContaining({ type: "contains", expected: "2500" }),
        ],
      }),
    ),
  );
});
it("blocks generation when project readiness is closed", async () => {
  render(
    <EvaluationWorkspace
      detail={{
        ...detail,
        readiness: {
          ...detail.readiness,
          generation_allowed: false,
          reason: "资料已变化",
        },
      }}
      section="tasks"
      onSection={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "生成题目" }),
  ).toBeDisabled();
  expect(screen.getByText("资料已变化")).toBeInTheDocument();
});
it("explains bound graders before editing a generated task's fallback rules", async () => {
  const user = userEvent.setup();
  mock.tasks.mockResolvedValue({
    items: [{ ...task, default_grader_ids: ["g"] }],
  });
  mock.versions.mockResolvedValue({
    items: [{ ...task, default_grader_ids: ["g"] }],
  });
  render(
    <EvaluationWorkspace detail={detail} section="tasks" onSection={vi.fn()} />,
  );
  await user.click(
    await screen.findByRole("button", { name: "查看题目 余额查询" }),
  );
  await user.click(screen.getByRole("tab", { name: "Rubric 与检查" }));
  expect(screen.getByText(/当前默认使用绑定的 Grader/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "编辑题目" }));
  expect(
    screen.getByText(/修改 Rubric 或检查后，新版本会改用内置规则/),
  ).toBeVisible();
});
