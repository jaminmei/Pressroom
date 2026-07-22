import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FileUploadField from "@/features/workflow-editor/components/FileUploadField";
import { validateUploadFile } from "@/features/workflow-editor/components/fileUploadValidation";

describe("validateUploadFile", () => {
  it("rejects invalid mime type", () => {
    const file = new File(["abc"], "a.txt", { type: "text/plain" });
    const error = validateUploadFile(file, ["application/pdf"], 10);

    expect(error).toContain("檔案類型");
  });

  it("rejects oversized file", () => {
    const oneMb = 1024 * 1024;
    const file = new File([new Uint8Array(oneMb * 2)], "a.pdf", {
      type: "application/pdf"
    });

    const error = validateUploadFile(file, ["application/pdf"], 1);

    expect(error).toContain("檔案大小");
  });

  it("accepts valid file", () => {
    const file = new File(["pdf"], "a.pdf", { type: "application/pdf" });
    const error = validateUploadFile(file, ["application/pdf"], 10);

    expect(error).toBeNull();
  });
});

describe("FileUploadField", () => {
  it("stores selected file in memory and shows file info", async () => {
    const onFileChange = vi.fn();

    const { container } = render(
      <FileUploadField
        accept={["application/pdf"]}
        maxSizeMb={10}
        file={null}
        onFileChange={onFileChange}
      />
    );

    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    const file = new File(["content"], "sample.pdf", { type: "application/pdf" });

    fireEvent.change(input, { target: { files: [file] } });

    expect(onFileChange).toHaveBeenCalledWith(file);
    expect(await screen.findByText("sample.pdf")).toBeInTheDocument();
    expect(screen.getByText("The document is staged and will be submitted with the run")).toBeInTheDocument();
  });
});
