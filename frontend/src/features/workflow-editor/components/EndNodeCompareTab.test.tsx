import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EndNodeCompareTab from "@/features/workflow-editor/components/EndNodeCompareTab";
import { getTaskHistory, getTaskResults } from "@/services/taskApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

vi.mock("@/services/taskApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/taskApi")>("@/services/taskApi");
  return { ...actual, getTaskHistory: vi.fn(), getTaskResults: vi.fn() };
});

describe("EndNodeCompareTab", () => {
  beforeEach(() => {
    vi.mocked(getTaskHistory).mockReset();
    vi.mocked(getTaskResults).mockReset();
    useWorkspaceStore.setState({ capabilities: [] });
  });

  it("does not request run history or results without run view permission", () => {
    render(<EndNodeCompareTab />);

    expect(getTaskHistory).not.toHaveBeenCalled();
    expect(getTaskResults).not.toHaveBeenCalled();
    expect(screen.getByText("Select runs to compare results")).toBeInTheDocument();
  });
});
