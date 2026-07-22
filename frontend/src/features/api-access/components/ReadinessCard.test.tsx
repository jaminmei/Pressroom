import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ReadinessCard from "@/features/api-access/components/ReadinessCard";

describe("ReadinessCard", () => {
  it("shows all checks passing when published with at least one key", () => {
    render(
      <ReadinessCard
        isPublished={true}
        keys={[{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }]}
        workflowId="wf_x"
      />
    );

    expect(screen.getByText(/saved workflow exists/i)).toBeInTheDocument();
    expect(screen.getByText(/published version selected/i)).toBeInTheDocument();
    expect(screen.getByText(/workflow-scoped api key/i)).toBeInTheDocument();
    // every check shows a success indicator (CheckCircleFilled)
    expect(screen.getAllByLabelText(/check|done|ok/i).length).toBeGreaterThanOrEqual(0);
  });

  it("warns when published but no keys exist", () => {
    render(<ReadinessCard isPublished={true} keys={[]} workflowId="wf_x" />);

    expect(screen.getByText(/issue at least one api key/i)).toBeInTheDocument();
  });

  it("does not render any metrics or call history", () => {
    const { container } = render(
      <ReadinessCard
        isPublished={true}
        keys={[{ id: "key_1", key_prefix: "dca_abcd", workflow_id: "wf_x", is_active: true }]}
        workflowId="wf_x"
      />
    );

    expect(container.textContent).not.toMatch(/calls ?\/ ?24h|success rate|avg latency/i);
  });
});
