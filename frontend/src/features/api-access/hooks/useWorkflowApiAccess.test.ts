import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkflowApiAccess } from "@/features/api-access/hooks/useWorkflowApiAccess";
import {
  issueWorkflowApiKey,
  listWorkflowApiKeys,
  revokeWorkflowApiKey,
} from "@/services/apiAccessApi";
import { getWorkflowDetail } from "@/services/workflowApi";

vi.mock("@/services/workflowApi", () => ({
  getWorkflowDetail: vi.fn(),
}));

vi.mock("@/services/apiAccessApi", () => ({
  listWorkflowApiKeys: vi.fn(),
  issueWorkflowApiKey: vi.fn(),
  revokeWorkflowApiKey: vi.fn(),
}));

function makeEnvelope(data: unknown[], overrides?: Partial<{ total: number; page: number; limit: number }>) {
  return {
    data,
    meta: { total: overrides?.total ?? data.length, page: overrides?.page ?? 1, limit: overrides?.limit ?? 10 },
  };
}

const sampleWorkflow = {
  id: "wf_x",
  name: "Invoice Extraction",
  definition: { nodes: [], edges: [] },
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-29T00:00:00Z",
  published_version: 3,
  latest_version: 4,
};

describe("useWorkflowApiAccess", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads workflow detail and keys, derives isPublished=true when published_version set", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(
      makeEnvelope([{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }]) as never,
    );

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getWorkflowDetail).toHaveBeenCalledWith("wf_x");
    expect(listWorkflowApiKeys).toHaveBeenCalledWith("wf_x", 1, 10);
    expect(result.current.workflow?.id).toBe("wf_x");
    expect(result.current.keys).toHaveLength(1);
    expect(result.current.isPublished).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.page).toBe(1);
    expect(result.current.total).toBe(1);
    expect(result.current.limit).toBe(10);
  });

  it("derives isPublished=false when published_version is null", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue({ ...sampleWorkflow, published_version: null } as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(makeEnvelope([]) as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isPublished).toBe(false);
  });

  it("sets error message when getWorkflowDetail rejects", async () => {
    vi.mocked(getWorkflowDetail).mockRejectedValue(new Error("boom"));
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(makeEnvelope([]) as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.workflow).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("issueKey returns the full key response and refreshes the key list", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(makeEnvelope([]) as never);
    vi.mocked(issueWorkflowApiKey).mockResolvedValue({
      id: "key_new",
      key: "dca_full_secret",
      key_prefix: "dca_full",
      workflow_id: "wf_x",
    } as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let response: { key: string } | undefined;
    await act(async () => {
      response = await result.current.actions.issueKey({ workflow_id: "wf_x", description: "Prod" });
    });

    expect(issueWorkflowApiKey).toHaveBeenCalledWith({ workflow_id: "wf_x", description: "Prod" });
    expect(response?.key).toBe("dca_full_secret");
    expect(listWorkflowApiKeys).toHaveBeenCalledTimes(2);
    // both calls use default pagination
    expect(listWorkflowApiKeys).toHaveBeenNthCalledWith(1, "wf_x", 1, 10);
    expect(listWorkflowApiKeys).toHaveBeenNthCalledWith(2, "wf_x", 1, 10);
  });

  it("issueKey returns the full key even when refresh fails (never hide one-time secret)", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValueOnce(makeEnvelope([]) as never);
    vi.mocked(issueWorkflowApiKey).mockResolvedValue({
      id: "key_new", key: "dca_full_secret", key_prefix: "dca_full", workflow_id: "wf_x",
    } as never);
    vi.mocked(listWorkflowApiKeys).mockRejectedValueOnce(new Error("refresh failed") as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let response: { key: string } | undefined;
    await act(async () => {
      response = await result.current.actions.issueKey({ workflow_id: "wf_x", description: "Prod" });
    });

    expect(response?.key).toBe("dca_full_secret");
  });

  it("revokeKey calls the service and refreshes", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(
      makeEnvelope([{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }]) as never,
    );
    vi.mocked(revokeWorkflowApiKey).mockResolvedValue({ id: "key_1", is_active: false } as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.actions.revokeKey("key_1");
    });

    expect(revokeWorkflowApiKey).toHaveBeenCalledWith("key_1");
    expect(listWorkflowApiKeys).toHaveBeenCalledTimes(2);
    // refresh after revoke uses current page/limit
    expect(listWorkflowApiKeys).toHaveBeenNthCalledWith(2, "wf_x", 1, 10);
  });

  it("revokeKey propagates refresh errors so the UI can warn about stale list", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValueOnce(
      makeEnvelope([{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }]) as never,
    );
    vi.mocked(revokeWorkflowApiKey).mockResolvedValue({ id: "key_1", is_active: false } as never);
    vi.mocked(listWorkflowApiKeys).mockRejectedValueOnce(new Error("refresh failed") as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(
      act(async () => {
        await result.current.actions.revokeKey("key_1");
      })
    ).rejects.toThrow("refresh failed");
  });

  it("manual refresh action swallows errors (non-fatal)", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValueOnce(makeEnvelope([]) as never);
    vi.mocked(listWorkflowApiKeys).mockRejectedValueOnce(new Error("transient") as never);

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.actions.refresh();
    });

    expect(result.current.error).toBeNull();
  });

  it("exposes pagination state with defaults", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(
      makeEnvelope([{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }], { total: 5 }) as never,
    );

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.page).toBe(1);
    expect(result.current.total).toBe(5);
    expect(result.current.limit).toBe(10);
  });

  it("clamps page to last valid page after revoke makes current page empty", async () => {
    vi.mocked(getWorkflowDetail).mockResolvedValue(sampleWorkflow as never);
    vi.mocked(listWorkflowApiKeys).mockResolvedValue(
      makeEnvelope(
        Array.from({ length: 10 }, (_, i) => ({ id: `key_${i}`, key_prefix: `dca_${i}`, workflow_id: "wf_x", is_active: true })),
        { total: 11 },
      ) as never,
    );

    const { result } = renderHook(() => useWorkflowApiAccess("wf_x"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Navigate to page 2
    await act(async () => {
      result.current.setPage(2);
    });
    await waitFor(() => expect(result.current.page).toBe(2));

    // Revoke: total drops to 10, page 2 becomes empty → clamp to 1
    vi.mocked(revokeWorkflowApiKey).mockResolvedValue({ id: "key_x", is_active: false } as never);

    // Reset and set up 3 mocks: revoke(page=2), clamp(page=1), then useEffect re-fetch(page=1)
    vi.mocked(listWorkflowApiKeys).mockReset();
    vi.mocked(listWorkflowApiKeys)
      .mockResolvedValueOnce(makeEnvelope([], { total: 10, page: 2 }) as never)
      .mockResolvedValueOnce(
        makeEnvelope(
          Array.from({ length: 10 }, (_, i) => ({ id: `key_${i}`, key_prefix: `dca_${i}`, workflow_id: "wf_x", is_active: true })),
          { total: 10, page: 1 },
        ) as never,
      )
      .mockResolvedValueOnce(
        makeEnvelope(
          Array.from({ length: 10 }, (_, i) => ({ id: `key_${i}`, key_prefix: `dca_${i}`, workflow_id: "wf_x", is_active: true })),
          { total: 10, page: 1 },
        ) as never,
      );

    await act(async () => {
      await result.current.actions.revokeKey("key_last");
    });

    expect(result.current.page).toBe(1);
    expect(result.current.total).toBe(10);
    expect(result.current.keys).toHaveLength(10);
  });
});
