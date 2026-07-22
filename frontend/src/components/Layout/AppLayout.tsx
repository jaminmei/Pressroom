import { useCallback, useEffect, useMemo, useRef, useState, createElement } from "react";
import { useTranslation } from "react-i18next";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import CommandPalette from "@/components/CommandPalette/CommandPalette";
import type {
  NodeCommandDefinition,
  RecentWorkflowCommand,
  TemplateCommandSource
} from "@/components/CommandPalette/commands";
import { buildDefaultCommands } from "@/components/CommandPalette/commands";
import EngineErrorBanner from "@/components/Layout/EngineErrorBanner";
import Header from "@/components/Layout/Header";
import { useEngineHealth } from "@/hooks/useEngineHealth";
import Sidebar from "@/components/Layout/Sidebar";
import { useDomainShortcuts } from "@/features/projects/hooks/useDomainShortcuts";
import RecentRunsDrawer from "@/features/recent-runs/components/RecentRunsDrawer";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowPersistenceStore } from "@/features/workflow-editor/workflowPersistenceStore";
import { BUILTIN_TEMPLATES } from "@/features/workflow-editor/templates/builtinTemplates";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { useUIStore } from "@/stores/uiStore";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { getCategoryIcon } from "@/components/Icons";

interface RecentWorkflowRecord {
  workflowId: string;
  label: string;
  lastSavedAt: string | null;
}

const RECENT_WORKFLOW_STORAGE_KEY = "dc.command-palette.recent-workflows";
const MAX_RECENT_WORKFLOWS = 5;

function loadRecentWorkflowRecords(storageKey: string): RecentWorkflowRecord[] {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item): item is RecentWorkflowRecord => {
        return (
          typeof item === "object" &&
          item !== null &&
          typeof item.workflowId === "string" &&
          typeof item.label === "string"
        );
      })
      .map((item) => ({
        workflowId: item.workflowId,
        label: item.label,
        lastSavedAt: typeof item.lastSavedAt === "string" ? item.lastSavedAt : null
      }))
      .slice(0, MAX_RECENT_WORKFLOWS);
  } catch {
    return [];
  }
}

function saveRecentWorkflowRecords(storageKey: string, records: RecentWorkflowRecord[]): void {
  window.localStorage.setItem(storageKey, JSON.stringify(records.slice(0, MAX_RECENT_WORKFLOWS)));
}

function upsertRecentWorkflowRecord(
  records: RecentWorkflowRecord[],
  workflowId: string,
  lastSavedAt: string | null
): RecentWorkflowRecord[] {
  const label = `Workflow ${workflowId}`;
  const deduplicated = records.filter((record) => record.workflowId !== workflowId);
  return [{ workflowId, label, lastSavedAt }, ...deduplicated].slice(0, MAX_RECENT_WORKFLOWS);
}


function resolveCanvasCenterPosition(): { x: number; y: number } {
  const shell = document.querySelector<HTMLElement>(".react-flow-shell");
  const width = shell?.clientWidth ?? 720;
  const height = shell?.clientHeight ?? 520;

  return {
    x: Math.max(width / 2 - 100, 40),
    y: Math.max(height / 2 - 40, 40)
  };
}


export default function AppLayout() {
  const { t } = useTranslation(["layout", "workflows"]);
  const location = useLocation();
  const navigate = useNavigate();
  const userId = useAuthStore((state) => state.currentUser?.id ?? "anonymous");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? "none");
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);
  const can = useWorkspaceStore((state) => state.can);
  const workspaceRole = useWorkspaceStore((state) => state.currentWorkspace?.role ?? null);
  const contextKey = `${workspaceId}:${contextGeneration}`;
  const recentWorkflowStorageKey = `${RECENT_WORKFLOW_STORAGE_KEY}:${userId}:${workspaceId}`;
  useDomainShortcuts();
  useEngineHealth();
  const commandPaletteOpen = useUIStore((state) => state.commandPaletteOpen);
  const recentRunsDrawerOpen = useUIStore((state) => state.recentRunsDrawerOpen);
  const setCommandPaletteOpen = useUIStore((state) => state.setCommandPaletteOpen);
  const setRecentRunsDrawerOpen = useUIStore((state) => state.setRecentRunsDrawerOpen);
  const setRightPanelTab = useUIStore((state) => state.setRightPanelTab);
  const setSidebarCollapsed = useUIStore((state) => state.setSidebarCollapsed);
  const toggleSidebar = useUIStore((state) => state.toggleSidebar);
  const nodeRegistryNodes = useWorkflowStore((state) => state.nodeRegistry.nodes);
  const workflowId = useWorkflowPersistenceStore((state) => state.workflowId);
  const lastSavedAt = useWorkflowPersistenceStore((state) => state.lastSavedAt);
  const { publishUnified, saveDraft } = useWorkflowPersistence();
  const isCanvasEditorRoute =
    location.pathname === "/" || /^\/workflows\/[^/]+\/?$/.test(location.pathname);

  const [isDesktop, setIsDesktop] = useState(() => window.innerWidth >= 1024);
  const [recentWorkflowRecords, setRecentWorkflowRecords] = useState<RecentWorkflowRecord[]>(() =>
    loadRecentWorkflowRecords(recentWorkflowStorageKey)
  );
  const isDesktopRef = useRef(true);
  const templateCommandSources = useMemo<TemplateCommandSource[]>(
    () =>
      BUILTIN_TEMPLATES.map((template) => ({
        id: template.id,
        name: template.name,
        description: template.description,
        tags: template.tags
      })),
    []
  );

  const dispatchTemplateApplyRequest = useCallback((templateId: string) => {
    window.dispatchEvent(new CustomEvent("workflow:apply-template-request", { detail: { templateId } }));
  }, []);

  const handleApplyTemplateFromPalette = useCallback(
    (templateId: string) => {
      setRightPanelTab("config");
      setRecentRunsDrawerOpen(false);

      if (location.pathname === "/") {
        dispatchTemplateApplyRequest(templateId);
        return;
      }

      navigate("/");
      window.setTimeout(() => {
        dispatchTemplateApplyRequest(templateId);
      }, 120);
    },
    [dispatchTemplateApplyRequest, location.pathname, navigate, setRecentRunsDrawerOpen, setRightPanelTab]
  );

  useEffect(() => {
    const updateLayout = (isInitial = false) => {
      const width = window.innerWidth;
      const isDesktop = width >= 1024;
      const shouldCollapse = width < 1440;
      setIsDesktop(isDesktop);

      if (isInitial || isDesktopRef.current !== isDesktop) {
        setSidebarCollapsed(shouldCollapse);
      }

      if (!isDesktop) {
        setSidebarCollapsed(true);
      }

      isDesktopRef.current = isDesktop;
    };

    updateLayout(true);

    const onResize = () => updateLayout();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, [setSidebarCollapsed]);

  useEffect(() => {
    setRecentWorkflowRecords(loadRecentWorkflowRecords(recentWorkflowStorageKey));
  }, [recentWorkflowStorageKey]);

  useEffect(() => {
    if (!workflowId) {
      return;
    }

    setRecentWorkflowRecords((current) => {
      const next = upsertRecentWorkflowRecord(current, workflowId, lastSavedAt ?? null);
      saveRecentWorkflowRecords(recentWorkflowStorageKey, next);
      return next;
    });
  }, [workflowId, lastSavedAt, recentWorkflowStorageKey]);

  const handleAddNodeFromPalette = useCallback(
    (nodeType: string) => {
      if (workspaceRole !== null && !can("workflow.edit_draft")) return;
      if (location.pathname !== "/") {
        navigate("/");
      }
      setRightPanelTab("config");

      const tryInsert = (attempt: number) => {
        const shellReady = document.querySelector(".react-flow-shell") !== null;
        if (!shellReady && attempt < 3) {
          window.setTimeout(() => {
            tryInsert(attempt + 1);
          }, 60);
          return;
        }

        const position = resolveCanvasCenterPosition();
        const workflowState = useWorkflowStore.getState();
        const createdNodeId = workflowState.addNode(nodeType, position);
        workflowState.selectNode(createdNodeId);
        useUIStore.getState().selectNode(createdNodeId);
      };

      window.requestAnimationFrame(() => {
        tryInsert(0);
      });
    },
    [can, location.pathname, navigate, setRightPanelTab, workspaceRole]
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === "b") {
        event.preventDefault();
        toggleSidebar();
      }

      if ((event.ctrlKey || event.metaKey) && key === "k") {
        event.preventDefault();
        const current = useUIStore.getState().commandPaletteOpen;
        setCommandPaletteOpen(!current);
      }

      if ((event.ctrlKey || event.metaKey) && key === "r") {
        event.preventDefault();
        if (workspaceRole === null || can("workflow.run")) window.dispatchEvent(new Event("workflow:execute-request"));
      }

      if (event.key === "Escape") {
        setCommandPaletteOpen(false);
        setRecentRunsDrawerOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [can, setCommandPaletteOpen, setRecentRunsDrawerOpen, toggleSidebar, workspaceRole]);

  const commands = useMemo(
    () =>
      buildDefaultCommands({
        t,
        executeWorkflow: () => {
          window.dispatchEvent(new Event("workflow:execute-request"));
        },
        saveDraft: () => {
          void saveDraft();
        },
        publishWorkflow: () => {
          void publishUnified();
        },
        togglePalette: () => {
          const current = useUIStore.getState().commandPaletteOpen;
          setCommandPaletteOpen(!current);
        },
        navigateToEditor: () => {
          navigate("/");
        },
        navigateToTemplateCenter: () => {
          navigate("/templates");
        },
        openRecentRuns: () => {
          setRecentRunsDrawerOpen(true);
        },
        clearCanvas: () => {
          window.dispatchEvent(new Event("workflow:clear-request"));
        },
        templates: templateCommandSources,
        applyTemplate: (templateId) => {
          handleApplyTemplateFromPalette(templateId);
        },
        openHistory: () => {
          setRightPanelTab("history");
          navigate("/");
        },
        navigateToProjects: () => {
          navigate("/database");
        },
        createProject: () => {
          navigate("/database");
          setTimeout(() => {
            window.dispatchEvent(new Event("project:create-request"));
          }, 100);
        }
      }),
    [
      handleApplyTemplateFromPalette,
      navigate,
      publishUnified,
      saveDraft,
      setCommandPaletteOpen,
      setRecentRunsDrawerOpen,
      setRightPanelTab,
      t,
      templateCommandSources
    ]
  );

  const recentWorkflows = useMemo<RecentWorkflowCommand[]>(() => {
    return recentWorkflowRecords.map((record) => ({
      id: `recent-workflow-${record.workflowId}`,
      label: record.label,
      workflowId: record.workflowId,
      lastSavedAt: record.lastSavedAt,
      keywords: [record.workflowId, "workflow", "history", "recent"],
      action: () => {
        setRightPanelTab("history");
        navigate("/");
      }
    }));
  }, [navigate, recentWorkflowRecords, setRightPanelTab]);

  const nodeCommands = useMemo<NodeCommandDefinition[]>(() => {
    return [...nodeRegistryNodes]
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
      .map((node) => ({
        id: `node-${node.node_type}`,
        nodeType: node.node_type,
        label: node.display_name,
        category: node.category,
        description: node.description,
        keywords: [
          node.node_type,
          node.category,
          ...(node.description ? [node.description] : []),
          ...(Array.isArray(node.keywords) ? node.keywords : [])
        ],
        icon: createElement(getCategoryIcon(node.category), { size: 18 }),
        capability: "workflow.edit_draft"
      }));
  }, [nodeRegistryNodes]);

  return (
    <>
      <div className="app-shell">
        <Header />
        <EngineErrorBanner />
        <div className="app-workspace">
          {isDesktop ? <Sidebar onOpenRecentRuns={() => setRecentRunsDrawerOpen(true)} /> : null}
          {!isDesktop && isCanvasEditorRoute ? (
            <div className="app-mobile-hint">{t("layout:desktopOnly")}</div>
          ) : null}
          <main className="app-content">
            <div className="app-content-shell">
              <Outlet key={contextKey} />
            </div>
          </main>
        </div>
      </div>

      <CommandPalette
        key={`command-palette:${contextKey}`}
        commands={commands}
        nodeCommands={nodeCommands}
        onClose={() => setCommandPaletteOpen(false)}
        onSelectNode={handleAddNodeFromPalette}
        open={commandPaletteOpen}
        recentWorkflows={recentWorkflows}
      />

      <RecentRunsDrawer
        key={`recent-runs:${contextKey}`}
        onClose={() => setRecentRunsDrawerOpen(false)}
        open={recentRunsDrawerOpen}
      />
    </>
  );
}
