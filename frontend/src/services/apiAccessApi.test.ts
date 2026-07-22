import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/services/api";
import {
  issueWorkflowApiKey,
  listWorkflowApiKeys,
  revokeWorkflowApiKey,
} from "@/services/apiAccessApi";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("listWorkflowApiKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls GET /admin/api-keys with workflow_id param and returns the filtered envelope", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        data: [{ id: "key_1", workflow_id: "wf_x" }, { id: "key_2", workflow_id: "wf_other" }],
        meta: { total: 2, page: 1, limit: 10 },
      },
    } as never);

    const result = await listWorkflowApiKeys("wf_x");

    expect(apiClient.get).toHaveBeenCalledWith("/admin/api-keys", {
      params: { workflow_id: "wf_x", include_inactive: false },
    });
    expect(result).toEqual({
      data: [{ id: "key_1", workflow_id: "wf_x" }],
      meta: { total: 2, page: 1, limit: 10 },
    });
  });

  it("returns an empty data array when the envelope has no data field", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { meta: { total: 0, page: 1, limit: 10 } } } as never);

    const result = await listWorkflowApiKeys("wf_x");

    expect(result).toEqual({ data: [], meta: { total: 0, page: 1, limit: 10 } });
  });
});

describe("issueWorkflowApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls POST /admin/api-keys with workflow_id and description, returns full key record", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        id: "key_2",
        key: "dca_full_secret",
        key_prefix: "dca_abcd",
        workflow_id: "wf_x",
        description: "Prod",
      },
    } as never);

    const result = await issueWorkflowApiKey({
      workflow_id: "wf_x",
      description: "Prod",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/admin/api-keys", {
      workflow_id: "wf_x",
      description: "Prod",
    });
    expect(result.key).toBe("dca_full_secret");
    expect(result.workflow_id).toBe("wf_x");
  });

  it("forwards a null description when not provided", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { id: "key_3", key: "dca_x", key_prefix: "dca_x", workflow_id: "wf_x" },
    } as never);

    await issueWorkflowApiKey({ workflow_id: "wf_x" });

    expect(apiClient.post).toHaveBeenCalledWith("/admin/api-keys", {
      workflow_id: "wf_x",
      description: null,
    });
  });
});

describe("revokeWorkflowApiKey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls POST /admin/api-keys/{keyId}/revoke and returns the revoked record", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { id: "key_1", is_active: false },
    } as never);

    const result = await revokeWorkflowApiKey("key_1");

    expect(apiClient.post).toHaveBeenCalledWith("/admin/api-keys/key_1/revoke");
    expect(result?.id).toBe("key_1");
  });

  it("returns the revoke response body", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "key_1", is_active: false } } as never);

    const result = await revokeWorkflowApiKey("key_1");

    expect(result?.is_active).toBe(false);
  });
});
