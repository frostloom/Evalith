import { StrictMode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  listModels: vi.fn(),
  listExecutorConfigs: vi.fn(),
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
  window.history.replaceState(null, "", "/");
  apiMock.listModels.mockResolvedValue({ items: [] });
  apiMock.listExecutorConfigs.mockResolvedValue({ items: [] });
  apiMock.listProjects.mockResolvedValue({
    items: [project("a", "Project A"), project("b", "Project B")],
  });
  apiMock.enterProject.mockImplementation((id: string) =>
    Promise.resolve(detail(id, id === "a" ? "Project A" : "Project B")),
  );
});

async function selectProject(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  const namePattern = new RegExp(`${name}.*文件`);
  const switcher = screen.queryByRole("button", { name: "切换项目" });
  if (switcher && !screen.queryByRole("button", { name: namePattern })) {
    await user.click(switcher);
  }
  await user.click(await screen.findByRole("button", { name: namePattern }));
}
async function importProject(user: ReturnType<typeof userEvent.setup>) {
  const switcher = screen.queryByRole("button", { name: "切换项目" });
  if (switcher) await user.click(switcher);
  await user.click(
    (await screen.findAllByRole("button", { name: "建立项目" }))[0],
  );
}

it("keeps workspace updates under StrictMode", async () => {
  const updatedA = detail("a", "Project A");
  updatedA.messages = [
    {
      id: "msg_strict",
      role: "assistant",
      content: "strict mode update",
      payload: { kind: "chat" },
      model: null,
      sent_scope: null,
      created_at: "2026-11-06T00:00:00Z",
    },
  ] as never;
  apiMock.sendMessage.mockResolvedValue(updatedA);
  const user = userEvent.setup();
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  const main = screen.getByRole("main");
  await user.click(
    await within(main).findByRole("button", { name: /Project A.*文件/ }),
  );
  await screen.findByRole("heading", { name: "Project A" });
  await user.click(screen.getByRole("tab", { name: "主会话" }));
  await user.type(screen.getByLabelText("给主会话发送消息"), "hello");
  await user.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByText("strict mode update");
});

describe("import navigation", () => {
  it("accepts an import started from an existing workspace", async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockResolvedValue(detail("c", "Imported C"));
    apiMock.listProjects.mockResolvedValue({
      items: [
        project("a", "Project A"),
        project("b", "Project B"),
        project("c", "Imported C"),
      ],
    });
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await importProject(user);
    await user.type(screen.getByLabelText("项目名称"), "Imported C");
    await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
    await user.click(screen.getByRole("button", { name: "建立项目" }));
    await screen.findByRole("button", { name: /Imported C.*文件/ });
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
    await importProject(user);
    await user.type(screen.getByLabelText("项目名称"), "Late C");
    await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
    await user.click(screen.getByRole("button", { name: "建立项目" }));
    if (screen.queryByRole("dialog", { name: "建立项目" }))
      await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "模型配置" }));
    await screen.findByRole("heading", { name: "模型配置" });
    await act(async () => {
      resolveImport?.(detail("c", "Late C"));
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Late C" })).toBeNull(),
    );
    expect(
      screen.getByRole("heading", { name: "模型配置" }),
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
    await importProject(user);
    await user.type(screen.getByLabelText("项目名称"), "Late C");
    await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
    await user.click(screen.getByRole("button", { name: "建立项目" }));
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
    await screen.findByRole("tab", { name: "主会话" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    const composer = await screen.findByLabelText("给主会话发送消息");
    await user.type(composer, "draft for project A");

    await selectProject(user, "Project B");
    await screen.findByRole("heading", { name: "Project B" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));

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
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await selectProject(user, "Project B");
    await screen.findByText("cannot open B");
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));

    const composer = screen.getByLabelText("给主会话发送消息");
    await user.type(composer, "still A");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("recovered after failure");
  });

  it("keeps workspace updates after returning from model settings", async () => {
    const updatedA = detail("a", "Project A");
    updatedA.messages = [
      {
        id: "msg_back",
        role: "assistant",
        content: "message after settings",
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
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    if (screen.queryByRole("dialog", { name: "建立项目" }))
      await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "模型配置" }));
    await screen.findByRole("heading", { name: "模型配置" });
    await user.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(screen.getByLabelText("给主会话发送消息"), "after back");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("message after settings");
  });

  it("does not publish a delayed rejection from an abandoned workspace", async () => {
    let rejectSend: ((reason?: unknown) => void) | undefined;
    apiMock.sendMessage.mockReturnValue(
      new Promise((_, reject) => {
        rejectSend = reject;
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(screen.getByLabelText("给主会话发送消息"), "old failure");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await selectProject(user, "Project B");
    await screen.findByRole("heading", { name: "Project B" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await act(async () => {
      rejectSend?.(new Error("A request failed"));
    });
    await waitFor(() =>
      expect(screen.queryByText("A request failed")).toBeNull(),
    );
  });

  it("does not publish editor completion from an abandoned workspace", async () => {
    let resolveSources: ((value: unknown) => void) | undefined;
    apiMock.updateSources.mockReturnValue(
      new Promise((resolve) => {
        resolveSources = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.click(screen.getByRole("button", { name: "资料与范围" }));
    await user.click(screen.getByRole("button", { name: "保存并重新分析" }));
    await user.click(screen.getByRole("button", { name: "取消" }));
    await selectProject(user, "Project B");
    await screen.findByRole("heading", { name: "Project B" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await act(async () => {
      resolveSources?.(detail("a", "Project A"));
    });
    await waitFor(() =>
      expect(screen.queryByText("资料范围已保存并重新分析。")).toBeNull(),
    );
  });

  it("ignores a delayed response from an abandoned A workspace", async () => {
    let resolveSend: ((value: unknown) => void) | undefined;
    apiMock.sendMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );
    const staleA = detail("a", "Project A");
    staleA.messages = [
      {
        id: "msg_stale",
        role: "assistant",
        content: "stale abandoned A response",
        payload: { kind: "chat" },
        model: null,
        sent_scope: null,
        created_at: "2026-11-06T00:00:00Z",
      },
    ] as never;
    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(screen.getByLabelText("给主会话发送消息"), "old request");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await selectProject(user, "Project B");
    await screen.findByRole("heading", { name: "Project B" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await selectProject(user, "Project A");
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await act(async () => {
      resolveSend?.(staleA);
    });
    await waitFor(() =>
      expect(screen.queryByText("stale abandoned A response")).toBeNull(),
    );
  });

  it("restores the displayed project after overlapping switch failures", async () => {
    apiMock.listProjects.mockResolvedValue({
      items: [
        project("a", "Project A"),
        project("b", "Project B"),
        project("c", "Project C"),
      ],
    });
    const rejects: Record<string, (reason?: unknown) => void> = {};
    apiMock.enterProject.mockImplementation((id: string) => {
      if (id === "b" || id === "c") {
        return new Promise((_, reject) => {
          rejects[id] = reject;
        });
      }
      return Promise.resolve(detail("a", "Project A"));
    });
    const updatedA = detail("a", "Project A");
    updatedA.messages = [
      {
        id: "msg_overlap",
        role: "assistant",
        content: "A still updates",
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
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await selectProject(user, "Project B");
    await selectProject(user, "Project C");
    await act(async () => {
      rejects.b?.(new Error("B failed"));
      rejects.c?.(new Error("C failed"));
    });
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(screen.getByLabelText("给主会话发送消息"), "still A");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByText("A still updates");
  });

  it("keeps a successful import when an earlier switch fails", async () => {
    let rejectB: ((reason?: unknown) => void) | undefined;
    apiMock.enterProject.mockImplementation((id: string) => {
      if (id === "b") {
        return new Promise((_, reject) => {
          rejectB = reject;
        });
      }
      return Promise.resolve(detail("a", "Project A"));
    });
    apiMock.createProject.mockResolvedValue(detail("c", "Imported C"));
    apiMock.listProjects.mockResolvedValue({
      items: [
        project("a", "Project A"),
        project("b", "Project B"),
        project("c", "Imported C"),
      ],
    });
    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await selectProject(user, "Project B");
    await importProject(user);
    await user.type(screen.getByLabelText("项目名称"), "Imported C");
    await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
    await user.click(screen.getByRole("button", { name: "建立项目" }));
    await act(async () => {
      rejectB?.(new Error("B failed"));
    });
    await screen.findByRole("button", { name: /Imported C.*文件/ });
  });

  it("refreshes the workspace when returning from model settings", async () => {
    const initialA = detail("a", "Project A");
    const updatedA = detail("a", "Project A");
    updatedA.messages = [
      {
        id: "msg_late",
        role: "assistant",
        content: "withdrawal completed",
        payload: { kind: "chat" },
        model: null,
        sent_scope: null,
        created_at: "2026-11-06T00:00:00Z",
      },
    ] as never;
    let entered = 0;
    apiMock.enterProject.mockImplementation((_id: string) => {
      entered += 1;
      return Promise.resolve(entered === 1 ? initialA : updatedA);
    });
    let resolveSend: ((value: unknown) => void) | undefined;
    apiMock.sendMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    const main = screen.getByRole("main");
    await user.click(
      await within(main).findByRole("button", { name: /Project A.*文件/ }),
    );
    await screen.findByRole("heading", { name: "Project A" });
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(
      screen.getByLabelText("给主会话发送消息"),
      "我不同意继续。",
    );
    await user.click(screen.getByRole("button", { name: "发送" }));
    if (screen.queryByRole("dialog", { name: "建立项目" }))
      await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "模型配置" }));
    await screen.findByRole("heading", { name: "模型配置" });
    await act(async () => {
      resolveSend?.(updatedA);
    });
    await user.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("withdrawal completed");
  });

  it("keeps model settings when project entry resolves late", async () => {
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
    if (screen.queryByRole("dialog", { name: "建立项目" }))
      await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "模型配置" }));
    await screen.findByRole("heading", { name: "模型配置" });
    await act(async () => {
      resolveA?.(detail("a", "Project A"));
    });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Project A" })).toBeNull(),
    );
    expect(
      screen.getByRole("heading", { name: "模型配置" }),
    ).toBeInTheDocument();
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
    await user.click(screen.getByRole("tab", { name: "主会话" }));

    await act(async () => {
      resolveA?.(detail("a", "Project A"));
    });

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Project B" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("heading", { name: "Project A" }),
    ).not.toBeInTheDocument();
  });
});

it("closes the project navigation after choosing a project section", async () => {
  const user = userEvent.setup();
  render(<App />);
  await selectProject(user, "Project A");
  await screen.findByRole("heading", { name: "Project A" });
  const menu = screen.getByRole("button", { name: "展开导航" });
  expect(menu).toHaveAttribute("aria-expanded", "false");
  await user.click(menu);
  expect(screen.getByRole("button", { name: "收起导航" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await user.click(screen.getByRole("tab", { name: "资料来源" }));
  expect(screen.getByRole("button", { name: "展开导航" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  expect(screen.getByRole("tab", { name: "资料来源" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("filters the project directory and clears an empty search", async () => {
  const user = userEvent.setup();
  render(<App />);
  const search = await screen.findByRole("textbox", { name: "搜索项目" });
  await user.type(search, "Project B");
  const main = screen.getByRole("main");
  expect(
    within(main).queryByRole("button", { name: /Project A.*文件/ }),
  ).not.toBeInTheDocument();
  expect(
    within(main).getByRole("button", { name: /Project B.*文件/ }),
  ).toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "not-found");
  expect(within(main).getByText("没有匹配的项目")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "清除筛选" }));
  expect(
    within(main).getByRole("button", { name: /Project A.*文件/ }),
  ).toBeInTheDocument();
});

it("restores the selected project and tab from a direct URL", async () => {
  window.history.replaceState(null, "", "/#/projects/b?tab=sources");
  render(<App />);
  await screen.findByRole("heading", { name: "Project B" });
  expect(screen.getByRole("tab", { name: "资料来源" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.queryByRole("textbox", { name: "给主会话发送消息" }),
  ).not.toBeInTheDocument();
});

it("restores a tab when browser navigation returns to the project", async () => {
  const user = userEvent.setup();
  render(<App />);
  await selectProject(user, "Project A");
  await screen.findByRole("heading", { name: "Project A" });
  await user.click(screen.getByRole("tab", { name: "资料来源" }));
  await user.click(screen.getByRole("button", { name: "模型配置" }));
  await screen.findByRole("heading", { name: "模型配置" });
  await act(async () => {
    window.history.replaceState(null, "", "/#/projects/a?tab=sources");
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  await screen.findByRole("heading", { name: "Project A" });
  expect(screen.getByRole("tab", { name: "资料来源" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("closes the create drawer with Escape and restores its trigger focus", async () => {
  const user = userEvent.setup();
  render(<App />);
  const trigger = await screen.findByRole("button", { name: "建立项目" });
  await user.click(trigger);
  expect(screen.getByRole("dialog", { name: "建立项目" })).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "项目名称" }),
    "unsaved project",
  );
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(trigger).toHaveFocus();
  expect(apiMock.createProject).not.toHaveBeenCalled();
});

it("asks before deleting a model and leaves cancellation without effects", async () => {
  apiMock.listModels.mockResolvedValue({
    items: [
      {
        id: "model_a",
        name: "Offline model",
        provider: "stub",
        base_url: null,
        model_name: "stub",
        has_api_key: false,
        last_test_ok: null,
        last_test_message: null,
        last_test_at: null,
        created_at: "2026-11-11T00:00:00Z",
      },
    ],
  });
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("button", { name: "模型配置" }));
  await user.click(await screen.findByRole("button", { name: "删除" }));
  const dialog = screen.getByRole("dialog", { name: "删除模型配置？" });
  await user.click(within(dialog).getByRole("button", { name: "取消" }));
  expect(apiMock.deleteModel).not.toHaveBeenCalled();
  await user.click(await screen.findByRole("button", { name: "删除" }));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() =>
    expect(apiMock.deleteModel).toHaveBeenCalledWith("model_a"),
  );
});

it("returns to the project directory when browser Back reaches the original root URL", async () => {
  const user = userEvent.setup();
  render(<App />);
  await selectProject(user, "Project A");
  await screen.findByRole("heading", { name: "Project A" });
  await act(async () => {
    window.history.replaceState(null, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(
    await screen.findByRole("heading", { name: "项目", level: 1 }),
  ).toBeInTheDocument();
  expect(window.location.hash).toBe("");
});

it("opens the main conversation immediately when entering a project, as required by the PRD", async () => {
  const user = userEvent.setup();
  render(<App />);
  await selectProject(user, "Project A");
  await screen.findByRole("heading", { name: "Project A" });
  expect(screen.getByRole("tab", { name: "主会话" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.getByRole("textbox", { name: "给主会话发送消息" }),
  ).toBeVisible();
});

it("switches and remembers both themes without discarding a conversation draft", async () => {
  window.localStorage.setItem("evalith.theme", "light");
  const user = userEvent.setup();
  const first = render(<App />);
  await selectProject(user, "Project A");
  await screen.findByRole("heading", { name: "Project A" });
  await user.click(screen.getByRole("tab", { name: "主会话" }));
  await user.type(
    screen.getByRole("textbox", { name: "给主会话发送消息" }),
    "保留这条草稿",
  );
  await user.click(screen.getByRole("button", { name: "切换到深色模式" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(window.localStorage.getItem("evalith.theme")).toBe("dark");
  expect(screen.getByRole("textbox", { name: "给主会话发送消息" })).toHaveValue(
    "保留这条草稿",
  );
  first.unmount();
  render(<App />);
  await screen.findByRole("heading", { name: "Project A" });
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  await user.click(screen.getByRole("button", { name: "切换到浅色模式" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(window.localStorage.getItem("evalith.theme")).toBe("light");
});

it("keeps form input when the theme is changed from an open project drawer", async () => {
  window.localStorage.setItem("evalith.theme", "light");
  const user = userEvent.setup();
  render(<App />);
  await importProject(user);
  await user.type(
    screen.getByRole("textbox", { name: "项目名称" }),
    "待导入的项目",
  );
  await user.click(screen.getByRole("button", { name: "切换到深色模式" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(screen.getByRole("textbox", { name: "项目名称" })).toHaveValue(
    "待导入的项目",
  );
  expect(screen.getByRole("dialog", { name: "建立项目" })).toBeInTheDocument();
});

it("starts with project establishment and does not expose a project workspace before a card is opened", async () => {
  render(<App />);
  await screen.findByRole("button", { name: /Project A.*文件/ });
  expect(screen.getByRole("heading", { name: "项目", level: 1 })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "项目会话" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "切换项目" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: "给主会话发送消息" }),
  ).not.toBeInTheDocument();
});

it("creates a project card first and enters its conversation only after opening that card", async () => {
  const created = detail("c", "New approval project");
  apiMock.createProject.mockResolvedValue(created);
  apiMock.listProjects
    .mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [created.project] });
  apiMock.enterProject.mockResolvedValue(created);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("heading", { name: "创建第一个项目" });
  await importProject(user);
  await user.type(screen.getByLabelText("项目名称"), created.project.name);
  await user.type(screen.getByLabelText(/本地目录/), "/tmp/c");
  await user.click(screen.getByRole("button", { name: "建立项目" }));
  const card = await screen.findByRole("button", {
    name: /New approval project.*文件/,
  });
  expect(
    screen.queryByRole("textbox", { name: "给主会话发送消息" }),
  ).not.toBeInTheDocument();
  expect(apiMock.enterProject).not.toHaveBeenCalled();
  await user.click(card);
  expect(
    await screen.findByRole("textbox", { name: "给主会话发送消息" }),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: created.project.name }),
  ).toBeVisible();
});

it("keeps the project directory, executor settings and model settings as separate destinations", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: /Project A.*文件/ });
  await user.click(screen.getByRole("button", { name: "执行器配置" }));
  expect(
    await screen.findByRole("heading", { name: "执行器配置", level: 1 }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Project A.*文件/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "添加模型服务" }),
  ).not.toBeInTheDocument();
  expect(window.location.hash).toBe("#/executors");
  await user.click(screen.getByRole("button", { name: "模型配置" }));
  expect(
    await screen.findByRole("heading", { name: "模型配置" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "添加执行器" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "项目目录" }));
  expect(
    await screen.findByRole("button", { name: /Project A.*文件/ }),
  ).toBeVisible();
});
