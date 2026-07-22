import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApiKeyCreatedModal from "@/features/api-access/components/ApiKeyCreatedModal";
import type { IssueApiKeyResponse } from "@/services/apiAccessApi";

const writeTextMock = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  writeTextMock.mockClear();
  Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
});

const sampleKey: IssueApiKeyResponse = {
  id: "key_new",
  key: "dca_full_secret_value",
  key_prefix: "dca_full",
  workflow_id: "wf_x",
};

describe("ApiKeyCreatedModal", () => {
  it("renders the full key once when open with a key", () => {
    render(
      <AntApp>
        <ApiKeyCreatedModal open={true} apiKey={sampleKey} onClose={vi.fn()} />
      </AntApp>
    );

    expect(screen.getByText("dca_full_secret_value")).toBeInTheDocument();
  });

  it("does not render the full key when apiKey is null", () => {
    render(
      <AntApp>
        <ApiKeyCreatedModal open={true} apiKey={null} onClose={vi.fn()} />
      </AntApp>
    );

    expect(screen.queryByText("dca_full_secret_value")).not.toBeInTheDocument();
  });

  it("copy button writes the full key to clipboard", () => {
    render(
      <AntApp>
        <ApiKeyCreatedModal open={true} apiKey={sampleKey} onClose={vi.fn()} />
      </AntApp>
    );

    fireEvent.click(screen.getByRole("button", { name: /copy/i }));

    expect(writeTextMock).toHaveBeenCalledWith("dca_full_secret_value");
  });

  it("Done button calls onClose", () => {
    const onClose = vi.fn();
    render(
      <AntApp>
        <ApiKeyCreatedModal open={true} apiKey={sampleKey} onClose={onClose} />
      </AntApp>
    );

    fireEvent.click(screen.getByText(/saved it/i));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
