import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { ModelSettings } from "./ModelSettings";
import type { ModelConfig } from "./types";

const legacy = {
  id: "m1",
  name: "GPT 账号",
  provider: "codex_local",
  base_url: null,
  model_name: "gpt-6-luna",
  has_api_key: false,
  last_test_ok: null,
  last_test_message: null,
  last_test_at: null,
  created_at: "2026-11-11T00:00:00Z",
} as ModelConfig;

const api = vi.hoisted(() => ({
  createModel: vi.fn(),
  testModel: vi.fn(),
  deleteModel: vi.fn(),
}));
vi.mock("./api", () => ({ api }));

it("keeps legacy account configs visible as removed and offers no ChatGPT login option", async () => {
  const user = userEvent.setup();
  render(
    <ModelSettings
      models={[legacy]}
      onRefresh={vi.fn().mockResolvedValue(undefined)}
      onBack={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  expect(screen.getByText("ChatGPT 账号（已移除）")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "添加模型服务" }));
  expect(
    screen.getByRole("option", { name: /离线演示/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: /OpenAI 兼容服务/ }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: /本地 ChatGPT/ }),
  ).not.toBeInTheDocument();
});
