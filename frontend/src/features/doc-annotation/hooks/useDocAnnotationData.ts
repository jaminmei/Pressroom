import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  listTestSetDocuments,
  listTestSets,
  uploadTestSetDocuments
} from "@/services/testSetApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type {
  TestDocument,
  TestDocumentUploadError,
  TestSet
} from "@/types/testSet";

interface UseDocAnnotationDataResult {
  testSets: TestSet[];
  selectedTestSetId: string | null;
  selectedTestSet: TestSet | null;
  documents: TestDocument[];
  testSetsError: string | null;
  documentsError: string | null;
  loadingTestSets: boolean;
  loadingDocuments: boolean;
  uploadPending: boolean;
  queuedFiles: File[];
  uploadErrors: TestDocumentUploadError[];
  uploadedCount: number;
  setSelectedTestSetId: (value: string) => void;
  setQueuedFiles: (files: File[]) => void;
  appendQueuedFiles: (files: File[]) => void;
  uploadDocuments: () => Promise<void>;
}

export function useDocAnnotationData(): UseDocAnnotationDataResult {
  const { t } = useTranslation("projects");
  const [testSets, setTestSets] = useState<TestSet[]>([]);
  const [selectedTestSetId, setSelectedTestSetId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<TestDocument[]>([]);
  const [testSetsError, setTestSetsError] = useState<string | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [loadingTestSets, setLoadingTestSets] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [uploadPending, setUploadPending] = useState(false);
  const [queuedFiles, setQueuedFiles] = useState<File[]>([]);
  const [uploadErrors, setUploadErrors] = useState<TestDocumentUploadError[]>([]);
  const [uploadedCount, setUploadedCount] = useState(0);
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id ?? null);
  const generation = useWorkspaceStore((state) => state.contextGeneration);
  const testSetsRequestIdRef = useRef(0);
  const documentRequestIdRef = useRef(0);
  const selectedTestSetIdRef = useRef<string | null>(null);

  const refreshTestSets = useCallback(async () => {
    const requestId = ++testSetsRequestIdRef.current;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === testSetsRequestIdRef.current &&
      requestContext.workspaceId === (useWorkspaceStore.getState().currentWorkspace?.id ?? null) &&
      requestContext.generation === useWorkspaceStore.getState().contextGeneration;
    setLoadingTestSets(true);
    setTestSetsError(null);
    try {
      const response = await listTestSets();
      if (!isCurrentRequest()) return;
      setTestSets(response.items);
    } catch {
      if (!isCurrentRequest()) return;
      setTestSets([]);
      setTestSetsError(t("legacy.loadTestSetsFailed"));
    } finally {
      if (isCurrentRequest()) setLoadingTestSets(false);
    }
  }, [generation, t, workspaceId]);

  const refreshDocuments = useCallback(async (testSetId: string) => {
    const requestId = documentRequestIdRef.current + 1;
    documentRequestIdRef.current = requestId;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      requestId === documentRequestIdRef.current &&
      requestContext.workspaceId === (useWorkspaceStore.getState().currentWorkspace?.id ?? null) &&
      requestContext.generation === useWorkspaceStore.getState().contextGeneration;
    setLoadingDocuments(true);
    setDocumentsError(null);
    setDocuments([]);
    try {
      const response = await listTestSetDocuments(testSetId);
      if (!isCurrentRequest()) {
        return;
      }

      setDocuments(response.items);
    } catch {
      if (!isCurrentRequest()) {
        return;
      }

      setDocuments([]);
      setDocumentsError(t("legacy.loadDocumentsFailed"));
    } finally {
      if (isCurrentRequest()) {
        setLoadingDocuments(false);
      }
    }
  }, [generation, t, workspaceId]);

  useEffect(() => {
    void refreshTestSets();
  }, [generation, refreshTestSets, workspaceId]);

  useEffect(() => {
    documentRequestIdRef.current += 1;
    selectedTestSetIdRef.current = null;
    setSelectedTestSetId(null);
    setDocuments([]);
    setQueuedFiles([]);
    setUploadErrors([]);
    setUploadedCount(0);
    setDocumentsError(null);
  }, [generation, workspaceId]);

  useEffect(() => {
    selectedTestSetIdRef.current = selectedTestSetId;

    if (!selectedTestSetId) {
      documentRequestIdRef.current += 1;
      setDocuments([]);
      setQueuedFiles([]);
      setUploadErrors([]);
      setUploadedCount(0);
      setDocumentsError(null);
      return;
    }

    setDocuments([]);
    setQueuedFiles([]);
    setUploadErrors([]);
    setUploadedCount(0);
    setDocumentsError(null);

    void refreshDocuments(selectedTestSetId);
  }, [refreshDocuments, selectedTestSetId]);

  const appendQueuedFiles = useCallback((files: File[]) => {
    setQueuedFiles((current) => {
      const nextFiles = [...current];
      files.forEach((file) => {
        const alreadyQueued = nextFiles.some(
          (queuedFile) =>
            queuedFile.name === file.name &&
            queuedFile.size === file.size &&
            queuedFile.lastModified === file.lastModified
        );

        if (!alreadyQueued) {
          nextFiles.push(file);
        }
      });
      return nextFiles;
    });
  }, []);

  const uploadDocuments = useCallback(async () => {
    if (!selectedTestSetId || queuedFiles.length === 0) {
      return;
    }

    const activeTestSetId = selectedTestSetId;
    const requestContext = { workspaceId, generation };
    const isCurrentRequest = () =>
      activeTestSetId === selectedTestSetIdRef.current &&
      requestContext.workspaceId === (useWorkspaceStore.getState().currentWorkspace?.id ?? null) &&
      requestContext.generation === useWorkspaceStore.getState().contextGeneration;

    setUploadPending(true);
    setDocumentsError(null);
    setUploadErrors([]);
    setUploadedCount(0);
    try {
      const response = await uploadTestSetDocuments(activeTestSetId, queuedFiles);
      if (!isCurrentRequest()) {
        return;
      }

      setUploadErrors(response.errors);
      setUploadedCount(response.uploaded.length);
      setQueuedFiles([]);
      await Promise.all([refreshDocuments(activeTestSetId), refreshTestSets()]);
    } catch {
      if (!isCurrentRequest()) {
        return;
      }

      setDocumentsError(t("legacy.uploadDocumentsFailed"));
    } finally {
      if (isCurrentRequest()) {
        setUploadPending(false);
      }
    }
  }, [generation, queuedFiles, refreshDocuments, refreshTestSets, selectedTestSetId, t, workspaceId]);

  const selectedTestSet = useMemo(
    () => testSets.find((testSet) => testSet.id === selectedTestSetId) ?? null,
    [selectedTestSetId, testSets]
  );

  return {
    testSets,
    selectedTestSetId,
    selectedTestSet,
    documents,
    testSetsError,
    documentsError,
    loadingTestSets,
    loadingDocuments,
    uploadPending,
    queuedFiles,
    uploadErrors,
    uploadedCount,
    setSelectedTestSetId,
    setQueuedFiles,
    appendQueuedFiles,
    uploadDocuments,
  };
}
