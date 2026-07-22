import { describe, expect, it, vi } from "vitest";

import { getNodeRegistry } from "@/services/nodeRegistryApi";
import { apiClient } from "@/services/api";

vi.mock("@/services/api", () => ({
  apiClient: {
    get: vi.fn()
  }
}));

const mockedGet = vi.mocked(apiClient.get);

describe("getNodeRegistry", () => {
  it("fetches /nodes/registry and returns response payload", async () => {
    const responseData = {
      version: "1.0.0",
      categories: [{ category_id: "input", display_name: "輸入源" }],
      nodes: [],
      connection_rules: []
    };

    mockedGet.mockResolvedValue({ data: responseData });

    await expect(getNodeRegistry()).resolves.toEqual(responseData);
    expect(mockedGet).toHaveBeenCalledWith("/nodes/registry");
  });
});
