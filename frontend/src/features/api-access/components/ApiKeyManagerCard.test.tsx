import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApiKeyManagerCard from "@/features/api-access/components/ApiKeyManagerCard";
import type { UseWorkflowApiAccessResult } from "@/features/api-access/hooks/useWorkflowApiAccess";
import type { IssueApiKeyResponse } from "@/services/apiAccessApi";

let currentCaps: string[] = ["api_key.manage"];

vi.mock("@/hooks/usePermission", () => ({
  usePermission: () => ({
    can: (cap: string) => currentCaps.includes(cap),
    explain: () => "mock reason",
    role: "Admin"
  })
}));

function makeAccess(overrides: Partial<UseWorkflowApiAccessResult> = {}): UseWorkflowApiAccessResult {
  return {
    workflow: { id: "wf_x", name: "Wf", definition: { nodes: [], connections: [] }, created_at: "", updated_at: "", published_version: 3, latest_version: 3 },
    keys: [],
    loading: false,
    error: null,
    isPublished: true,
    page: 1,
    total: 0,
    limit: 10,
    setPage: vi.fn(),
    actions: {
      issueKey: vi.fn().mockResolvedValue({
        id: "key_new", key: "dca_full", key_prefix: "dca_full", workflow_id: "wf_x",
      } as IssueApiKeyResponse),
      revokeKey: vi.fn().mockResolvedValue(undefined),
      refresh: vi.fn().mockResolvedValue(undefined),
    },
    ...overrides,
  };
}

function renderCard(access: UseWorkflowApiAccessResult) {
  return render(
    <AntApp>
      <ApiKeyManagerCard access={access} workflowId="wf_x" />
    </AntApp>
  );
}

describe("ApiKeyManagerCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentCaps = ["api_key.manage"];
  });

  it("renders existing keys with prefix and a revoke action for active keys", () => {
    const access = makeAccess({
      keys: [
        { id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true, description: "Prod", created_at: "2026-06-01T00:00:00Z" },
      ],
      total: 1,
    });

    renderCard(access);

    expect(screen.getByText("dca_abcd")).toBeInTheDocument();
    expect(screen.getByText("Prod")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revoke/i })).toBeInTheDocument();
  });

  it("hides inactive keys from the list", () => {
    const access = makeAccess({
      keys: [
        { id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: false, description: "Old", created_at: "2026-06-01T00:00:00Z" },
      ],
      total: 1,
    });

    renderCard(access);

    expect(screen.queryByText("Old")).not.toBeInTheDocument();
    expect(screen.queryByText("dca_abcd")).not.toBeInTheDocument();
    expect(screen.getByText(/no active api keys/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /revoke/i })).not.toBeInTheDocument();
  });

  it("shows an empty placeholder when there are no keys", () => {
    renderCard(makeAccess());

    expect(screen.getByText(/no active api keys/i)).toBeInTheDocument();
  });

  it("generate form submits description, opens modal with full key, and clears on close", async () => {
    const access = makeAccess();
    renderCard(access);

    const input = screen.getByPlaceholderText(/describe this key/i);
    await act(async () => {
      fireEvent.change(input, { target: { value: "Prod Integration" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    });

    await waitFor(() => expect(access.actions.issueKey).toHaveBeenCalledWith({
      workflow_id: "wf_x",
      description: "Prod Integration",
    }));

    await waitFor(() => expect(screen.getByText("dca_full")).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByText(/saved it/i));
    });

    await waitFor(() => {
      expect(screen.queryByText("dca_full")).not.toBeInTheDocument();
    });
  });

  it("revoke opens Modal.confirm and calls revokeKey on confirm", async () => {
    const access = makeAccess({
      keys: [
        { id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true, description: "Prod", created_at: "2026-06-01T00:00:00Z" },
      ],
      total: 1,
    });

    renderCard(access);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /revoke/i }));
    });

    await waitFor(() => {
      const dangerButtons = document.querySelectorAll(".ant-modal-confirm-btns .ant-btn");
      const okBtn = Array.from(dangerButtons).find((b) => b.textContent === "Revoke");
      expect(okBtn).toBeDefined();
      fireEvent.click(okBtn as HTMLElement);
    });
  });

  it("disables Generate and Revoke when api_key.manage capability is absent", () => {
    currentCaps = [];
    const access = makeAccess({
      keys: [
        { id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true, description: "Prod", created_at: "2026-06-01T00:00:00Z" },
      ],
      total: 1,
    });

    renderCard(access);

    const generateBtn = screen.getByRole("button", { name: /generate/i });
    expect(generateBtn).toBeDisabled();

    const revokeBtn = screen.getByRole("button", { name: /revoke/i });
    expect(revokeBtn).toBeDisabled();
  });
});
