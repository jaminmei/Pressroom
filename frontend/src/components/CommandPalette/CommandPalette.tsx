import { useEffect, useRef } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import CommandItem from "@/components/CommandPalette/CommandItem";
import type {
  CommandCategory,
  CommandDefinition,
  NodeCommandDefinition,
  RecentWorkflowCommand
} from "@/components/CommandPalette/commands";
import { useCommandPalette } from "@/components/CommandPalette/useCommandPalette";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface CommandPaletteProps {
  open: boolean;
  commands: CommandDefinition[];
  recentWorkflows: RecentWorkflowCommand[];
  nodeCommands: NodeCommandDefinition[];
  onClose: () => void;
  onSelectNode: (nodeType: string) => void;
}

const categoryOrder: CommandCategory[] = ["navigation", "action", "template", "task", "project"];

function formatRecentWorkflowDescription(
  item: RecentWorkflowCommand,
  language: "en" | "zh-TW"
): string {
  if (!item.lastSavedAt) {
    return item.workflowId;
  }

  const timestamp = new Date(item.lastSavedAt);
  if (Number.isNaN(timestamp.getTime())) {
    return `${item.workflowId} · ${item.lastSavedAt}`;
  }

  return `${item.workflowId} · ${formatDateTime(timestamp, language)}`;
}

function getCategoryTitle(category: CommandCategory, t: TFunction): string {
  const keys: Record<CommandCategory, string> = {
    navigation: "layout:commandPalette.navigation",
    action: "layout:commandPalette.actions",
    template: "layout:commandPalette.templates",
    task: "layout:commandPalette.tasks",
    project: "layout:commandPalette.database"
  };
  return t(keys[category]);
}

function nodeItemTestId(nodeType: string): string {
  return `command-item-node-${nodeType.replace(/[\\/]/g, "_")}`;
}

export default function CommandPalette({
  open,
  commands,
  recentWorkflows,
  nodeCommands,
  onClose,
  onSelectNode
}: CommandPaletteProps) {
  const { t } = useTranslation("layout");
  const { language } = useLanguage();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const {
    mode,
    query,
    setQuery,
    groupedCommands,
    orderedCommands,
    filteredRecentWorkflows,
    filteredNodeCommands,
    selectedIndex,
    onKeyDown,
    executeCommand,
    executeRecentWorkflow,
    executeNodeCommand
  } = useCommandPalette({
    commands,
    recentWorkflows,
    nodeCommands,
    onClose,
    onSelectNode
  });

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const rootResultCount = orderedCommands.length + filteredRecentWorkflows.length;
  let globalIndex = 0;

  return (
    <div className="command-palette-overlay" onClick={onClose} role="presentation">
      <section
        className="command-palette"
        data-testid="command-palette"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          className="command-palette-input"
          data-testid="command-palette-input"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => onKeyDown(event.nativeEvent)}
          placeholder={t("commandPalette.placeholder")}
          ref={inputRef}
          value={query}
        />

        {mode === "node" ? (
          <div className="command-palette-page-hint" data-testid="command-palette-node-page">
            @node · {t("commandPalette.nodeRegistry")}
          </div>
        ) : null}

        {mode === "node" ? (
          filteredNodeCommands.length === 0 ? (
            <p className="command-palette-empty">{t("commandPalette.noNodes")}</p>
          ) : (
            <div className="command-palette-group">
              <h4>{t("commandPalette.nodeRegistry")}</h4>
              <div className="command-palette-items">
                {filteredNodeCommands.map((node, index) => (
                  <CommandItem
                    badge={node.category}
                    description={node.description ?? node.nodeType}
                    icon={node.icon}
                    index={index}
                    key={node.id}
                    label={node.label}
                    onSelect={() => executeNodeCommand(node)}
                    selected={selectedIndex === index}
                    testId={nodeItemTestId(node.nodeType)}
                  />
                ))}
              </div>
            </div>
          )
        ) : (
          <>
            {rootResultCount === 0 ? <p className="command-palette-empty">{t("commandPalette.noMatches")}</p> : null}

            {categoryOrder.map((category) => {
              const categoryCommands = groupedCommands[category] ?? [];
              if (categoryCommands.length === 0) {
                return null;
              }

              return (
                <div className="command-palette-group" key={category}>
                  <h4>{getCategoryTitle(category, t)}</h4>
                  <div className="command-palette-items">
                    {categoryCommands.map((command) => {
                      const itemIndex = globalIndex;
                      globalIndex += 1;

                      return (
                        <CommandItem
                          index={itemIndex}
                          key={command.id}
                          label={command.label}
                          onSelect={() => executeCommand(command)}
                          selected={selectedIndex === itemIndex}
                          shortcut={command.shortcut}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {filteredRecentWorkflows.length > 0 ? (
              <div className="command-palette-group" data-testid="command-palette-recent-workflows">
                <h4>{t("commandPalette.recentWorkflows")}</h4>
                <div className="command-palette-items">
                  {filteredRecentWorkflows.map((workflow) => {
                    const itemIndex = globalIndex;
                    globalIndex += 1;

                    return (
                      <CommandItem
                        badge={t("commandPalette.recent")}
                        description={formatRecentWorkflowDescription(workflow, language)}
                        index={itemIndex}
                        key={workflow.id}
                        label={workflow.label}
                        onSelect={() => executeRecentWorkflow(workflow)}
                        selected={selectedIndex === itemIndex}
                        testId={`command-item-recent-${workflow.workflowId}`}
                      />
                    );
                  })}
                </div>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
