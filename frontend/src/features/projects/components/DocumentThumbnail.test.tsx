import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DocumentThumbnail from "@/features/projects/components/DocumentThumbnail";
import { getDocumentThumbnailUrl } from "@/services/testSetApi";

vi.mock("@/services/testSetApi", () => ({
  getDocumentThumbnailUrl: vi.fn(
    (_testSetId: string, _documentId: string, size: number) => `/thumbnail/${size}`,
  ),
}));

function stubHoverCapability(matches: boolean): void {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

describe("DocumentThumbnail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubHoverCapability(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("lazy-loads only the list thumbnail on touch and opens the existing preview", () => {
    const onPreview = vi.fn();
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick}>
        <DocumentThumbnail
          documentId="doc-1"
          filename="page.jpg"
          mimeType="image/jpeg"
          onPreview={onPreview}
          testSetId="set-1"
        />
      </div>,
    );

    const image = document.querySelector(".document-thumbnail-image");
    expect(image).not.toBeNull();
    expect(image).toHaveAttribute("src", "/thumbnail/96");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(getDocumentThumbnailUrl).toHaveBeenCalledTimes(1);

    fireEvent.mouseEnter(screen.getByRole("button", { name: "Preview page.jpg" }));
    expect(screen.queryByTestId("document-thumbnail-popover")).not.toBeInTheDocument();
    expect(getDocumentThumbnailUrl).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Preview page.jpg" }));
    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("requests the large preview only after the desktop hover delay and closes on Escape", async () => {
    stubHoverCapability(true);
    render(
      <DocumentThumbnail
        documentId="doc-1"
        filename="page.jpg"
        mimeType="image/jpeg"
        onPreview={vi.fn()}
        testSetId="set-1"
      />,
    );

    const button = screen.getByRole("button", { name: "Preview page.jpg" });
    fireEvent.mouseEnter(button);
    expect(screen.queryByTestId("document-thumbnail-popover")).not.toBeInTheDocument();
    expect(getDocumentThumbnailUrl).toHaveBeenCalledTimes(1);

    expect(await screen.findByTestId("document-thumbnail-popover")).toBeInTheDocument();
    expect(screen.getByAltText("page.jpg preview")).toHaveAttribute("src", "/thumbnail/640");
    expect(getDocumentThumbnailUrl).toHaveBeenLastCalledWith("set-1", "doc-1", 640);

    fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByTestId("document-thumbnail-popover")).not.toBeInTheDocument();
  });

  it("keeps a fixed PDF fallback when thumbnail loading fails", () => {
    render(
      <DocumentThumbnail
        documentId="doc-pdf"
        filename="report.pdf"
        mimeType="application/pdf"
        onPreview={vi.fn()}
        testSetId="set-1"
      />,
    );

    const image = document.querySelector(".document-thumbnail-image");
    expect(image).not.toBeNull();
    fireEvent.error(image as Element);

    const button = screen.getByRole("button", { name: "Preview report.pdf" });
    expect(button).toHaveAttribute("title", "Preview unavailable");
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(button.querySelector(".document-thumbnail-frame--error")).toBeInTheDocument();
  });

  it("renders a non-interactive 96px thumbnail without requesting the hover variant", () => {
    stubHoverCapability(true);
    render(
      <DocumentThumbnail
        documentId="doc-static"
        filename="static.jpg"
        mimeType="image/jpeg"
        testSetId="set-1"
      />,
    );

    const thumbnail = screen.getByTestId("document-thumbnail-doc-static");
    expect(thumbnail.tagName).toBe("SPAN");
    expect(thumbnail.querySelector("img")).toHaveAttribute("src", "/thumbnail/96");

    fireEvent.mouseEnter(thumbnail);
    expect(getDocumentThumbnailUrl).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("document-thumbnail-popover")).not.toBeInTheDocument();
  });
});
