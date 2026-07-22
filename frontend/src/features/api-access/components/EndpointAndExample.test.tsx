import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InvocationExampleCard from "@/features/api-access/components/InvocationExampleCard";
import PublicEndpointCard from "@/features/api-access/components/PublicEndpointCard";
import RunHistoryCard from "@/features/api-access/components/RunHistoryCard";

const ORIGIN = "http://localhost:5173";

const writeTextMock = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  writeTextMock.mockClear();
  Object.assign(navigator, {
    clipboard: { writeText: writeTextMock },
  });
  Object.defineProperty(window, "location", {
    value: { origin: ORIGIN },
    writable: true,
  });
});

describe("PublicEndpointCard", () => {
  it("renders the public run and upload endpoints for the workflow id", () => {
    render(
      <AntApp>
        <PublicEndpointCard workflowId="wf_invoice_extract" />
      </AntApp>
    );

    expect(screen.getByText(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`)).toBeInTheDocument();
    expect(screen.getByText(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run/upload`)).toBeInTheDocument();
  });

  it("copy buttons write each endpoint to clipboard", async () => {
    render(
      <AntApp>
        <PublicEndpointCard workflowId="wf_invoice_extract" />
      </AntApp>
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy json run endpoint/i }));
      fireEvent.click(screen.getByRole("button", { name: /copy file upload endpoint/i }));
      await Promise.resolve();
    });

    expect(writeTextMock).toHaveBeenCalledWith(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`);
    expect(writeTextMock).toHaveBeenCalledWith(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run/upload`);
  });
});

describe("InvocationExampleCard", () => {
  it("renders a curl example containing the public path and JSON headers", () => {
    const { container } = render(
      <AntApp>
        <InvocationExampleCard workflowId="wf_invoice_extract" />
      </AntApp>
    );

    expect(container.textContent).toContain(`curl -X POST ${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`);
    expect(container.textContent).toContain("Authorization: Bearer");
    expect(container.textContent).toContain("Content-Type: application/json");
  });

  it("copy button writes the curl example to clipboard", async () => {
    render(
      <AntApp>
        <InvocationExampleCard workflowId="wf_invoice_extract" />
      </AntApp>
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy/i }));
      await Promise.resolve();
    });

    expect(writeTextMock).toHaveBeenCalledTimes(1);
    const copied = writeTextMock.mock.calls[0][0] as string;
    expect(copied).toContain(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/run`);
    expect(copied).toContain("Authorization: Bearer");
  });
});

describe("RunHistoryCard", () => {
  it("renders health, status, results, and history public API endpoints", () => {
    const { container } = render(<RunHistoryCard workflowId="wf_invoice_extract" />);

    expect(container.textContent).toContain(`${ORIGIN}/api/v1/health`);
    expect(container.textContent).toContain(`${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}`);
    expect(container.textContent).toContain(`${ORIGIN}/api/v1/workflow-runs/{workflow_run_id}/results`);
    expect(container.textContent).toContain(`${ORIGIN}/api/v1/workflows/wf_invoice_extract/runs?page=1&limit=20`);
  });
});
