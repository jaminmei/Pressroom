import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RoleSelector } from "./RoleSelector";
import { WORKSPACE_ROLES } from "@/types/workspace";

describe("RoleSelector", () => {
  it("renders role options", () => {
    render(<RoleSelector value="viewer" roles={WORKSPACE_ROLES} onChange={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Viewer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("selects a role chip and respects disabled roles", () => {
    const onChange = vi.fn();
    render(
      <RoleSelector
        disabledRoles={["owner"]}
        onChange={onChange}
        roles={WORKSPACE_ROLES}
        value="viewer"
      />
    );

    expect(screen.getByRole("button", { name: "Owner" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Editor" }));
    expect(onChange).toHaveBeenCalledWith("editor");
  });
});
