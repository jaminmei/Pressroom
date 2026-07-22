import { useCallback, useEffect, useMemo, useState } from "react";

import {
  isEvaluationRunRequestContextCurrent,
} from "@/services/evaluationRunApi";
import { getApiErrorMessage } from "@/services/api";
import {
  getDocumentGroundTruthVersion,
  getLatestDocumentGroundTruth,
  listDocumentGroundTruthVersions,
} from "@/services/projectApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type {
  DocumentGroundTruth,
  GroundTruthVersionSummary,
} from "@/types/project";

export interface UseDocumentGroundTruthResult {
  versions: GroundTruthVersionSummary[];
  selectedVersion: number | null;
  selectedGroundTruth: DocumentGroundTruth | null;
  currentVersion: number | null;
  loading: boolean;
  error: string | null;
  detailLoading: boolean;
  detailError: string | null;
  selectVersion: (version: number) => void;
  retry: () => void;
  retrySelectedVersion: () => void;
}

export function useDocumentGroundTruth(
  projectId: string,
  documentId: string | null,
): UseDocumentGroundTruthResult {
  const [versions, setVersions] = useState<GroundTruthVersionSummary[]>([]);
  const [detailsByVersion, setDetailsByVersion] = useState<
    Record<number, DocumentGroundTruth>
  >({});
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [detailRetryCount, setDetailRetryCount] = useState(0);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);

  useEffect(() => {
    let cancelled = false;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      !cancelled && isEvaluationRunRequestContextCurrent(requestContext);

    setVersions([]);
    setDetailsByVersion({});
    setSelectedVersion(null);
    setCurrentVersion(null);
    setError(null);
    setDetailError(null);
    setDetailLoading(false);
    setLoading(Boolean(projectId && documentId));

    if (projectId && documentId) {
      void (async () => {
        try {
          const [latest, versionItems] = await Promise.all([
            getLatestDocumentGroundTruth(projectId, documentId),
            listDocumentGroundTruthVersions(projectId, documentId),
          ]);
          if (!isCurrentRequest()) return;

          setVersions(versionItems);
          if (latest) {
            setDetailsByVersion({ [latest.version]: latest });
            setCurrentVersion(latest.version);
            setSelectedVersion(latest.version);
          } else if (versionItems.length > 0) {
            setCurrentVersion(versionItems[0].version);
            setSelectedVersion(versionItems[0].version);
          }
        } catch (caught: unknown) {
          if (!isCurrentRequest()) return;
          setError(getApiErrorMessage(caught, "Failed to load ground truth."));
        } finally {
          if (isCurrentRequest()) setLoading(false);
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, [documentId, generation, projectId, retryCount, workspaceId]);

  useEffect(() => {
    if (
      !projectId ||
      !documentId ||
      selectedVersion == null ||
      detailsByVersion[selectedVersion] ||
      !versions.some((item) => item.version === selectedVersion)
    ) {
      return;
    }

    let cancelled = false;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      !cancelled && isEvaluationRunRequestContextCurrent(requestContext);

    setDetailLoading(true);
    setDetailError(null);
    void (async () => {
      try {
        const detail = await getDocumentGroundTruthVersion(
          projectId,
          documentId,
          selectedVersion,
        );
        if (!isCurrentRequest()) return;
        setDetailsByVersion((current) => ({
          ...current,
          [selectedVersion]: detail,
        }));
      } catch (caught: unknown) {
        if (!isCurrentRequest()) return;
        setDetailError(
          getApiErrorMessage(caught, "Failed to load this ground-truth version."),
        );
      } finally {
        if (isCurrentRequest()) setDetailLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    detailsByVersion,
    detailRetryCount,
    documentId,
    generation,
    projectId,
    selectedVersion,
    versions,
    workspaceId,
  ]);

  const selectVersion = useCallback((version: number) => {
    setDetailError(null);
    setSelectedVersion(version);
  }, []);

  const retry = useCallback(() => {
    setRetryCount((current) => current + 1);
  }, []);

  const retrySelectedVersion = useCallback(() => {
    setDetailRetryCount((current) => current + 1);
  }, []);

  const selectedGroundTruth = useMemo(
    () => selectedVersion == null ? null : detailsByVersion[selectedVersion] ?? null,
    [detailsByVersion, selectedVersion],
  );

  return {
    versions,
    selectedVersion,
    selectedGroundTruth,
    currentVersion,
    loading,
    error,
    detailLoading,
    detailError,
    selectVersion,
    retry,
    retrySelectedVersion,
  };
}
