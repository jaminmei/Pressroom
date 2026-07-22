import { Alert, Flex, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import WorkflowEditor from "@/features/workflow-editor/components/WorkflowEditor";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { getNodeRegistry } from "@/services/nodeRegistryApi";

type PersistedWorkflowLoadState = "idle" | "loading" | "ready" | "error";

async function ensureNodeRegistryLoaded() {
  const currentRegistry = useWorkflowStore.getState().nodeRegistry;
  if (currentRegistry.nodes.length > 0) {
    return;
  }

  const registry = await getNodeRegistry();
  useWorkflowStore.getState().setNodeRegistry({
    nodes: registry.nodes,
    connection_rules: registry.connection_rules
  });
}

export default function PersistedWorkflowEditorPage() {
  const { t } = useTranslation("workflows");
  const { workflowId } = useParams<{ workflowId: string }>();
  const [searchParams] = useSearchParams();
  const traceRunId = searchParams.get("traceRunId");
  const { loadWorkflow, revalidateMetadata } = useWorkflowPersistence();
  const [status, setStatus] = useState<PersistedWorkflowLoadState>("idle");
  const loadWorkflowRef = useRef(loadWorkflow);
  const revalidateMetadataRef = useRef(revalidateMetadata);

  useEffect(() => {
    loadWorkflowRef.current = loadWorkflow;
  }, [loadWorkflow]);

  useEffect(() => {
    revalidateMetadataRef.current = revalidateMetadata;
  }, [revalidateMetadata]);

  useEffect(() => {
    let active = true;

    async function hydrateWorkflow() {
      if (!workflowId) {
        if (active) {
          setStatus("error");
        }
        return;
      }

      if (active) {
        setStatus("loading");
      }

      try {
        await ensureNodeRegistryLoaded();
        const loaded = await loadWorkflowRef.current(workflowId);
        if (active) {
          setStatus(loaded ? "ready" : "error");
        }
      } catch {
        if (active) {
          setStatus("error");
        }
      }
    }

    void hydrateWorkflow();

    return () => {
      active = false;
    };
  }, [workflowId]);

  useEffect(() => {
    if (!workflowId || status !== "ready" || traceRunId) {
      return;
    }

    const onFocus = () => {
      void revalidateMetadataRef.current();
    };

    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
    };
  }, [status, traceRunId, workflowId]);

  if (status === "loading" || status === "idle") {
    return (
      <Flex
        align="center"
        data-testid="persisted-workflow-editor-loading"
        gap={12}
        justify="center"
        style={{ minHeight: 320 }}
        vertical
      >
        <Spin size="large" />
        <span>{t("studioText.loadingSaved")}</span>
      </Flex>
    );
  }

  if (status === "error") {
    return (
      <Alert
        data-testid="persisted-workflow-editor-error"
        description={t("studioText.loadSpecifiedDescription")}
        message={t("studioText.loadSpecifiedFailed")}
        showIcon
        type="error"
      />
    );
  }

  return (
    <WorkflowEditor
      key={`${workflowId}:${traceRunId ?? "edit"}`}
      readOnlyTrace={Boolean(traceRunId)}
      traceRunId={traceRunId}
      traceWorkflowId={workflowId}
    />
  );
}
