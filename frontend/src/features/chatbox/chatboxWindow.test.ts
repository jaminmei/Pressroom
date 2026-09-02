import { describe, expect, it } from "vitest";

import { resizeChatboxWindow } from "@/features/chatbox/chatboxWindow";

describe("resizeChatboxWindow", () => {
  it("grows toward the top-left and respects the desktop maximum", () => {
    expect(
      resizeChatboxWindow(
        { width: 420, height: 560 },
        { x: 200, y: 200 },
        { x: 100, y: 100 },
        { width: 1370, height: 1082 },
      ),
    ).toEqual({ width: 520, height: 660 });

    expect(
      resizeChatboxWindow(
        { width: 420, height: 560 },
        { x: 200, y: 200 },
        { x: -1000, y: -1000 },
        { width: 1370, height: 1082 },
      ),
    ).toEqual({ width: 760, height: 900 });
  });
});
