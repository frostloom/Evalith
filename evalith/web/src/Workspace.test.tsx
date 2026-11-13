import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getProject: vi.fn(),
  sendMessage: vi.fn(),
  continueProject: vi.fn(),
  updateProjectModel: vi.fn(),
}));

vi.mock("./api", () => ({
  api: apiMock,
  request: vi.fn().mockResolvedValue({ items: [] }),
  ApiError: class ApiError extends Error {
    code = "test";
    status = 500;
  },
}));

import type { ModelConfig, ProjectDetail } from "./types";
import { Workspace } from "./Workspace";
import { ApiError } from "./api";

function makeDetail(readinessOpen: boolean): ProjectDetail {
  return {
    project: {
      id: "prj_a",
      name: "Project A",
      root_path: "/tmp/a",
      include_paths: [],
      exclude_patterns: [],
      supplemental: [],
      model_config_id: null,
      snapshot_id: "snp_a",
      analysis_error: null,
      created_at: "2026-11-06T00:00:00Z",
      updated_at: "2026-11-06T00:00:00Z",
      file_count: 0,
      snapshot_digest: "digest_a",
    },
    session: {
      id: "ses_a",
      project_id: "prj_a",
      kind: "main",
      created_at: "2026-11-06T00:00:00Z",
    },
    messages: [],
    snapshot: null,
    understanding: null,
    readiness: {
      generation_allowed: readinessOpen,
      generation_implemented: false,
      unknowns_confirmed: false,
      reason: readinessOpen ? "已同意继续" : "尚未满足继续条件",
    },
  } as unknown as ProjectDetail;
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("selects a model in context, saves explicitly and preserves the conversation draft", async () => {
  const user = userEvent.setup();
  const onDetail = vi.fn();
  const next = makeDetail(false);
  next.project.model_config_id = "local";
  apiMock.updateProjectModel.mockResolvedValue(next);
  render(
    <Workspace
      detail={makeDetail(false)}
      models={[
        {
          id: "local",
          name: "离线演示模型",
          provider: "stub",
          model_name: "stub",
        } as ModelConfig,
      ]}
      busy={false}
      tab="conversation"
      onDetail={onDetail}
      onHome={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  const draft = screen.getByRole("textbox", { name: "给主会话发送消息" });
  await user.type(draft, "保留项目背景");
  const trigger = screen.getByRole("button", { name: "选择模型" });
  await user.click(trigger);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  const picker = screen.getByRole("dialog", { name: "会话模型" });
  await user.click(within(picker).getByRole("radio", { name: /离线演示模型/ }));
  expect(apiMock.updateProjectModel).not.toHaveBeenCalled();
  await user.click(within(picker).getByRole("button", { name: "保存模型" }));
  await waitFor(() =>
    expect(apiMock.updateProjectModel).toHaveBeenCalledWith("prj_a", "local"),
  );
  await waitFor(() => expect(onDetail).toHaveBeenCalledWith(next));
  expect(draft).toHaveValue("保留项目背景");
  expect(
    screen.queryByRole("dialog", { name: "会话模型" }),
  ).not.toBeInTheDocument();
});

it("closes the model menu with Escape without applying a pending selection", async () => {
  const user = userEvent.setup();
  render(
    <Workspace
      detail={makeDetail(false)}
      models={[
        {
          id: "local",
          name: "离线演示模型",
          provider: "stub",
          model_name: "stub",
        } as ModelConfig,
      ]}
      busy={false}
      tab="conversation"
      onDetail={vi.fn()}
      onHome={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("button", { name: "选择模型" }));
  await user.click(screen.getByRole("radio", { name: /离线演示模型/ }));
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "会话模型" }),
    ).not.toBeInTheDocument(),
  );
  expect(apiMock.updateProjectModel).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "选择模型" })).toHaveFocus();
});

describe("workspace failure reconciliation", () => {
  it("shows a pending reply and prevents another Enter from sending twice", async () => {
    const user = userEvent.setup();
    let finish!: (detail: ProjectDetail) => void;
    apiMock.sendMessage.mockReturnValue(
      new Promise<ProjectDetail>((resolve) => {
        finish = resolve;
      }),
    );
    render(
      <Workspace
        detail={makeDetail(false)}
        models={[]}
        busy={false}
        tab="conversation"
        onDetail={vi.fn()}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const input = screen.getByRole("textbox", { name: "给主会话发送消息" });
    await user.type(input, "补充业务背景");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("status")).toHaveTextContent("正在回复");
    expect(input).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(apiMock.sendMessage).toHaveBeenCalledTimes(1);
    finish(makeDetail(false));
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(input).toHaveValue("");
  });

  it("keeps the reading position for new replies until the reader returns to the latest message", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    const previous = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      const props = {
        models: [],
        busy: false,
        tab: "conversation" as const,
        onDetail: vi.fn(),
        onHome: vi.fn(),
        onError: vi.fn(),
        onNotice: vi.fn(),
      };
      const view = render(<Workspace detail={makeDetail(false)} {...props} />);
      const messages = screen
        .getByRole("tabpanel", { name: "主会话" })
        .querySelector(".messages")!;
      Object.defineProperties(messages, {
        scrollHeight: { value: 2000 },
        clientHeight: { value: 400 },
        scrollTop: { value: 0 },
      });
      fireEvent.scroll(messages);
      scrollIntoView.mockClear();
      const next = makeDetail(false);
      next.messages = [
        {
          id: "new",
          role: "assistant",
          content: "新的回复",
          payload: { kind: "chat" },
          model: null,
          sent_scope: null,
          created_at: "2026-11-11T00:00:00Z",
        },
      ];
      view.rerender(<Workspace detail={next} {...props} />);
      expect(scrollIntoView).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: "回到最新消息" }));
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(
        screen.queryByRole("button", { name: "回到最新消息" }),
      ).not.toBeInTheDocument();
    } finally {
      Element.prototype.scrollIntoView = previous;
    }
  });

  it("refreshes readiness after a failed withdrawal request", async () => {
    const user = userEvent.setup();
    const refreshed = makeDetail(false);
    apiMock.sendMessage.mockRejectedValue(new Error("provider failed"));
    apiMock.getProject.mockResolvedValue(refreshed);
    const onDetail = vi.fn();
    render(
      <Workspace
        detail={makeDetail(true)}
        models={[]}
        busy={false}
        onDetail={onDetail}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("tab", { name: "主会话" }));
    await user.type(
      screen.getByRole("textbox", { name: "给主会话发送消息" }),
      "不要继续",
    );
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(apiMock.getProject).toHaveBeenCalledWith("prj_a"),
    );
    await waitFor(() => expect(onDetail).toHaveBeenCalledWith(refreshed));
  });

  it("does not send Enter while the IME is composing", async () => {
    apiMock.sendMessage.mockResolvedValue(makeDetail(false));
    const onDetail = vi.fn();
    render(
      <Workspace
        detail={makeDetail(true)}
        models={[]}
        busy={false}
        tab="conversation"
        onDetail={onDetail}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const input = screen.getByRole("textbox", { name: "给主会话发送消息" });
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "继续" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    expect(apiMock.sendMessage).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe("继续");

    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalledTimes(1));
  });
});

describe("stale source evidence", () => {
  it("refreshes the workspace when continuation discovers changed files", async () => {
    const user = userEvent.setup();
    const refreshed = makeDetail(false);
    const error = new ApiError("资料已变化", "understanding_stale", 409);
    error.code = "understanding_stale";
    apiMock.continueProject.mockRejectedValue(error);
    apiMock.getProject.mockResolvedValue(refreshed);
    const onDetail = vi.fn();
    render(
      <Workspace
        detail={makeDetail(false)}
        models={[]}
        busy={false}
        onDetail={onDetail}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "表示可以继续" }));
    await waitFor(() => expect(onDetail).toHaveBeenCalledWith(refreshed));
  });

  it("labels previous conclusions as historical and requires reanalysis", () => {
    const detail = makeDetail(false);
    detail.understanding = {
      summary: "Old policy summary",
      agent_or_flow: "Approval flow",
      known: [{ text: "Approval optional", source: "policy.md" }],
      inferred: [],
      unknowns: [],
      sources: [],
      sufficient: false,
      user_continued: false,
      sufficient_reason: "",
      model: "stub",
      error: null,
      updated_at: "2026-11-06T00:00:00Z",
      snapshot_id: "snp_old",
      stale: true,
    };
    render(
      <Workspace
        detail={detail}
        models={[]}
        busy={false}
        onDetail={vi.fn()}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("资料已变化");
    expect(
      screen.getByRole("heading", { name: "历史依据" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "已知" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Approval optional")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /继续/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新分析" })).toBeEnabled();
  });
});

describe("Rhesis detail navigation", () => {
  it("switches real tab panels without losing the conversation draft", async () => {
    const user = userEvent.setup();
    render(
      <Workspace
        detail={makeDetail(false)}
        models={[]}
        busy={false}
        onDetail={vi.fn()}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const overview = screen.getByRole("tab", { name: "项目理解" });
    expect(overview).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: /主会话/ }));
    await user.type(
      screen.getByRole("textbox", { name: "给主会话发送消息" }),
      "未发送的纠正",
    );
    await user.click(screen.getByRole("tab", { name: "资料来源" }));
    expect(
      screen.queryByRole("textbox", { name: "给主会话发送消息" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /主会话/ }));
    expect(
      screen.getByRole("textbox", { name: "给主会话发送消息" }),
    ).toHaveValue("未发送的纠正");
  });
});

it("keeps source fingerprints separate from the conversation", () => {
  render(
    <Workspace
      detail={makeDetail(false)}
      models={[]}
      busy={false}
      tab="conversation"
      onDetail={vi.fn()}
      onHome={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  expect(
    screen.getByRole("textbox", { name: "给主会话发送消息" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("complementary", { name: "当前项目上下文" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "项目理解" })).toBeVisible();
  expect(screen.getByRole("tab", { name: "资料来源" })).toBeVisible();
});

it("renders model replies as readable headings, lists and code without enabling raw HTML", () => {
  const detail = makeDetail(false);
  detail.messages = [
    {
      id: "formatted",
      role: "assistant",
      content:
        "## 评测重点\n\n- **输入校验**\n- 异常恢复\n\n```python\nassert result.ok\n```\n\n<script>window.untrusted = true</script>\n\n[不可信链接](javascript:alert(1))",
      payload: { kind: "chat" },
      model: "stub",
      sent_scope: null,
      created_at: "2026-11-11T00:00:00Z",
    },
  ];
  render(
    <Workspace
      detail={detail}
      models={[]}
      busy={false}
      tab="conversation"
      onDetail={vi.fn()}
      onHome={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "评测重点", level: 2 }),
  ).toBeVisible();
  expect(screen.getByText("输入校验").tagName).toBe("STRONG");
  expect(screen.getByText("assert result.ok").tagName).toBe("CODE");
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText("不可信链接")).not.toHaveAttribute(
    "href",
    "javascript:alert(1)",
  );
});

it("keeps recovered analysis errors in history instead of showing a current failure", () => {
  const detail = makeDetail(true);
  const understanding = {
    summary: "Current analysis succeeded",
    agent_or_flow: "Agent",
    known: [],
    inferred: [],
    unknowns: [],
    sources: [],
    sufficient: true,
    sufficient_reason: "Scoped source",
    stale: false,
    error: null,
    user_continued: false,
    model: "stub",
    updated_at: "2026-11-13T00:00:00Z",
    snapshot_id: "snp_a",
  };
  detail.understanding = understanding as ProjectDetail["understanding"];
  detail.messages = [
    {
      id: "old",
      role: "system",
      content: "Old parser failure",
      payload: { kind: "error" },
    },
    {
      id: "new",
      role: "assistant",
      content: "Current analysis succeeded",
      payload: { kind: "understanding", understanding },
    },
  ] as ProjectDetail["messages"];
  render(
    <Workspace
      detail={detail}
      models={[]}
      busy={false}
      tab="conversation"
      onDetail={vi.fn()}
      onHome={vi.fn()}
      onError={vi.fn()}
      onNotice={vi.fn()}
    />,
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText("Old parser failure")).not.toBeVisible();
  expect(
    screen
      .getAllByText("Current analysis succeeded")
      .some((node) => node.closest("details") === null),
  ).toBe(true);
});
