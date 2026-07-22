import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { getCategoryIcon } from "@/components/Icons";

import CommandPalette from "@/components/CommandPalette/CommandPalette";
import type {
  CommandDefinition,
  NodeCommandDefinition,
  RecentWorkflowCommand
} from "@/components/CommandPalette/commands";

const commands: CommandDefinition[] = [
  {
    id: "action-run",
    label: "Run Workflow",
    category: "action",
    keywords: ["run", "execute"],
    action: vi.fn()
  },
  {
    id: "task-history",
    label: "Open History",
    category: "task",
    keywords: ["history"],
    action: vi.fn()
  }
];

const recentWorkflows: RecentWorkflowCommand[] = [
  {
    id: "recent-wk_1",
    label: "Workflow wk_1",
    workflowId: "wk_1",
    lastSavedAt: "2026-03-04T10:00:00Z",
    keywords: ["wk_1"],
    action: vi.fn()
  }
];

const nodeCommands: NodeCommandDefinition[] = [
  {
    id: "node-engine-ocr",
    nodeType: "engine/ocr",
    label: "OCR Engine",
    category: "engine",
    description: "文本 OCR conversion",
    keywords: ["ocr", "文本"],
    icon: createElement(getCategoryIcon("engine"), { size: 16 })
  }
];

describe("CommandPalette", () => {
  it("renders grouped commands, recent workflows and focuses input", () => {
    render(
      <CommandPalette
        commands={commands}
        nodeCommands={nodeCommands}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        open
        recentWorkflows={recentWorkflows}
      />
    );

    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(screen.getByTestId("command-palette-recent-workflows")).toBeInTheDocument();
    expect(screen.getByTestId("command-palette-input")).toHaveFocus();
  });

  it("shows @node page and selects node with enter", () => {
    vi.useFakeTimers();
    const onSelectNode = vi.fn();

    render(
      <CommandPalette
        commands={commands}
        nodeCommands={nodeCommands}
        onClose={vi.fn()}
        onSelectNode={onSelectNode}
        open
        recentWorkflows={recentWorkflows}
      />
    );

    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "@node ocr" } });
    act(() => {
      vi.advanceTimersByTime(220);
    });

    expect(screen.getByTestId("command-palette-node-page")).toBeInTheDocument();
    expect(screen.getByTestId("command-item-node-engine_ocr")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByTestId("command-palette-input"), { key: "Enter" });

    expect(onSelectNode).toHaveBeenCalledWith("engine/ocr");
    vi.useRealTimers();
  });

  it("executes selected command with Enter", () => {
    const action = vi.fn();
    render(
      <CommandPalette
        commands={[{ ...commands[0], action }]}
        nodeCommands={nodeCommands}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        open
        recentWorkflows={[]}
      />
    );

    fireEvent.keyDown(screen.getByTestId("command-palette-input"), { key: "Enter" });

    expect(action).toHaveBeenCalledTimes(1);
  });
});
