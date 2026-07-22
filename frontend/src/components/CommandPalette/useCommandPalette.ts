import { useEffect, useMemo, useState } from "react";

import type {
  CommandCategory,
  CommandDefinition,
  NodeCommandDefinition,
  RecentWorkflowCommand
} from "@/components/CommandPalette/commands";
import { usePermission } from "@/hooks/usePermission";

export type CommandPaletteMode = "root" | "node";

interface UseCommandPaletteOptions {
  commands: CommandDefinition[];
  recentWorkflows: RecentWorkflowCommand[];
  nodeCommands: NodeCommandDefinition[];
  onClose: () => void;
  onSelectNode: (nodeType: string) => void;
}

const categoryOrder: CommandCategory[] = ["navigation", "action", "project", "template", "task"];

function fuzzyMatch(text: string, query: string): boolean {
  if (!query) {
    return true;
  }

  let queryIndex = 0;
  const normalizedText = text.toLowerCase();
  const normalizedQuery = query.toLowerCase();

  for (let i = 0; i < normalizedText.length && queryIndex < normalizedQuery.length; i += 1) {
    if (normalizedText[i] === normalizedQuery[queryIndex]) {
      queryIndex += 1;
    }
  }

  return queryIndex === normalizedQuery.length;
}

function tokenize(value: string): string[] {
  return value
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

function compact(value: string): string {
  return value.replace(/\s+/g, "");
}

function matchesSearch(fragments: Array<string | undefined>, rawQuery: string): boolean {
  const queryTokens = tokenize(rawQuery);
  if (queryTokens.length === 0) {
    return true;
  }

  const normalizedCandidate = fragments
    .filter((fragment): fragment is string => typeof fragment === "string" && fragment.length > 0)
    .join(" ")
    .toLowerCase();
  const compactCandidate = compact(normalizedCandidate);

  return queryTokens.every((token) => {
    const compactToken = compact(token);
    return (
      normalizedCandidate.includes(token) ||
      compactCandidate.includes(compactToken) ||
      fuzzyMatch(normalizedCandidate, token)
    );
  });
}

function stripNodePrefix(rawQuery: string): string {
  return rawQuery.trim().replace(/^@node/i, "").trim();
}

export function useCommandPalette({
  commands,
  recentWorkflows,
  nodeCommands,
  onClose,
  onSelectNode
}: UseCommandPaletteOptions) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const { can } = usePermission();

  const mode: CommandPaletteMode = query.trim().toLowerCase().startsWith("@node") ? "node" : "root";

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query);
    }, 200);

    return () => {
      window.clearTimeout(timer);
    };
  }, [query]);

  const rootQuery = mode === "root" ? debouncedQuery.trim() : "";
  const nodeQuery = mode === "node" ? stripNodePrefix(debouncedQuery) : "";

  const filteredCommands = useMemo(() => {
    return commands.filter((command) => {
      if (command.capability && !can(command.capability)) {
        return false;
      }
      return matchesSearch([command.label, ...command.keywords], rootQuery);
    });
  }, [commands, rootQuery, can]);

  const groupedCommands = useMemo<Record<CommandCategory, CommandDefinition[]>>(() => {
    const grouped: Record<CommandCategory, CommandDefinition[]> = {
      navigation: [],
      action: [],
      project: [],
      template: [],
      task: []
    };

    filteredCommands.forEach((command) => {
      grouped[command.category].push(command);
    });

    return grouped;
  }, [filteredCommands]);

  const orderedCommands = useMemo(() => {
    return categoryOrder.flatMap((category) => groupedCommands[category]);
  }, [groupedCommands]);

  const filteredRecentWorkflows = useMemo(() => {
    return recentWorkflows.filter((workflow) =>
      matchesSearch([workflow.label, workflow.workflowId, workflow.lastSavedAt ?? "", ...workflow.keywords], rootQuery)
    );
  }, [recentWorkflows, rootQuery]);

  const filteredNodeCommands = useMemo(() => {
    return nodeCommands.filter((node) =>
      (!node.capability || can(node.capability)) &&
      matchesSearch([node.label, node.description ?? "", node.category, node.nodeType, ...node.keywords], nodeQuery)
    );
  }, [can, nodeCommands, nodeQuery]);

  const activeItemCount =
    mode === "node" ? filteredNodeCommands.length : orderedCommands.length + filteredRecentWorkflows.length;

  useEffect(() => {
    setSelectedIndex(0);
  }, [mode, rootQuery, nodeQuery]);

  useEffect(() => {
    setSelectedIndex((current) => {
      if (activeItemCount === 0) {
        return 0;
      }
      return Math.min(current, activeItemCount - 1);
    });
  }, [activeItemCount]);

  const executeCommand = (command?: CommandDefinition) => {
    if (!command || (command.capability && !can(command.capability))) {
      return;
    }

    command.action();
    onClose();
  };

  const executeRecentWorkflow = (workflow?: RecentWorkflowCommand) => {
    if (!workflow) {
      return;
    }

    workflow.action();
    onClose();
  };

  const executeNodeCommand = (node?: NodeCommandDefinition) => {
    if (!node || (node.capability && !can(node.capability))) {
      return;
    }

    onSelectNode(node.nodeType);
    onClose();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((current) => {
        if (activeItemCount === 0) {
          return 0;
        }
        return (current + 1) % activeItemCount;
      });
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((current) => {
        if (activeItemCount === 0) {
          return 0;
        }
        return current <= 0 ? activeItemCount - 1 : current - 1;
      });
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();

      if (mode === "node") {
        executeNodeCommand(filteredNodeCommands[selectedIndex]);
        return;
      }

      if (selectedIndex < orderedCommands.length) {
        executeCommand(orderedCommands[selectedIndex]);
        return;
      }

      executeRecentWorkflow(filteredRecentWorkflows[selectedIndex - orderedCommands.length]);
    }
  };

  return {
    mode,
    query,
    setQuery,
    groupedCommands,
    orderedCommands,
    filteredRecentWorkflows,
    filteredNodeCommands,
    selectedIndex,
    executeCommand,
    executeRecentWorkflow,
    executeNodeCommand,
    onKeyDown
  };
}
