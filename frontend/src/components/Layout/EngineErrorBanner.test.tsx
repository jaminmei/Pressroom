import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import EngineErrorBanner from "@/components/Layout/EngineErrorBanner";
import { initialUIState, useUIStore } from "@/stores/uiStore";

describe("EngineErrorBanner", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
  });

  it("renders null when all engines are healthy", () => {
    useUIStore.setState({ engineStatuses: { ocr: "healthy", vlm: "healthy" } });

    const { container } = render(<EngineErrorBanner />);

    expect(container.innerHTML).toBe("");
  });

  it("renders error Alert with engine names when engines fail", () => {
    useUIStore.setState({ engineStatuses: { ocr: "unavailable", vlm: "healthy" } });

    render(<EngineErrorBanner />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("ocr");
  });

  it("auto-hides when all engines recover", () => {
    useUIStore.setState({ engineStatuses: { ocr: "unavailable", vlm: "healthy" } });

    const { container, rerender } = render(<EngineErrorBanner />);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    act(() => {
      useUIStore.setState({ engineStatuses: { ocr: "healthy", vlm: "healthy" } });
    });
    rerender(<EngineErrorBanner />);

    expect(container.innerHTML).toBe("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
