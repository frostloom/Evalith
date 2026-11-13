import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
const ev = vi.hoisted(() => ({
  graders: vi.fn(),
  tasks: vi.fn(),
  sets: vi.fn(),
  saveGrader: vi.fn(),
  saveSet: vi.fn(),
  archiveGrader: vi.fn(),
  synthesizeGrader: vi.fn(),
}));
vi.mock("./evaluationApi", () => ({ evaluationApi: ev }));
import { EvaluationLibraryPage } from "./EvaluationLibraryPage";
import type { ProjectDetail, ModelConfig } from "./types";
const detail = {
  project: { id: "p", name: "Gateway", model_config_id: "m" },
} as ProjectDetail;
const models = [
  {
    id: "m",
    name: "GPT local",
    provider: "codex_local",
    model_name: "gpt-6-luna",
  },
] as ModelConfig[];
beforeEach(() => {
  vi.clearAllMocks();
  ev.graders.mockResolvedValue({ items: [] });
  ev.tasks.mockResolvedValue({ items: [] });
  ev.sets.mockResolvedValue({ items: [] });
  ev.saveGrader.mockResolvedValue({ id: "g" });
});
it("fills an editable grader draft from a requirement without saving it automatically", async () => {
  const user = userEvent.setup();
  ev.synthesizeGrader.mockResolvedValue({
    draft: {
      name: "工具事实",
      description: "Check actual traces",
      rubric: "Only pass with observed evidence",
      steps: ["Locate evidence", "Compare claims", "Score"],
      check: { type: "judge", expected: "Use facts" },
      threshold: 0.9,
      model_config_id: "m",
      task_kinds: ["conversation"],
      source_refs: ["README.md"],
      uncertainties: [],
    },
  });
  render(
    <EvaluationLibraryPage
      detail={detail}
      section="graders"
      models={models}
      onOpenSet={vi.fn()}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "新建评价标准" }));
  await user.click(screen.getByRole("textbox", { name: "评分要求" }));
  await user.paste("Check tool-backed balance facts");
  await user.click(screen.getByRole("button", { name: "生成 Grader 草稿" }));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "评分 Rubric" })).toHaveValue(
      "Only pass with observed evidence",
    ),
  );
  expect(ev.saveGrader).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "下一步：确认配置" }));
  await user.click(screen.getByRole("button", { name: "创建评价标准" }));
  await waitFor(() =>
    expect(ev.saveGrader).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({
        rubric: "Only pass with observed evidence",
        threshold: 0.9,
        task_kinds: ["conversation"],
      }),
      undefined,
    ),
  );
});
it("lets a collection explicitly remove an archived standard before saving", async () => {
  ev.tasks.mockResolvedValue({
    items: [
      {
        id: "t",
        version: 1,
        definition: { title: "余额查询", category: "查询" },
      },
    ],
  });
  ev.sets.mockResolvedValue({
    items: [
      {
        id: "s",
        name: "余额回归",
        task_ids: ["t"],
        grader_ids: ["archived"],
        created_at: "2026-11-13T00:00:00Z",
      },
    ],
  });
  ev.saveSet.mockResolvedValue({ id: "s" });
  const user = userEvent.setup();
  render(
    <EvaluationLibraryPage
      detail={detail}
      section="sets"
      models={models}
      onOpenSet={vi.fn()}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "配置" }));
  await user.click(
    screen.getByRole("checkbox", { name: /已归档或不可用的标准/ }),
  );
  await user.click(screen.getByRole("button", { name: "保存测试集" }));
  await waitFor(() =>
    expect(ev.saveSet).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({ grader_ids: [], task_ids: ["t"] }),
      "s",
    ),
  );
});
it("reviews a judge configuration before persisting the criterion and threshold", async () => {
  const u = userEvent.setup();
  render(
    <EvaluationLibraryPage
      detail={detail}
      section="graders"
      models={models}
      onOpenSet={vi.fn()}
    />,
  );
  await u.click(await screen.findByRole("button", { name: "新建评价标准" }));
  await u.type(screen.getByRole("textbox", { name: "标准名称" }), "工具依据");
  await u.type(
    screen.getByRole("textbox", { name: "评分 Rubric" }),
    "回答必须依据实际工具结果",
  );
  await u.clear(screen.getByRole("spinbutton", { name: "通过阈值" }));
  await u.type(screen.getByRole("spinbutton", { name: "通过阈值" }), "0.9");
  await u.click(screen.getByRole("button", { name: "下一步：确认配置" }));
  expect(ev.saveGrader).not.toHaveBeenCalled();
  await u.click(screen.getByRole("button", { name: "创建评价标准" }));
  await waitFor(() =>
    expect(ev.saveGrader).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({
        name: "工具依据",
        threshold: 0.9,
        model_config_id: "m",
        rubric: "回答必须依据实际工具结果",
      }),
      undefined,
    ),
  );
});
