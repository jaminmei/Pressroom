import { describe, expect, it } from "vitest";

import { shouldRenderChatbox } from "@/features/chatbox/chatboxAvailability";

describe("chatbox launcher visibility", () => {
  it("requires authentication and a workspace, but not a configured session", () => {
    expect(shouldRenderChatbox("authenticated", "workspace-1")).toBe(true);
    expect(shouldRenderChatbox("anonymous", "workspace-1")).toBe(false);
    expect(shouldRenderChatbox("authenticated", null)).toBe(false);
  });
});
