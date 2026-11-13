import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi, beforeEach } from "vitest";
const ev = vi.hoisted(() => ({
  prepare: vi.fn(),
  generate: vi.fn(),
  graders: vi.fn(),
  preview: vi.fn(),
  start: vi.fn(),
}));
vi.mock("./evaluationApi", () => ({ evaluationApi: ev }));
vi.mock("./api", () => ({
  api: { listExecutorConfigs: vi.fn().mockResolvedValue({ items: [] }) },
}));
import { GenerationDialog, RunDialog } from "./EvaluationDialogs";
import type { EvalTask, Environment } from "./evaluationTypes";
beforeEach(() => {
  vi.clearAllMocks();
  ev.graders.mockResolvedValue({ items: [] });
  ev.prepare.mockResolvedValue({ id: "job" });
});
it("prepares complete linked assets from the existing generation control", async () => {
  const user = userEvent.setup();
  render(
    <GenerationDialog projectId="p" onClose={vi.fn()} onCreated={vi.fn()} />,
  );
  await user.type(
    screen.getByRole("textbox", { name: "评测方向" }),
    "Verify tool evidence",
  );
  await user.click(screen.getByRole("button", { name: "开始生成" }));
  await waitFor(() =>
    expect(ev.prepare).toHaveBeenCalledWith("p", 3, "Verify tool evidence"),
  );
  expect(ev.generate).not.toHaveBeenCalled();
});
it("reviews the actual resolved plan before starting target execution", async () => {
  const user = userEvent.setup();
  const onCreated = vi.fn();
  ev.preview.mockResolvedValue({
    plan_digest: "digest",
    grading_plan: {
      source: "task",
      tasks: [
        {
          title: "Query",
          source: "task",
          checks: [{ grader_name: "Facts", type: "judge", threshold: 0.9 }],
          not_applicable: [],
        },
      ],
    },
    models: { target: { model: "gpt-6-luna" }, judge: { model: "gpt-6-luna" } },
  });
  ev.start.mockResolvedValue({ id: "run" });
  const tasks = [
    {
      id: "t",
      version_id: "v",
      definition: { title: "Query", kind: "conversation" },
    },
  ] as EvalTask[];
  const environments = [
    {
      id: "env",
      status: "ready",
      events: [],
      plan: {
        limitations: [],
        services: [],
        network: [],
        credential_sources: [],
      },
    },
  ] as unknown as Environment[];
  render(
    <RunDialog
      projectId="p"
      tasks={tasks}
      environments={environments}
      onClose={vi.fn()}
      onCreated={onCreated}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "预检评分方案" }));
  expect(ev.start).not.toHaveBeenCalled();
  expect(await screen.findByText("Facts")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "确认并启动评测" }));
  await waitFor(() =>
    expect(ev.start).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({ plan_digest: "digest" }),
    ),
  );
  expect(ev.start.mock.calls[0][1]).not.toHaveProperty("grader_ids");
});
