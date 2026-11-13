import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { EvaluationRunView } from "./EvaluationRunView";
import type { EvalRun } from "./evaluationTypes";
const run = {
  id: "r",
  name: "账户回归",
  status: "completed",
  created_at: "2026-11-13T01:00:00Z",
  tasks: [{}],
  results: [
    {
      id: "result",
      task: {
        version: 1,
        definition: { title: "Query", objective: "Use the tool" },
      },
      status: "passed",
      score: 1,
      checks: [
        {
          type: "judge",
          grader_id: "g",
          grader_name: "Tool evidence",
          status: "passed",
          threshold: 0.9,
        },
      ],
      observation: {},
      error: null,
    },
  ],
  models: {
    target: { model: "gpt-6-luna", name: "Target" },
    judge: { model: "gpt-6-luna", name: "Judge" },
  },
  graders: [
    {
      id: "g",
      name: "Tool evidence",
      version: 2,
      rubric: "Use the observed tool facts",
      threshold: 0.9,
      check: { type: "judge" },
    },
  ],
  environment_snapshot: {
    adapter: "aigateway_go",
    plan: { write_directory: "/owned", limitations: [] },
  },
  usage: { model_calls: 3 },
  budget: { max_model_calls: 6 },
  cleanup_status: "completed",
} as unknown as EvalRun;
it("opens a saved run from the list and exposes its frozen configuration", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <EvaluationRunView
      runs={[run]}
      run={run}
      section="runs"
      selectedRunId={null}
      busy={false}
      selectedResultIds={[]}
      onSelect={onSelect}
      onResult={vi.fn()}
      onSelection={vi.fn()}
      onAnalyze={vi.fn()}
      onCancel={vi.fn()}
    >
      {null}
    </EvaluationRunView>,
  );
  await user.click(screen.getByRole("button", { name: /账户回归/ }));
  expect(onSelect).toHaveBeenCalledWith("r");
  await user.click(screen.getByRole("tab", { name: "运行配置" }));
  expect(screen.getByText("Use the observed tool facts")).toBeVisible();
  expect(screen.getByText(/通过阈值 ≥ 0.9/)).toBeVisible();
  await user.click(screen.getByRole("tab", { name: "测试结果" }));
  expect(screen.getByRole("button", { name: /Query/ })).toBeVisible();
});
