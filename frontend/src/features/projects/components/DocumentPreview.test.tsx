import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DocumentPreview from "@/features/projects/components/DocumentPreview";
import { setActiveWorkspaceId } from "@/services/api";

describe("DocumentPreview", () => {
  it("renders a safe fallback for unsupported document types", () => {
    setActiveWorkspaceId("workspace-1");
    render(<DocumentPreview documentId="doc-1" filename="notes.txt" mimeType="text/plain" testSetId="set-1" />);

    expect(screen.getByTestId("preview-fallback")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute("href");
  });
});
