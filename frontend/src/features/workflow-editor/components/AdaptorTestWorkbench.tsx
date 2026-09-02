import {
  Alert,
  Badge,
  Button,
  Empty,
  Input,
  Modal,
  Radio,
  Space,
  Spin,
  Tag,
  Typography
} from "antd";
import { isAxiosError } from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import VariablePicker from "@/features/workflow-editor/components/VariablePicker";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import type { InputBinding } from "@/features/workflow-editor/types/inputBindings";
import { buildWorkflowExecutionPayload } from "@/features/workflow-editor/utils/workflowBuilder";
import { apiClient } from "@/services/api";
import type { NodeOutput } from "@/services/taskApi";
import { inputFilesMatch } from "@/utils/inputFileIdentity";
import type { WorkflowNode } from "@/types/workflow";

const { Text, Title } = Typography;
const { TextArea } = Input;
const TEST_CASE_POLL_INTERVAL_MS = 2_000;
const TEST_CASE_POLL_TIMEOUT_MS = 120_000;
const TEST_CASE_POLL_MAX_TRANSIENT_FAILURES = 3;
const WORKBENCH_MODAL_WIDTH = 1_200;

type WorkbenchStatus = "empty" | "pending" | "running_upstream" | "ready" | "blocked" | "failed" | "stale";
type InputMode = "all_upstream" | "custom_bindings";

interface TestCaseNodeState {
  status: string;
  node_type: string;
  error?: { message?: string } | null;
  has_output?: boolean;
}

interface TestCaseResponse {
  test_case_id: string;
  target_node_id: string;
  status: Exclude<WorkbenchStatus, "empty">;
  scope_fingerprint: string;
  workflow_fingerprint?: string;
  nodes: Record<string, TestCaseNodeState>;
  input_identities?: Array<{ filename?: string; name?: string; size?: number }>;
  created_at?: string;
  expires_at?: string | null;
}

interface ExecutionError {
  phase?: string;
  type?: string;
  message?: string;
  traceback?: string;
  line?: number | null;
  column?: number | null;
  retryable?: boolean;
}

interface ExecutionResponse {
  execution_id: string | null;
  status: "succeeded" | "failed" | "running" | string;
  output: NodeOutput | null;
  error: ExecutionError | null;
  stdout: string;
  stderr: string;
  duration_ms: number | null;
}

interface AdaptorTestWorkbenchProps {
  nodeId: string;
  open: boolean;
  onClose: () => void;
}

interface PollHandles {
  controller: AbortController | null;
  nextTimer: number | null;
  timeoutTimer: number | null;
}

function isTransientPollingError(error: unknown): boolean {
  if (!isAxiosError(error)) return false;
  if (!error.response) return true;
  return error.response.status === 408
    || error.response.status === 425
    || error.response.status === 429
    || error.response.status >= 500;
}

function stringifyBindings(bindings: InputBinding[]): string {
  return JSON.stringify(
    bindings.map((binding) => ({
      name: binding.name,
      selector: binding.selector
    }))
  );
}

function buildDraftSignature(code: string, inputMode: InputMode, bindings: InputBinding[]): string {
  return JSON.stringify({
    code,
    inputMode,
    bindings: stringifyBindings(bindings)
  });
}

function sortScopeNodes(scopeNodeIds: string[], nodes: WorkflowNode[]): WorkflowNode[] {
  const scopeSet = new Set(scopeNodeIds);
  return nodes.filter((node) => scopeSet.has(node.id));
}

function getStatusColor(status: WorkbenchStatus): string {
  switch (status) {
    case "ready":
      return "green";
    case "blocked":
    case "failed":
      return "red";
    case "stale":
      return "orange";
    case "running_upstream":
    case "pending":
      return "blue";
    default:
      return "default";
  }
}

function getStatusLabel(status: WorkbenchStatus): string {
  switch (status) {
    case "running_upstream":
      return "Running";
    case "pending":
      return "Pending";
    case "ready":
      return "Ready";
    case "blocked":
      return "Blocked";
    case "failed":
      return "Failed";
    case "stale":
      return "Stale";
    default:
      return "Empty";
  }
}

function isTerminalTestCaseStatus(status: WorkbenchStatus): boolean {
  return status === "ready" || status === "blocked" || status === "failed" || status === "stale";
}

function nodeStatusColor(status: string | undefined): string {
  if (status === "completed") return "green";
  if (status === "failed") return "red";
  return "default";
}

function JsonCollapsible({ data, label, defaultOpen = false }: { data: unknown; label: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const jsonStr = JSON.stringify(data, null, 2) ?? "null";

  return (
    <div style={{ marginBottom: 8 }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4, padding: "4px 0" }}
      >
        <Text style={{ fontSize: 12 }}>{open ? "▼" : "▶"}</Text>
        <Text strong style={{ fontSize: 12 }}>{label}</Text>
        <Text type="secondary" style={{ fontSize: 11 }}>{jsonStr.length > 50 ? `${jsonStr.length} chars` : jsonStr.slice(0, 50)}</Text>
      </div>
      {open ? (
        <pre
          style={{
            background: "#0f172a",
            borderRadius: 6,
            color: "#e2e8f0",
            fontSize: 11,
            lineHeight: 1.5,
            margin: "4px 0 8px",
            maxHeight: 300,
            overflow: "auto",
            padding: 10,
          }}
        >
          {jsonStr}
        </pre>
      ) : null}
    </div>
  );
}

function NodeOutputPreview({ output }: { output: NodeOutput | null }) {
  if (!output) {
    return <Empty description="No output loaded" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const binary = Array.isArray(output.binary) ? output.binary : [];

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      {output.text ? (
        <div>
          <Text strong>Text</Text>
          <div
            style={{
              border: "1px solid #f0f0f0",
              borderRadius: 8,
              marginTop: 4,
              maxHeight: 200,
              overflow: "auto",
              padding: 10,
              whiteSpace: "pre-wrap",
              fontSize: 13,
            }}
          >
            {output.text}
          </div>
        </div>
      ) : null}

      <JsonCollapsible data={binary} label={`binary (${binary.length} items)`} />
      <JsonCollapsible data={output.structured} label="structured" defaultOpen={output.text == null && binary.length === 0} />
      <JsonCollapsible data={output.metadata} label="metadata" />
    </Space>
  );
}

function ExecutionResultPanel({ execution }: { execution: ExecutionResponse | null }) {
  if (!execution) {
    return <Empty description="Run Test Code to inspect execution output" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const succeeded = execution.status === "succeeded";
  const failed = execution.status === "failed";
  let statusColor = "blue";
  if (succeeded) statusColor = "green";
  else if (failed) statusColor = "red";
  let statusLabel = execution.status;
  if (succeeded) statusLabel = "Succeeded";
  else if (failed) statusLabel = "Failed";

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Space align="center" size={12}>
        <Badge color={statusColor} />
        <Text strong>{statusLabel}</Text>
        {execution.duration_ms != null ? <Text type="secondary">{execution.duration_ms} ms</Text> : null}
      </Space>

      {execution.error ? (
        <Alert
          message={execution.error.message ?? "Execution failed"}
          showIcon
          type="error"
          description={(
            <Space direction="vertical" size={4}>
              {execution.error.phase ? <Text>{execution.error.phase}</Text> : null}
              {execution.error.type ? <Text>{execution.error.type}</Text> : null}
              {execution.error.line != null ? <Text>{`Line ${execution.error.line}`}</Text> : null}
              {execution.error.traceback ? (
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{execution.error.traceback}</pre>
              ) : null}
            </Space>
          )}
        />
      ) : null}

      {execution.output ? <NodeOutputPreview output={execution.output} /> : null}

      {execution.stdout ? (
        <div>
          <Text strong>stdout</Text>
          <pre style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>{execution.stdout}</pre>
        </div>
      ) : null}

      {execution.stderr ? (
        <div>
          <Text strong>stderr</Text>
          <pre style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>{execution.stderr}</pre>
        </div>
      ) : null}
    </Space>
  );
}

function OutputInspector({
  error,
  loading,
  output,
  selectedNodeId,
  testCase,
}: {
  error: string | null;
  loading: boolean;
  output: NodeOutput | null;
  selectedNodeId: string | null;
  testCase: TestCaseResponse | null;
}) {
  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
        <Spin />
      </div>
    );
  }
  if (error) return <Alert message={error} showIcon type="error" />;
  if (selectedNodeId && testCase?.nodes[selectedNodeId]?.status === "failed") {
    return (
      <Alert
        description={testCase.nodes[selectedNodeId].error?.message ?? "Unknown error"}
        message="Node execution failed"
        showIcon
        type="error"
      />
    );
  }
  if (selectedNodeId && testCase?.nodes[selectedNodeId]?.status !== "completed") {
    return <Alert message="Selected node has no completed output yet." showIcon type="info" />;
  }
  return <NodeOutputPreview output={output} />;
}

export default function AdaptorTestWorkbench({ nodeId, open, onClose }: AdaptorTestWorkbenchProps) {
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);
  const updateNodeConfig = useWorkflowStore((state) => state.updateNodeConfig);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === nodeId) ?? null,
    [nodeId, nodes]
  );

  const adaptorConfig = (nodeConfigs[nodeId] ?? selectedNode?.data.config ?? {}) as Record<string, unknown>;
  const [testCase, setTestCase] = useState<TestCaseResponse | null>(null);
  const [workbenchStatus, setWorkbenchStatus] = useState<WorkbenchStatus>("empty");
  const [loadingTestCase, setLoadingTestCase] = useState(false);
  const [loadingNodeOutput, setLoadingNodeOutput] = useState(false);
  const [runningExecution, setRunningExecution] = useState(false);
  const [inspectorError, setInspectorError] = useState<string | null>(null);
  const [headerError, setHeaderError] = useState<string | null>(null);
  const [selectedScopeNodeId, setSelectedScopeNodeId] = useState<string | null>(null);
  const [selectedNodeOutput, setSelectedNodeOutput] = useState<NodeOutput | null>(null);
  const [draftCode, setDraftCode] = useState(typeof adaptorConfig.code === "string" ? adaptorConfig.code : "");
  const [draftInputMode, setDraftInputMode] = useState<InputMode>(
    adaptorConfig.input_mode === "custom_bindings" ? "custom_bindings" : "all_upstream"
  );
  const [draftBindings, setDraftBindings] = useState<InputBinding[]>(
    Array.isArray(adaptorConfig.input_bindings) ? adaptorConfig.input_bindings as InputBinding[] : []
  );
  const [execution, setExecution] = useState<ExecutionResponse | null>(null);
  const [verifiedDraftSignature, setVerifiedDraftSignature] = useState<string | null>(null);
  const pollHandlesRef = useRef<PollHandles>({ controller: null, nextTimer: null, timeoutTimer: null });
  const pollingGenerationRef = useRef(0);

  const stopTestCasePolling = useCallback((updateLoading = true) => {
    pollingGenerationRef.current += 1;
    const handles = pollHandlesRef.current;
    handles.controller?.abort();
    if (handles.nextTimer !== null) window.clearTimeout(handles.nextTimer);
    if (handles.timeoutTimer !== null) window.clearTimeout(handles.timeoutTimer);
    pollHandlesRef.current = { controller: null, nextTimer: null, timeoutTimer: null };
    if (updateLoading) setLoadingTestCase(false);
  }, []);

  const startTestCasePolling = useCallback((testCaseId: string, pollImmediately = false) => {
    stopTestCasePolling(false);
    const generation = pollingGenerationRef.current;
    let transientFailureCount = 0;

    async function pollOnce() {
      const controller = new AbortController();
      pollHandlesRef.current.controller = controller;
      try {
        const response = await apiClient.get<TestCaseResponse>(`/adaptor-test-cases/${testCaseId}`, {
          signal: controller.signal,
        });
        if (generation !== pollingGenerationRef.current) return;
        transientFailureCount = 0;
        setTestCase(response.data);
        setWorkbenchStatus(response.data.status);
        if (isTerminalTestCaseStatus(response.data.status)) {
          stopTestCasePolling();
          return;
        }
        scheduleNext();
      } catch (error) {
        if (generation !== pollingGenerationRef.current || controller.signal.aborted) return;
        if (isTransientPollingError(error)
          && transientFailureCount < TEST_CASE_POLL_MAX_TRANSIENT_FAILURES) {
          transientFailureCount += 1;
          scheduleNext();
          return;
        }
        setHeaderError(error instanceof Error ? error.message : "Failed to refresh test case");
        stopTestCasePolling();
      } finally {
        if (pollHandlesRef.current.controller === controller) {
          pollHandlesRef.current.controller = null;
        }
      }
    }
    function scheduleNext() {
      if (generation !== pollingGenerationRef.current) return;
      pollHandlesRef.current.nextTimer = window.setTimeout(
        () => void pollOnce(),
        TEST_CASE_POLL_INTERVAL_MS,
      );
    }

    pollHandlesRef.current.timeoutTimer = window.setTimeout(() => {
      if (generation !== pollingGenerationRef.current) return;
      setHeaderError("Timed out while waiting for the test case.");
      stopTestCasePolling();
    }, TEST_CASE_POLL_TIMEOUT_MS);
    if (pollImmediately) void pollOnce();
    else scheduleNext();
  }, [stopTestCasePolling]);

  useEffect(() => {
    if (!open) stopTestCasePolling();
    // A node switch must invalidate the previous node's in-flight poll before
    // the node-scoped state reset below runs.
    return () => stopTestCasePolling(false);
  }, [nodeId, open, stopTestCasePolling]);

  useEffect(() => {
    if (!open) {
      return;
    }

    setDraftCode(typeof adaptorConfig.code === "string" ? adaptorConfig.code : "");
    setDraftInputMode(adaptorConfig.input_mode === "custom_bindings" ? "custom_bindings" : "all_upstream");
    setDraftBindings(Array.isArray(adaptorConfig.input_bindings) ? adaptorConfig.input_bindings as InputBinding[] : []);
  }, [adaptorConfig.code, adaptorConfig.input_bindings, adaptorConfig.input_mode, open]);

  useEffect(() => {
    setTestCase(null);
    setWorkbenchStatus("empty");
    setSelectedScopeNodeId(null);
    setSelectedNodeOutput(null);
    setExecution(null);
    setVerifiedDraftSignature(null);
    setInspectorError(null);
    setHeaderError(null);
    setLoadingTestCase(false);
    setLoadingNodeOutput(false);
    setRunningExecution(false);
  }, [nodeId]);

  const scopeNodes = useMemo(() => {
    if (!testCase) {
      return [];
    }
    return sortScopeNodes(Object.keys(testCase.nodes), nodes);
  }, [nodes, testCase]);

  const currentDraftSignature = useMemo(
    () => buildDraftSignature(draftCode, draftInputMode, draftBindings),
    [draftBindings, draftCode, draftInputMode]
  );

  const isDraftVerified = execution?.status === "succeeded" && verifiedDraftSignature === currentDraftSignature;
  const selectedTestCaseId = testCase?.test_case_id;
  const selectedScopeNodeStatus = selectedScopeNodeId
    ? testCase?.nodes[selectedScopeNodeId]?.status
    : undefined;

  useEffect(() => {
    if (!testCase) {
      return;
    }

    const currentInputIdentities = Object.values(uploadedFiles).map((file) => ({ name: file.name || "unknown", size: file.size || 0 }));
    const savedInputIdentities = (testCase.input_identities ?? []).map((item) => ({ name: item.name || item.filename || "unknown", size: item.size ?? 0 }));
    const inputFingerprintChanged = Array.isArray(testCase.input_identities)
      ? !inputFilesMatch(savedInputIdentities, currentInputIdentities)
      : false;

    if (inputFingerprintChanged) {
      setWorkbenchStatus("stale");
      return;
    }

    setWorkbenchStatus(testCase.status);
  }, [testCase, uploadedFiles]);

  useEffect(() => {
    if (!selectedScopeNodeId || !selectedTestCaseId) {
      return;
    }

    if (selectedScopeNodeStatus !== "completed") {
      setSelectedNodeOutput(null);
      return;
    }

    let disposed = false;
    const loadNodeOutput = async () => {
      setLoadingNodeOutput(true);
      setInspectorError(null);
      try {
        const response = await apiClient.get<{ node_id: string; output: NodeOutput }>(
          `/adaptor-test-cases/${selectedTestCaseId}/nodes/${selectedScopeNodeId}/result`
        );
        if (!disposed) {
          setSelectedNodeOutput(response.data.output);
        }
      } catch (error) {
        if (!disposed) {
          setSelectedNodeOutput(null);
          setInspectorError(error instanceof Error ? error.message : "Failed to load node output");
        }
      } finally {
        if (!disposed) {
          setLoadingNodeOutput(false);
        }
      }
    };

    void loadNodeOutput();

    return () => {
      disposed = true;
    };
  }, [selectedScopeNodeId, selectedScopeNodeStatus, selectedTestCaseId]);

  const createTestCase = async () => {
    stopTestCasePolling(false);
    const generation = pollingGenerationRef.current;
    const payload = buildWorkflowExecutionPayload({
      nodes,
      edges,
      nodeConfigs,
      uploadedFiles
    });
    const formData = new FormData();
    formData.append("workflow", JSON.stringify(payload.workflow));
    formData.append("target_node_id", nodeId);
    payload.orderedFiles.forEach((file) => {
      formData.append("files", file);
    });

    setLoadingTestCase(true);
    setHeaderError(null);
    setExecution(null);
    setVerifiedDraftSignature(null);

    try {
      const response = await apiClient.post<TestCaseResponse>("/adaptor-test-cases", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });
      if (generation !== pollingGenerationRef.current) return;
      setTestCase(response.data);
      setWorkbenchStatus(response.data.status);
      const firstScopeNode = Object.keys(response.data.nodes)[0] ?? null;
      setSelectedScopeNodeId(firstScopeNode);

      if (response.data.status === "pending" || response.data.status === "running_upstream") {
        startTestCasePolling(response.data.test_case_id);
      } else {
        setLoadingTestCase(false);
      }
    } catch (error) {
      if (generation !== pollingGenerationRef.current) return;
      setHeaderError(error instanceof Error ? error.message : "Failed to create test case");
      setLoadingTestCase(false);
    }
  };

  const refreshTestCase = async () => {
    if (!testCase) {
      await createTestCase();
      return;
    }

    setLoadingTestCase(true);
    setHeaderError(null);
    startTestCasePolling(testCase.test_case_id, true);
  };

  const cancelTestCase = async () => {
    if (!testCase) {
      return;
    }

    stopTestCasePolling();
    try {
      await apiClient.delete(`/adaptor-test-cases/${testCase.test_case_id}`);
      setTestCase(null);
      setWorkbenchStatus("empty");
      setSelectedScopeNodeId(null);
      setSelectedNodeOutput(null);
      setExecution(null);
      setVerifiedDraftSignature(null);
    } catch (error) {
      setHeaderError(error instanceof Error ? error.message : "Failed to cancel test case");
    }
  };

  const runExecution = async () => {
    if (!testCase) {
      setHeaderError("Load a test case before running code.");
      return;
    }

    setRunningExecution(true);
    setHeaderError(null);
    try {
      const response = await apiClient.post<ExecutionResponse>(
        `/adaptor-test-cases/${testCase.test_case_id}/executions`,
        {
          code: draftCode,
          input_mode: draftInputMode,
          bindings: draftBindings
        }
      );
      setExecution(response.data);
      if (response.data.status === "succeeded") {
        setVerifiedDraftSignature(currentDraftSignature);
      }
    } catch (error) {
      setExecution(null);
      setHeaderError(error instanceof Error ? error.message : "Failed to run test code");
    } finally {
      setRunningExecution(false);
    }
  };

  const applyDraft = () => {
    if (!isDraftVerified) {
      return;
    }
    updateNodeConfig(nodeId, {
      code: draftCode,
      input_mode: draftInputMode,
      input_bindings: draftBindings
    });
  };

  const isApplyEnabled = Boolean(testCase && workbenchStatus === "ready" && isDraftVerified);
  const showUntestedChanges = verifiedDraftSignature != null && verifiedDraftSignature !== currentDraftSignature;
  const handleClose = () => {
    stopTestCasePolling();
    onClose();
  };

  return (
    <Modal
      destroyOnHidden
      footer={(
        <Space>
          <Button onClick={handleClose}>Close</Button>
          <Button disabled={!isApplyEnabled} onClick={applyDraft} type="primary">
            Apply
          </Button>
        </Space>
      )}
      onCancel={handleClose}
      open={open}
      title="Adaptor Test Workbench"
      width={WORKBENCH_MODAL_WIDTH}
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <div
          style={{
            border: "1px solid #f0f0f0",
            borderRadius: 12,
            padding: 16
          }}
        >
          <Space align="start" size={16} style={{ justifyContent: "space-between", width: "100%" }}>
            <Space direction="vertical" size={6}>
              <Space align="center">
                <Badge color={getStatusColor(workbenchStatus)} />
                <Title level={5} style={{ margin: 0 }}>{getStatusLabel(workbenchStatus)}</Title>
                {showUntestedChanges ? <Tag color="orange">UNTESTED_CHANGES</Tag> : null}
              </Space>
              <Text type="secondary">{selectedNode?.data.label ?? nodeId}</Text>
              {testCase?.scope_fingerprint ? <Text code>{testCase.scope_fingerprint}</Text> : null}
              {workbenchStatus === "stale" ? (
                <Alert
                  message="Test case is stale"
                  description="Upstream node configuration or input files changed after this test case was created. Refresh before testing or applying."
                  showIcon
                  type="warning"
                />
              ) : null}
            </Space>

            <Space>
              <Button loading={loadingTestCase} onClick={() => void createTestCase()}>
                Load
              </Button>
              <Button disabled={!testCase} loading={loadingTestCase} onClick={() => void refreshTestCase()}>
                Refresh
              </Button>
              <Button danger disabled={!testCase} onClick={() => void cancelTestCase()}>
                Cancel
              </Button>
            </Space>
          </Space>
          {headerError ? <Alert message={headerError} showIcon style={{ marginTop: 12 }} type="error" /> : null}
        </div>

        <div
          style={{
            display: "grid",
            gap: 16,
            gridTemplateColumns: "280px minmax(0, 1fr)"
          }}
        >
          <div
            style={{
              border: "1px solid #f0f0f0",
              borderRadius: 12,
              padding: 16
            }}
          >
            <Title level={5}>Upstream Scope</Title>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              {scopeNodes.length === 0 ? (
                <Empty description="Load a test case to inspect upstream nodes" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : scopeNodes.map((node) => {
                const scopeState = testCase?.nodes[node.id];
                const isSelected = selectedScopeNodeId === node.id;
                return (
                  <Button
                    block
                    key={node.id}
                    onClick={() => setSelectedScopeNodeId(node.id)}
                    style={{ justifyContent: "space-between" }}
                    type={isSelected ? "primary" : "default"}
                  >
                    <span>{node.data.label}</span>
                    <Tag color={nodeStatusColor(scopeState?.status)}>
                      {scopeState?.status ?? "pending"}
                    </Tag>
                  </Button>
                );
              })}
            </Space>
          </div>

          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <div
              style={{
                border: "1px solid #f0f0f0",
                borderRadius: 12,
                padding: 16
              }}
            >
              <Title level={5}>Output Inspector</Title>
              <OutputInspector
                error={inspectorError}
                loading={loadingNodeOutput}
                output={selectedNodeOutput}
                selectedNodeId={selectedScopeNodeId}
                testCase={testCase}
              />
            </div>

            <div
              style={{
                border: "1px solid #f0f0f0",
                borderRadius: 12,
                padding: 16
              }}
            >
              <Title level={5}>Input Configuration</Title>
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Radio.Group
                  onChange={(event) => setDraftInputMode(event.target.value as InputMode)}
                  optionType="button"
                  options={[
                    { label: "All Upstream", value: "all_upstream" },
                    { label: "Custom Bindings", value: "custom_bindings" }
                  ]}
                  value={draftInputMode}
                />
                {draftInputMode === "custom_bindings" ? (
                  <VariablePicker bindings={draftBindings} nodeId={nodeId} onChange={setDraftBindings} />
                ) : (
                  <Text type="secondary">All completed upstream node outputs will be exposed to the adaptor by node ID.</Text>
                )}
              </Space>
            </div>

            <div
              style={{
                border: "1px solid #f0f0f0",
                borderRadius: 12,
                padding: 16
              }}
            >
              <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
                <Title level={5} style={{ margin: 0 }}>Code Editor</Title>
                <Button loading={runningExecution} onClick={() => void runExecution()} type="primary">
                  Test Code
                </Button>
              </Space>
              <Text type="secondary">Draft code stays local until Apply writes the verified configuration into the canvas store.</Text>
              <TextArea
                data-testid="adaptor-workbench-code-editor"
                onChange={(event) => setDraftCode(event.target.value)}
                style={{ fontFamily: "monospace", marginTop: 12, minHeight: 220 }}
                value={draftCode}
              />
            </div>

            <div
              style={{
                border: "1px solid #f0f0f0",
                borderRadius: 12,
                padding: 16
              }}
            >
              <Title level={5}>Execution Result</Title>
              <ExecutionResultPanel execution={execution} />
            </div>
          </Space>
        </div>
      </Space>
    </Modal>
  );
}
