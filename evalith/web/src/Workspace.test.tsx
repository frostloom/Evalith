import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  getProject: vi.fn(),
  sendMessage: vi.fn(),
  continueProject: vi.fn(),
}));

vi.mock("./api", () => ({
  api: apiMock,
  ApiError: class ApiError extends Error {
    code = "test";
    status = 500;
  },
}));

import type { ProjectDetail } from "./types";
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

describe("workspace failure reconciliation", () => {
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
    await user.type(
      screen.getByPlaceholderText(/补充资料、纠正理解/),
      "不要继续",
    );
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(apiMock.getProject).toHaveBeenCalledWith("prj_a"));
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
        onDetail={onDetail}
        onHome={vi.fn()}
        onError={vi.fn()}
        onNotice={vi.fn()}
      />,
    );
    const input = screen.getByPlaceholderText(/补充资料、纠正理解/);
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
    render(<Workspace detail={makeDetail(false)} models={[]} busy={false}
      onDetail={onDetail} onHome={vi.fn()} onError={vi.fn()} onNotice={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "表示可以继续" }));
    await waitFor(() => expect(onDetail).toHaveBeenCalledWith(refreshed));
  });

  it("labels previous conclusions as historical and requires reanalysis", () => {
    const detail = makeDetail(false);
    detail.understanding = {
      summary: "Old policy summary", agent_or_flow: "Approval flow",
      known: [{ text: "Approval optional", source: "policy.md" }],
      inferred: [], unknowns: [], sources: [], sufficient: false,
      user_continued: false, sufficient_reason: "", model: "stub",
      error: null, updated_at: "2026-11-06T00:00:00Z",
      snapshot_id: "snp_old", stale: true,
    };
    render(<Workspace detail={detail} models={[]} busy={false}
      onDetail={vi.fn()} onHome={vi.fn()} onError={vi.fn()} onNotice={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("资料已变化");
    expect(screen.getByRole("heading", { name: "历史依据" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "已知" })).not.toBeInTheDocument();
    expect(screen.getByText("Approval optional")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /继续/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新分析" })).toBeEnabled();
  });
});
