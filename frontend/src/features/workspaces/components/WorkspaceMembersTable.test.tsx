import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceMembersTable } from "./WorkspaceMembersTable";

vi.mock("antd", () => ({
  Button: ({ children, disabled, icon: _icon, ...props }: { children?: ReactNode; disabled?: boolean; icon?: ReactNode }) => (
    <button type="button" disabled={disabled} {...props}>{children}</button>
  ),
  Dropdown: ({ children, menu }: {
    children?: ReactNode;
    menu: { items?: Array<{ key: string; label: ReactNode; disabled?: boolean }>; onClick?: (info: { key: string }) => void };
  }) => (
    <div>
      {children}
      {menu.items?.map((item) => (
        <button
          disabled={item.disabled}
          key={item.key}
          onClick={() => menu.onClick?.({ key: item.key })}
          type="button"
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/Permissions/RoleBadge", () => ({
  RoleBadge: ({ role }: { role: string }) => <span>{role}</span>
}));

describe("WorkspaceMembersTable", () => {
  it("renders identity, role, status, and protects the current user", () => {
    render(
      <WorkspaceMembersTable
        members={[{
          userId: "self",
          email: "self@example.com",
          name: "Ari Wong",
          role: "admin",
          status: "active",
          isCurrentUser: true
        }]}
        canChangeRole
        canRemove
        onChangeRole={vi.fn()}
        onRemoveMember={vi.fn()}
      />
    );

    expect(screen.getByRole("table", { name: "Workspace members" })).toBeInTheDocument();
    expect(screen.getByText("Ari Wong")).toBeInTheDocument();
    expect(screen.getByText("self@example.com")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Active")).toHaveClass("is-active");
    expect(screen.getByRole("button", { name: /actions locked for Ari Wong/i })).toBeDisabled();
  });

  it("offers a More menu and dispatches allowed actions", () => {
    const member = {
      userId: "member-1",
      email: "mina@example.com",
      name: "Mina Li",
      role: "editor" as const,
      status: "pending" as const
    };
    const onChangeRole = vi.fn();
    const onRemoveMember = vi.fn();

    render(
      <WorkspaceMembersTable
        members={[member]}
        canChangeRole
        canRemove
        onChangeRole={onChangeRole}
        onRemoveMember={onRemoveMember}
      />
    );

    expect(screen.getByRole("button", { name: /more actions for Mina Li/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change role" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove member" }));
    expect(onChangeRole).toHaveBeenCalledWith(member);
    expect(onRemoveMember).toHaveBeenCalledWith(member);
  });
});
