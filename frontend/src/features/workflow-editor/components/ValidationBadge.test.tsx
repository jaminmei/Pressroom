import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ValidationBadge from "@/features/workflow-editor/components/ValidationBadge";

describe("ValidationBadge", () => {
  it("hides when there are no issues", () => {
    const { container } = render(<ValidationBadge blockingCount={0} warningCount={0} onClick={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows blocking count with blocking severity", () => {
    render(<ValidationBadge blockingCount={2} warningCount={1} onClick={vi.fn()} />);

    const badge = screen.getByTestId("validation-badge");
    expect(badge).toHaveTextContent("2");
    expect(badge).toHaveAttribute("data-severity", "blocking");
  });

  it("shows warning count when only warnings exist", () => {
    render(<ValidationBadge blockingCount={0} warningCount={3} onClick={vi.fn()} />);

    const badge = screen.getByTestId("validation-badge");
    expect(badge).toHaveTextContent("3");
    expect(badge).toHaveAttribute("data-severity", "warning");
  });

  it("invokes callback when clicked", () => {
    const onClick = vi.fn();
    render(<ValidationBadge blockingCount={1} warningCount={0} onClick={onClick} />);

    fireEvent.click(screen.getByTestId("validation-badge"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
