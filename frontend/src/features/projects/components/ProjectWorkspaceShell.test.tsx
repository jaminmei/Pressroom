import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectWorkspaceShell from "@/features/projects/components/ProjectWorkspaceShell";

describe("ProjectWorkspaceShell", () => {
  it("renders the Run breadcrumb and routes sidebar actions through callbacks", () => {
    const onBackToList = vi.fn();
    const onNavigateSection = vi.fn();
    const onProjectClick = vi.fn();

    render(
      <ProjectWorkspaceShell
        activeSection="runs"
        breadcrumbTail="Run Workflow"
        onBackToList={onBackToList}
        onNavigateSection={onNavigateSection}
        onProjectClick={onProjectClick}
        projectName="Invoices"
      >
        <div data-testid="shell-content">Content</div>
      </ProjectWorkspaceShell>,
    );

    expect(screen.getByTestId("ws-nav-runs")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("breadcrumb-project-name")).toHaveTextContent("Invoices");
    expect(screen.getByTestId("breadcrumb-tail")).toHaveTextContent("Run Workflow");
    expect(screen.getByTestId("shell-content")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("breadcrumb-project-name"));
    fireEvent.click(screen.getByTestId("ws-nav-documents"));
    fireEvent.click(screen.getByTestId("ws-nav-back"));

    expect(onProjectClick).toHaveBeenCalledTimes(1);
    expect(onNavigateSection).toHaveBeenCalledWith("documents");
    expect(onBackToList).toHaveBeenCalledTimes(1);
  });

  it("omits sections that are unavailable to the current user", () => {
    render(
      <ProjectWorkspaceShell
        activeSection="overview"
        availableSections={new Set(["overview", "documents", "settings"])}
        onBackToList={vi.fn()}
        onNavigateSection={vi.fn()}
        projectName="Invoices"
      >
        Content
      </ProjectWorkspaceShell>,
    );

    expect(screen.queryByTestId("ws-nav-runs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ws-nav-ground-truth")).not.toBeInTheDocument();
    expect(screen.getByTestId("ws-nav-documents")).toBeInTheDocument();
  });
});
