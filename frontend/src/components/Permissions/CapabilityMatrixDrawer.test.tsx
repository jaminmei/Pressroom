import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CapabilityMatrixDrawer } from "./CapabilityMatrixDrawer";

describe("CapabilityMatrixDrawer", () => {
  it("renders drawer and capability rows when open", () => {
    render(<CapabilityMatrixDrawer open={true} onClose={vi.fn()} />);
    expect(screen.getByText("Capability Matrix")).toBeInTheDocument();
    // One of the capabilities from the ALL_CAPABILITIES array
    expect(screen.getByText("workspace.delete")).toBeInTheDocument();
  });
});
