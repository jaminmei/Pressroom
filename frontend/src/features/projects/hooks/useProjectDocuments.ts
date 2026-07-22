import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectDocument } from "@/types/project";

import { listDocuments, uploadDocuments as apiUploadDocs, deleteDocument as apiDeleteDoc } from "@/services/projectApi";
import {
  captureEvaluationRunRequestContext,
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

export interface UseProjectDocumentsResult {
  documents: ProjectDocument[];
  loading: boolean;
  error: string | null;
  uploadDocuments: (files: File[]) => Promise<void>;
  deleteDocument: (id: string) => Promise<void>;
}

function filterByProject(docs: ProjectDocument[], _projectId: string): ProjectDocument[] {
  // In mock mode, return all; real impl filters by projectId
  return docs;
}

export function useProjectDocuments(projectId: string): UseProjectDocumentsResult {
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  const requestIdRef = useRef(0);
  const baseRef = useRef<ProjectDocument[]>([]);

  const fetchDocuments = useCallback(async (pid: string) => {
    const requestId = ++requestIdRef.current;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === requestIdRef.current && isEvaluationRunRequestContextCurrent(requestContext);
    setLoading(true);
    setError(null);

    try {
      const docs = await listDocuments(pid);
      if (!isCurrentRequest()) return;
      baseRef.current = filterByProject(docs, pid);
      setDocuments([...baseRef.current]);
    } catch (e) {
      if (!isCurrentRequest()) return;
      const msg = e instanceof Error ? e.message : "Failed to load documents";
      setError(msg);
      setDocuments([]);
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [generation, workspaceId]);

  useEffect(() => {
    ++requestIdRef.current;
    setDocuments([]);
    setError(null);

    if (!projectId) return;
    void fetchDocuments(projectId);
  }, [fetchDocuments, projectId]);

  const uploadDocuments = useCallback(async (files: File[]): Promise<void> => {
    const requestContext = captureEvaluationRunRequestContext();
    const newDocs = await apiUploadDocs(projectId, files);
    if (!isEvaluationRunRequestContextCurrent(requestContext)) return;
    baseRef.current = [...newDocs, ...baseRef.current];
    setDocuments([...baseRef.current]);
  }, [projectId]);

  const deleteDocument = useCallback(async (id: string): Promise<void> => {
    const requestContext = captureEvaluationRunRequestContext();
    await apiDeleteDoc(projectId, id);
    if (!isEvaluationRunRequestContextCurrent(requestContext)) return;
    baseRef.current = baseRef.current.filter((d) => d.id !== id);
    setDocuments([...baseRef.current]);
  }, [projectId]);

  return {
    documents,
    loading,
    error,
    uploadDocuments,
    deleteDocument,
  };
}
