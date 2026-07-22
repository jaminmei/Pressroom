import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DynamicWarningBadge from "@/features/workflow-editor/components/DynamicWarningBadge";
import type { DynamicWarning } from "@/features/workflow-editor/store";

function makeWarning(overrides: Partial<DynamicWarning> = {}): DynamicWarning {
  return {
    code: "MODEL_NO_VISION",
    severity: "warning",
    node_id: "engine_1",
    message: "Model does not support vision",
    model: null,
    edge_ids: [],
    ...overrides,
  };
}

describe("DynamicWarningBadge", () => {
  it("renders nothing when no warnings match nodeId", () => {
    const warnings = [makeWarning({ node_id: "engine_2" })];
    const { container } = render(
      <DynamicWarningBadge warnings={warnings} nodeId="engine_1" />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders MODEL_NO_VISION warning badge", () => {
    const warnings = [
      makeWarning({
        code: "MODEL_NO_VISION",
        node_id: "engine_1",
        severity: "warning",
      }),
    ];
    render(<DynamicWarningBadge warnings={warnings} nodeId="engine_1" />);

    expect(screen.getByTestId("dynamic-warning-badge")).toBeInTheDocument();
    expect(
      screen.getByText("Model does not support vision")
    ).toBeInTheDocument();
  });

  it("renders MODEL_NOT_SELECTED info badge", () => {
    const warnings = [
      makeWarning({
        code: "MODEL_NOT_SELECTED",
        node_id: "engine_1",
        severity: "info",
      }),
    ];
    render(<DynamicWarningBadge warnings={warnings} nodeId="engine_1" />);

    expect(screen.getByTestId("dynamic-warning-badge")).toBeInTheDocument();
    expect(
      screen.getByText("Select a vision model to process image input")
    ).toBeInTheDocument();
  });

  it("renders multiple badges for same node", () => {
    const warnings = [
      makeWarning({
        code: "MODEL_NO_VISION",
        node_id: "engine_1",
        severity: "warning",
      }),
      makeWarning({
        code: "MODEL_NOT_SELECTED",
        node_id: "engine_1",
        severity: "info",
      }),
    ];
    render(<DynamicWarningBadge warnings={warnings} nodeId="engine_1" />);

    expect(
      screen.getByText("Model does not support vision")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Select a vision model to process image input")
    ).toBeInTheDocument();
  });
});
