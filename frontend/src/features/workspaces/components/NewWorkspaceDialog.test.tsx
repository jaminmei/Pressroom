import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { NewWorkspaceDialog } from "./NewWorkspaceDialog";

describe("NewWorkspaceDialog", () => {
  it("opens and closes without a disconnected Form warning", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    function Harness() {
      const [open, setOpen] = useState(true);
      return open ? (
        <NewWorkspaceDialog
          onCancel={() => setOpen(false)}
          onSubmit={vi.fn()}
          open
        />
      ) : null;
    }

    render(<Harness />);
    expect(screen.getByTestId("new-workspace-dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByTestId("new-workspace-dialog")).not.toBeInTheDocument());

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("trims values before submitting", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<NewWorkspaceDialog onCancel={vi.fn()} onSubmit={onSubmit} open />);

    fireEvent.change(screen.getByTestId("new-workspace-name-input"), {
      target: { value: "  Legal Conversion Lab  " },
    });
    fireEvent.change(screen.getByPlaceholderText("Optional description..."), {
      target: { value: "  Contract review  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      name: "Legal Conversion Lab",
      description: "Contract review",
    }));
  });
});
