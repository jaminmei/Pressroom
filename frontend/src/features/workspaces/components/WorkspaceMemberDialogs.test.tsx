import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceMember } from "@/types/workspace";
import { AddWorkspaceMemberDialog } from "./AddWorkspaceMemberDialog";
import { ChangeWorkspaceRoleDialog } from "./ChangeWorkspaceRoleDialog";
import { RemoveWorkspaceMemberDialog } from "./RemoveWorkspaceMemberDialog";

const member: WorkspaceMember = {
  userId: "member-1",
  email: "mina@example.com",
  name: "Mina Li",
  role: "editor",
  status: "active"
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("workspace member dialogs", () => {
  it("connects invite and role forms without deprecated or disconnected-form warnings", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const { rerender } = render(
      <AddWorkspaceMemberDialog
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
        open={false}
      />
    );
    rerender(
      <AddWorkspaceMemberDialog
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
        open
      />
    );

    expect(await screen.findByRole("button", { name: "Viewer" })).toHaveAttribute("aria-pressed", "true");

    rerender(
      <ChangeWorkspaceRoleDialog
        member={member}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
        open
      />
    );
    expect(await screen.findByRole("button", { name: "Editor" })).toHaveAttribute("aria-pressed", "true");

    await waitFor(() => {
      const output = [...consoleError.mock.calls, ...consoleWarn.mock.calls].flat().join(" ");
      expect(output).not.toMatch(/destroyOnClose|not connected to any Form element/i);
    });
  });

  it("renders the destructive member confirmation without deprecated modal props", async () => {
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    render(
      <RemoveWorkspaceMemberDialog
        member={member}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
        open
      />
    );

    expect(await screen.findByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(consoleWarn.mock.calls.flat().join(" ")).not.toMatch(/destroyOnClose/i);
  });

});
