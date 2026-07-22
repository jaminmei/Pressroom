import { act, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { getCategoryIcon } from "@/components/Icons";
import type {
  CommandDefinition,
  NodeCommandDefinition,
  RecentWorkflowCommand
} from "@/components/CommandPalette/commands";
import { useCommandPalette } from "@/components/CommandPalette/useCommandPalette";

const commands: CommandDefinition[] = [
  {
    id: "action-run",
    label: "Run Workflow",
    category: "action",
    keywords: ["run", "execute", "執行"],
    action: vi.fn()
  },
  {
    id: "action-save",
    label: "Save Draft",
    category: "action",
    keywords: ["save", "draft", "草稿"],
    action: vi.fn()
  },
  {
    id: "task-history",
    label: "Open History",
    category: "task",
    keywords: ["history", "紀錄"],
    action: vi.fn()
  }
];

const recentWorkflows: RecentWorkflowCommand[] = [
  {
    id: "recent-wk_1",
    label: "Workflow wk_1",
    workflowId: "wk_1",
    lastSavedAt: "2026-03-04T10:00:00Z",
    keywords: ["wk_1", "history"],
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
    keywords: ["ocr", "文本", "text", "recognition"],
    icon: createElement(getCategoryIcon("engine"), { size: 16 })
  },
  {
    id: "node-output-md",
    nodeType: "output/markdown",
    label: "Markdown Output",
    category: "output",
    description: "輸出 markdown",
    keywords: ["markdown", "輸出"],
    icon: createElement(getCategoryIcon("output"), { size: 16 })
  }
];

describe("useCommandPalette", () => {
  it("filters root commands with debounce", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useCommandPalette({
        commands,
        recentWorkflows,
        nodeCommands,
        onClose: vi.fn(),
        onSelectNode: vi.fn()
      })
    );

    act(() => {
      result.current.setQuery("save");
    });

    expect(result.current.orderedCommands).toHaveLength(3);

    act(() => {
      vi.advanceTimersByTime(220);
    });

    expect(result.current.orderedCommands.map((command) => command.id)).toEqual(["action-save"]);

    vi.useRealTimers();
  });

  it("enters @node mode and supports mixed-language search", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useCommandPalette({
        commands,
        recentWorkflows,
        nodeCommands,
        onClose: vi.fn(),
        onSelectNode: vi.fn()
      })
    );

    act(() => {
      result.current.setQuery("@node 文本 ocr");
    });

    expect(result.current.mode).toBe("node");

    act(() => {
      vi.advanceTimersByTime(220);
    });

    expect(result.current.filteredNodeCommands.map((node) => node.nodeType)).toEqual(["engine/ocr"]);

    vi.useRealTimers();
  });

  it("supports keyboard navigation and executes command", () => {
    const onClose = vi.fn();
    const action = vi.fn();
    const { result } = renderHook(() =>
      useCommandPalette({
        commands: [{ ...commands[0], action }, commands[1]],
        recentWorkflows,
        nodeCommands,
        onClose,
        onSelectNode: vi.fn()
      })
    );

    act(() => {
      result.current.onKeyDown({ key: "Enter", preventDefault: vi.fn() } as unknown as KeyboardEvent);
    });

    expect(action).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("executes node selection with Enter in @node mode", () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    const onSelectNode = vi.fn();

    const { result } = renderHook(() =>
      useCommandPalette({
        commands,
        recentWorkflows,
        nodeCommands,
        onClose,
        onSelectNode
      })
    );

    act(() => {
      result.current.setQuery("@node OCR");
      vi.advanceTimersByTime(220);
    });

    act(() => {
      result.current.onKeyDown({ key: "Enter", preventDefault: vi.fn() } as unknown as KeyboardEvent);
    });

    expect(onSelectNode).toHaveBeenCalledWith("engine/ocr");
    expect(onClose).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });
});
