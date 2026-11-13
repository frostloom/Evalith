import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  updateSources: vi.fn(),
}));

vi.mock("./api", () => ({
  api: apiMock,
  request: vi.fn().mockResolvedValue({items:[]}),
  ApiError: class ApiError extends Error {
    code = "test";
    status = 500;
  },
}));

import type { ProjectDetail } from "./types";
import { SourceEditor } from "./Workspace";

const detail = {
  project: {
    id: "prj_a",
    name: "Project A",
    root_path: "/tmp/a",
    include_paths: ["README.md"],
    exclude_patterns: [],
    supplemental: [
      {
        title: "Policy",
        content: "First paragraph\n\nSecond paragraph",
      },
    ],
    model_config_id: null,
    snapshot_id: "snp_a",
    analysis_error: null,
    created_at: "2026-11-06T00:00:00Z",
    updated_at: "2026-11-06T00:00:00Z",
    file_count: 1,
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
    generation_allowed: false,
    generation_implemented: false,
    unknowns_confirmed: false,
    reason: "not ready",
  },
} as unknown as ProjectDetail;

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.updateSources.mockResolvedValue(detail);
});

describe("source editor", () => {
  it("preserves supplemental titles and multiline content when saved unchanged", async () => {
    const user = userEvent.setup();
    render(
      <SourceEditor
        detail={detail}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onError={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "保存并重新分析" }));
    await waitFor(() => expect(apiMock.updateSources).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateSources.mock.calls[0][1] as {
      supplemental: Array<{ title: string; content: string }>;
    };
    expect(payload.supplemental).toEqual([
      { title: "Policy", content: "First paragraph\n\nSecond paragraph" },
    ]);
  });
});
