import { useCallback, useEffect, useRef, useState } from "react";

import type { Project } from "@/types/project";

import {
  createProject as apiCreateProject,
  deleteProject as apiDeleteProject,
  listProjects,
  updateProject as apiUpdateProject,
} from "@/services/projectApi";
import {
  captureEvaluationRunRequestContext,
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

const VIEW_MODE_KEY = "projects-list-view-mode";

type ViewMode = "grid" | "list";

export interface UseProjectsListResult {
  items: Project[];
  loading: boolean;
  error: string | null;
  query: string;
  setQuery: (q: string) => void;
  clearQuery: () => void;
  refresh: () => Promise<void>;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  createProject: (name: string, description?: string) => Promise<Project>;
  deleteProject: (id: string) => Promise<void>;
  renameProject: (id: string, name: string) => Promise<void>;
  duplicateProject: (id: string) => Promise<void>;
}

function getStoredViewMode(): ViewMode {
  try {
    const stored = localStorage.getItem(VIEW_MODE_KEY);
    if (stored === "grid" || stored === "list") return stored;
  } catch { // no-excuse-ok: catch -- localStorage is optional browser state
    // localStorage unavailable
  }
  return "grid";
}

function filterProjects(projects: Project[], query: string): Project[] {
  const q = query.trim().toLowerCase();
  if (!q) return projects;
  return projects.filter((p) => p.name.toLowerCase().includes(q));
}

export function useProjectsList(): UseProjectsListResult {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [viewMode, setViewModeState] = useState<ViewMode>(getStoredViewMode);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const requestIdRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const baseItemsRef = useRef<Project[]>([]);

  const fetchProjects = useCallback(async () => {
    const reqId = ++requestIdRef.current;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      reqId === requestIdRef.current && isEvaluationRunRequestContextCurrent(requestContext);
    setLoading(true);
    setError(null);

    try {
      const projects = await listProjects();
      if (!isCurrentRequest()) return;
      baseItemsRef.current = projects;
      setItems(baseItemsRef.current);
    } catch (e) {
      if (!isCurrentRequest()) return;
      const msg = e instanceof Error ? e.message : "Failed to load projects";
      setError(msg);
      setItems([]);
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [generation, workspaceId]);

  const applySearch = useCallback((q: string) => {
    setItems(filterProjects(baseItemsRef.current, q));
  }, []);

  const setViewMode = useCallback(
    (mode: ViewMode) => {
      setViewModeState(mode);
      try {
        localStorage.setItem(VIEW_MODE_KEY, mode);
      } catch { // no-excuse-ok: catch -- localStorage is optional browser state
        // localStorage unavailable
      }
    },
    [],
  );

  const refresh = useCallback(async () => {
    await fetchProjects();
    applySearch(query);
  }, [fetchProjects, applySearch, query]);

  const clearQuery = useCallback(() => {
    setQuery("");
    setItems(baseItemsRef.current);
  }, []);

  const createProject = useCallback(
    async (name: string, description?: string): Promise<Project> => {
      const requestContext = captureEvaluationRunRequestContext();
      const newProject = await apiCreateProject({ name, description });
      if (!isEvaluationRunRequestContextCurrent(requestContext)) return newProject;
      baseItemsRef.current = [newProject, ...baseItemsRef.current];
      setItems(filterProjects(baseItemsRef.current, query));
      return newProject;
    },
    [query],
  );

  const deleteProject = useCallback(
    async (id: string): Promise<void> => {
      const requestContext = captureEvaluationRunRequestContext();
      await apiDeleteProject(id);
      if (!isEvaluationRunRequestContextCurrent(requestContext)) return;
      baseItemsRef.current = baseItemsRef.current.filter((p) => p.id !== id);
      setItems(filterProjects(baseItemsRef.current, query));
    },
    [query],
  );

  const renameProject = useCallback(
    async (id: string, name: string): Promise<void> => {
      const requestContext = captureEvaluationRunRequestContext();
      await apiUpdateProject(id, { name });
      if (!isEvaluationRunRequestContextCurrent(requestContext)) return;
      baseItemsRef.current = baseItemsRef.current.map((p) =>
        p.id === id ? { ...p, name, lastUpdated: new Date().toISOString() } : p,
      );
      setItems(filterProjects(baseItemsRef.current, query));
    },
    [query],
  );

  const duplicateProject = useCallback(
    async (id: string): Promise<void> => {
      const original = baseItemsRef.current.find((p) => p.id === id);
      if (!original) return;
      const requestContext = captureEvaluationRunRequestContext();
      const copy = await apiCreateProject({
        name: `${original.name} (Copy)`,
        description: original.description,
      });
      if (!isEvaluationRunRequestContextCurrent(requestContext)) return;
      baseItemsRef.current = [copy, ...baseItemsRef.current];
      setItems(filterProjects(baseItemsRef.current, query));
    },
    [query],
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      applySearch(query);
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, applySearch]);

  useEffect(() => {
    baseItemsRef.current = [];
    setItems([]);
    fetchProjects();
  }, [fetchProjects]);

  return {
    items,
    loading,
    error,
    query,
    setQuery,
    clearQuery,
    refresh,
    viewMode,
    setViewMode,
    createProject,
    deleteProject,
    renameProject,
    duplicateProject,
  };
}
