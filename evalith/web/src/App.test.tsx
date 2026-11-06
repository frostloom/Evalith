import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  listModels: vi.fn(),
  createModel: vi.fn(),
  testModel: vi.fn(),
  deleteModel: vi.fn(),
  listProjects: vi.fn(),
  createProject: vi.fn(),
  getProject: vi.fn(),
  enterProject: vi.fn(),
  sendMessage: vi.fn(),
  continueProject: vi.fn(),
  rescan: vi.fn(),
  reanalyse: vi.fn(),
  updateSources: vi.fn(),
}));

vi.mock("./api", () => ({
  api: apiMock,
  ApiError: class ApiError extends Error {
    code = "test";
    status = 500;
  },
}));

import { App } from "./App";

function project(id: string, name: string) {
  return {
    id,
    name,
    root_path: `/tmp/${id}`,
    include_paths: [],
    exclude_patterns: [],
    supplemental: [],
    model_config_id: null,
    snapshot_id: `snp_${id}`,
    analysis_error: null,
    created_at: "2026-11-06T00:00:00Z",
    updated_at: "2026-11-06T00:00:00Z",
    file_count: 1,
    snapshot_digest: `digest_${id}`,
  };
}

function detail(id: string, name: string) {
  return {
    project: project(id, name),
    session: {
      id: `ses_${id}`,
      project_id: id,
      kind: "main",
      created_at: "2026-11-06T00:00:00Z",
    },
    messages: [],
    snapshot: {
      id: `snp_${id}`,
      digest: `digest_${id}`,
      root: `/tmp/${id}`,
      created_at: "2026-11-06T00:00:00Z",
      files: [],
      excluded: [],
      read_errors: [],
      selected_scope: [],
      file_count: 0,
      excluded_count: 0,
      read_error_count: 0,
    },
    understanding: {
      summary: `Summary for ${name}`,
      agent_or_flow: "",
      known: [],
      inferred: [],
      unknowns: [],
      sources: [],
      sufficient: false,
      user_continued: false,
      sufficient_reason: "",
      model: "stub",
      error: null,
      updated_at: "2026-11-06T00:00:00Z",
      snapshot_id: `snp_${id}`,
    },
    readiness: {
      generation_allowed: false,
      generation_implemented: false,
      unknowns_confirmed: false,
      reason: "not ready",
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listModels.mockResolvedValue({ items: [] });
  apiMock.listProjects.mockResolvedValue({
    items: [project("a", "Project A"), project("b", "Project B")],
  });
  apiMock.enterProject.mockImplementation((id: string) =>
    Promise.resolve(detail(id, id === "a" ? "Project A" : "Project B")),
  );
});

describe("import navigation", () => {
  it("accepts an import started from an existing workspace", async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockResolvedValue(detail("c", "Imported C"));
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getAllByRole("button", { name: /导入本地项目/ })[0]);
    await user.type(screen.getByLabelText("项目名称"), "Imported C");
    await user.type(
      screen.getByLabelText(/本地目录/),
      "/tmp/c",
    );
    await user.click(
      screen.getByRole("button", { name: "导入并生成初步理解" }),
    );
    await screen.findByRole("heading", { name: "Imported C" });
    expect(apiMock.createProject).toHaveBeenCalledTimes(1);
  });

  it("keeps model settings after a late import following sidebar navigation", async () => {
    let resolveImport: ((value: unknown) => void) | undefined;
    apiMock.createProject.mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getAllByRole("button", { name: /导入本地项目/ })[0]);
    await user.type(screen.getByLabelText("项目名称"), "Late C");
    await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
    await user.click(
      screen.getByRole("button", { name: "导入并生成初步理解" }),
    );
    await user.click(screen.getByRole("button", { name: "模型与凭据" }));
    await screen.findByRole("heading", { name: "配置会话使用的模型服务。" });
    await act(async () => {
      resolveImport?.(detail("c", "Late C"));
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Late C" })).toBeNull(),
    );
    expect(
      screen.getByRole("heading", { name: "配置会话使用的模型服务。" }),
    ).toBeInTheDocument();
  });

  it("ignores a late import response after cancellation", async () => {
    let resolveImport: ((value: unknown) => void) | undefined;
    apiMock.createProject.mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getAllByRole("button", { name: /导入本地项目/ })[0]);
    await user.type(screen.getByLabelText("项目名称"), "Late C");
    await user.type(
      screen.getByLabelText(/本地目录/),
      "/tmp/c",
    );
    await user.click(
      screen.getByRole("button", { name: "导入并生成初步理解" }),
    );
    await user.click(screen.getByRole("button", { name: "取消" }));
    await act(async () => {
      resolveImport?.(detail("c", "Late C"));
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Late C" })).toBeNull(),
    );
  });
});

describe("project switching", () => {
  it("resets the message draft when the user switches projects", async () => {
    const user = userEvent.setup();
    render(<App />);

    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    const composer = await screen.findByLabelText("给主会话发送消息");
    await user.type(composer, "draft for project A");

    await user.click(screen.getByRole("button", { name: /Project B.*文件/ }));
    await screen.findByRole("heading", { name: "Project B" });

    expect(screen.getByLabelText("给主会话发送消息")).toHaveValue("");
  });

  it("keeps the visible project when switching to another fails", async () => {
    apiMock.enterProject.mockImplementation((id: string) => {
      if (id === "b") return Promise.reject(new Error("cannot open B"));
      return Promise.resolve(detail("a", "Project A"));
    });
    const updatedA = detail("a", "Project A");
    updatedA.messages = [
      {
        id: "msg_1",
        role: "assistant",
        content: "recovered after failure",
        payload: { kind: "chat" },
        model: null,
        sent_scope: null,
        created_at: "2026-11-06T00:00:00Z",
      },
    ] as never;
    apiMock.sendMessage.mockResolvedValue(updatedA);

    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("button", { name: /Project B.*文件/ }));
    await screen.findByText("cannot open B");
    await screen.findByRole("heading", { name: "Project A" });

    const composer = screen.getByLabelText("给主会话发送消息");
    await user.type(composer, "still A");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("recovered after failure");
  });

  it("ignores a late response from the project the user left", async () => {
    let resolveA: ((value: unknown) => void) | undefined;
    apiMock.enterProject.mockImplementation((id: string) => {
      if (id === "a") {
        return new Promise((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve(detail("b", "Project B"));
    });

    const user = userEvent.setup();
    render(<App />);

    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await user.click(
      within(main).getByRole("button", { name: /Project B.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project B" });

    await act(async () => {
      resolveA?.(detail("a", "Project A"));
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Project B" })).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("heading", { name: "Project A" }),
    ).not.toBeInTheDocument();
  });
});
