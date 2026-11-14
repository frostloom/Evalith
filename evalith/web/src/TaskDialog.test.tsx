import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
const ev = vi.hoisted(() => ({ versions: vi.fn(), edit: vi.fn() }));
vi.mock("./evaluationApi", () => ({ evaluationApi: ev }));
import { TaskDialog } from "./EvaluationDialogs";
import type { EvalTask } from "./evaluationTypes";
import type { ModelConfig } from "./types";

const task = {
  id: "t1",
  task_id: "t1",
  version: 1,
  version_id: "v1",
  calibration_state: "unverified",
  source_digest: "d",
  model: "m",
  created_at: "2026-11-14T00:00:00Z",
  definition: {
    title: "Adaptive balance",
    category: "Conversation",
    objective: "Multi-turn inquiry",
    kind: "conversation",
    input: {
      turns: ["你好，帮我查一下余额"],
      adaptive: {
        max_turns: 3,
        instruction: "追问币种后结束",
        simulator_model_config_id: null,
      },
    },
    checks: [{ type: "not_contains", expected: "forbidden" }],
    rubric: "Facts only",
    source_refs: ["README.md"],
    uncertainties: [],
  },
} as EvalTask;

const models = [
  {
    id: "m1",
    name: "Sim",
    provider: "openai_compatible",
    model_name: "gpt-test",
  },
] as ModelConfig[];

beforeEach(() => {
  vi.clearAllMocks();
  ev.versions.mockResolvedValue({ items: [task] });
});

it("edits adaptive turn settings on conversation tasks", async () => {
  const user = userEvent.setup();
  render(
    <TaskDialog
      projectId="p"
      task={task}
      models={models}
      onClose={vi.fn()}
      onSaved={vi.fn()}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "编辑题目" }));
  const checkbox = screen.getByRole("checkbox", {
    name: /自适应后续轮次/,
  }) as HTMLInputElement;
  expect(checkbox.checked).toBe(true);
  const instruction = screen.getByLabelText(
    "场景指令（模拟器如何扮演用户）",
  ) as HTMLInputElement;
  expect(instruction.value).toBe("追问币种后结束");
  expect(screen.getByLabelText("模拟器模型")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加一轮" })).toBeDisabled();

  await user.click(checkbox);
  expect(screen.queryByLabelText(/场景指令/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加一轮" })).not.toBeDisabled();
});
