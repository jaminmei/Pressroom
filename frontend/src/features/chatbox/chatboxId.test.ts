import { afterEach, describe, expect, it, vi } from "vitest";

import { generateChatboxId } from "@/features/chatbox/chatboxId";

describe("generateChatboxId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to unique correlation ids when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {});

    const first = generateChatboxId("prompt");
    const second = generateChatboxId("prompt");

    expect(first).toMatch(/^prompt-/);
    expect(second).toMatch(/^prompt-/);
    expect(second).not.toBe(first);
  });
});
