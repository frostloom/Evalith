import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
const apiMock = vi.hoisted(() => ({
  listExecutorConfigs: vi.fn(),
  createExecutorConfig: vi.fn(),
  updateExecutorConfig: vi.fn(),
  deleteExecutorConfig: vi.fn(),
}));
vi.mock("./api", () => ({ api: apiMock }));
import { ExecutorSettings } from "./ExecutorSettings";
const saved = {
  id: "exe_a",
  name: "本地测试",
  backend: "local_command",
  command: ["python", "agent.py", "--dry-run"],
  working_directory: "/tmp/agent",
  base_url: null,
  timeout_seconds: 60,
  verified: false,
  execution_available: false,
  created_at: "2026-11-11T00:00:00Z",
  updated_at: "2026-11-11T00:00:00Z",
};
beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listExecutorConfigs.mockResolvedValue({ items: [] });
});
it("saves HTTP executor settings independently and shows an unverified state", async () => {
  const user = userEvent.setup();
  apiMock.createExecutorConfig.mockResolvedValue({
    ...saved,
    name: "HTTP 测试",
    backend: "http_api",
    command: [],
    working_directory: null,
    base_url: "http://127.0.0.1:8800/evaluate",
  });
  render(<ExecutorSettings />);
  await user.click(
    (await screen.findAllByRole("button", { name: "添加执行器" }))[0],
  );
  await user.type(screen.getByLabelText("配置名称"), "HTTP 测试");
  await user.selectOptions(screen.getByLabelText("执行后端"), "http_api");
  expect(screen.queryByLabelText("执行程序")).not.toBeInTheDocument();
  await user.type(
    screen.getByLabelText("API 地址"),
    "http://127.0.0.1:8800/evaluate",
  );
  await user.click(screen.getByRole("button", { name: "保存配置" }));
  expect(
    await screen.findByRole("heading", { name: "HTTP 测试" }),
  ).toBeVisible();
  expect(screen.getByText("未验证")).toBeVisible();
  expect(apiMock.createExecutorConfig).toHaveBeenCalledWith({
    name: "HTTP 测试",
    backend: "http_api",
    command: [],
    working_directory: null,
    base_url: "http://127.0.0.1:8800/evaluate",
    timeout_seconds: 60,
  });
});
it("restores command arguments for editing and keeps the form after a save error", async () => {
  const user = userEvent.setup();
  apiMock.listExecutorConfigs.mockResolvedValue({ items: [saved] });
  apiMock.updateExecutorConfig.mockRejectedValue(new Error("名称冲突"));
  render(<ExecutorSettings />);
  await user.click(await screen.findByRole("button", { name: "编辑" }));
  expect(screen.getByLabelText(/命令参数/)).toHaveValue("agent.py\n--dry-run");
  await user.click(screen.getByRole("button", { name: "保存配置" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("名称冲突");
  expect(screen.getByLabelText(/执行程序/)).toHaveValue("python");
});
it("confirms deletion and leaves a failed deletion visible in its dialog", async () => {
  const user = userEvent.setup();
  apiMock.listExecutorConfigs.mockResolvedValue({ items: [saved] });
  apiMock.deleteExecutorConfig.mockRejectedValue(new Error("删除失败"));
  render(<ExecutorSettings />);
  await user.click(await screen.findByRole("button", { name: "删除" }));
  const dialog = screen.getByRole("dialog", { name: "删除执行器配置？" });
  await user.click(within(dialog).getByRole("button", { name: "取消" }));
  expect(apiMock.deleteExecutorConfig).not.toHaveBeenCalled();
  await user.click(await screen.findByRole("button", { name: "删除" }));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("删除失败"),
  );
  expect(screen.getByRole("dialog")).toBeVisible();
});
