import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import WorkflowEditor from "@/features/workflow-editor/components/WorkflowEditor";
import { initialUIState, useUIStore } from "@/stores/uiStore";

describe("WorkflowEditor", () => {
  beforeEach(() => {
    useUIStore.setState(initialUIState);
  });

  it("renders editor layout with canvas and floating toolbar", () => {
    render(
      <MemoryRouter>
        <WorkflowEditor />
      </MemoryRouter>
    );

    expect(screen.getByTestId("workflow-editor-page")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-canvas-panel")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-entry-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-floating-toolbar")).toBeInTheDocument();
  });
});
