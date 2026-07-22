import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BinaryImagePreview from "@/features/workflow-editor/components/BinaryImagePreview";
import type { NodeOutput } from "@/services/taskApi";
import { setActiveWorkspaceId } from "@/services/api";

vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  return {
    ...actual,
    Image: ({ alt, src, style }: { alt?: string; src: string; style?: React.CSSProperties }) => (
      <img alt={alt ?? ""} data-testid="mock-antd-image" src={src} style={style} />
    )
  };
});

function renderPreview(binary: NodeOutput["binary"], labels?: string[]) {
  return render(
    <BinaryImagePreview
      binary={binary}
      labels={labels}
      nodeId="node-1"
      taskId="task-1"
    />
  );
}

describe("BinaryImagePreview", () => {
  beforeEach(() => {
    setActiveWorkspaceId("workspace-test");
  });
  it("renders a single image from inline data", () => {
    renderPreview([
      {
        data: "ZmFrZS1pbWFnZS1kYXRh",
        mime_type: "image/png",
        ref: "",
        size_bytes: 128
      }
    ]);

    const images = screen.getAllByTestId("mock-antd-image");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", "data:image/png;base64,ZmFrZS1pbWFnZS1kYXRh");
    expect(images[0]).toHaveStyle({ maxWidth: "100%", height: "auto", borderRadius: "8px" });
  });

  it("renders a single image from the node image endpoint when only ref is present", () => {
    renderPreview([
      {
        mime_type: "image/jpeg",
        ref: "outputs/result.jpg",
        size_bytes: 5120
      }
    ]);

    const image = screen.getByTestId("mock-antd-image");
    expect(image).toHaveAttribute("src", "/api/tasks/task-1/nodes/node-1/image?index=0&workspace_id=workspace-test");
  });

  it("renders mixed multi-image entries in a responsive grid with a count label", () => {
    renderPreview([
      {
        data: "aW1hZ2UtMQ==",
        mime_type: "image/png",
        ref: "",
        size_bytes: 100
      },
      {
        mime_type: "image/jpeg",
        ref: "outputs/two.jpg",
        size_bytes: 200
      },
      {
        data: "aW1hZ2UtMw==",
        mime_type: "image/webp",
        ref: "",
        size_bytes: 300
      }
    ]);

    expect(screen.getByText("3 images")).toBeInTheDocument();
    expect(screen.getByTestId("binary-image-preview-grid")).toHaveStyle({
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
      gap: "12px"
    });
    expect(screen.getAllByTestId("mock-antd-image")).toHaveLength(3);
  });

  it("renders image previews alongside non-image file info blocks", () => {
    renderPreview([
      {
        data: "aW1hZ2UtMQ==",
        mime_type: "image/png",
        ref: "",
        size_bytes: 100
      },
      {
        mime_type: "application/pdf",
        ref: "outputs/report.pdf",
        size_bytes: 4096
      }
    ]);

    expect(screen.getAllByTestId("mock-antd-image")).toHaveLength(1);
    const fileBlock = screen.getByTestId("binary-preview-file-1");
    expect(within(fileBlock).getByText("outputs/report.pdf")).toBeInTheDocument();
    expect(within(fileBlock).getByText("application/pdf")).toBeInTheDocument();
    expect(within(fileBlock).getByText("4.0 KB")).toBeInTheDocument();
  });

  it("renders a placeholder when neither inline data nor ref is available", () => {
    renderPreview([
      {
        mime_type: "image/png",
        ref: "",
        size_bytes: 0
      }
    ]);

    expect(screen.getByTestId("binary-preview-placeholder-0")).toBeInTheDocument();
    expect(screen.getByText("image unavailable")).toBeInTheDocument();
  });

  it("renders region labels for layout-detection style image lists", () => {
    renderPreview(
      [
        {
          data: "MQ==",
          mime_type: "image/png",
          ref: "",
          size_bytes: 100
        },
        {
          data: "Mg==",
          mime_type: "image/png",
          ref: "",
          size_bytes: 100
        },
        {
          data: "Mw==",
          mime_type: "image/png",
          ref: "",
          size_bytes: 100
        }
      ],
      ["text", "table", "figure"]
    );

    expect(screen.getByText("Region 1 · text")).toBeInTheDocument();
    expect(screen.getByText("Region 2 · table")).toBeInTheDocument();
    expect(screen.getByText("Region 3 · figure")).toBeInTheDocument();
    expect(screen.getAllByTestId("mock-antd-image")).toHaveLength(3);
  });
});
