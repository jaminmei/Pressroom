import {
  Background,
  Controls,
  ControlButton,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  SelectionMode,
  useStoreApi,
  type Connection,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type ReactFlowInstance
} from "@xyflow/react";
import { message } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import CanvasEntryToolbar from "@/features/workflow-editor/components/CanvasEntryToolbar";
import CanvasFloatingToolbar from "@/features/workflow-editor/components/CanvasFloatingToolbar";
import {
  getCustomEdgeStyle,
  resolveWorkflowEdgeExecutionStatus
} from "@/features/workflow-editor/components/CustomEdge";
import InlineAddEdge from "@/features/workflow-editor/components/InlineAddEdge";
import NodeContextMenu from "@/features/workflow-editor/components/NodeContextMenu";
import VersionConflictBanner from "@/features/workflow-editor/components/VersionConflictBanner";
import { buildValidatedEdge, getConnectionFailureMessage } from "@/features/workflow-editor/components/canvasConnection";
import EmptyCanvasGuide from "@/features/workflow-editor/components/EmptyCanvasGuide";
import ProgressOverlay from "@/features/task-execution/components/ProgressOverlay";
import WSConnectionBanner from "@/features/task-execution/components/WSConnectionBanner";
import type { TaskNodeVisualStatus } from "@/features/task-execution/store";
import { useTaskExecutionStore } from "@/features/task-execution/store";
import {
  resolveWorkflowNodeComponentType,
  workflowNodeTypes,
  type WorkflowCanvasNodeData
} from "@/features/workflow-editor/nodes/nodeTypes";
import { useMultiSelect } from "@/features/workflow-editor/hooks/useMultiSelect";
import { useWorkflowStore } from "@/features/workflow-editor/store";
import { ENGINE_CATEGORY_MAP } from "@/features/workflow-editor/components/EngineConfigPanel";
import { getDefaultProvider } from "@/services/providerApi";
import { getProviderParamDefaults } from "@/features/workflow-editor/utils/providerDefaults";
import { useWorkflowPersistence } from "@/features/workflow-editor/hooks/useWorkflowPersistence";
import { applyTemplateToWorkflowStore } from "@/features/workflow-editor/templates/applyTemplate";
import type { WorkflowTemplate } from "@/features/workflow-editor/templates/types";
import { localizeWorkflowTemplate } from "@/features/workflow-editor/templates/localizeTemplate";
import { useUIStore } from "@/stores/uiStore";
import type { NodeRegistryNode } from "@/types/node-registry";
import type { WorkflowNode } from "@/types/workflow";
import type { ExecuteWorkflowResult } from "@/hooks/useTaskOrchestration";
import type { TaskStatus } from "@/types/task";

const workflowEdgeTypes: EdgeTypes = {
  workflowEdge: InlineAddEdge
};

interface CanvasProps {
  onCancelTask?: () => Promise<void>;
  onManualReconnect?: () => Promise<boolean>;
  onExecuteWorkflow: (options?: { runName?: string }) => Promise<ExecuteWorkflowResult>;
  taskStatus: TaskStatus | "idle";
  readOnlyTrace?: boolean;
  runOnly?: boolean;
}

/** Captures the React Flow zustand store from inside <ReactFlow> and exposes it via a ref. */
function StoreBridge({ storeRef }: { storeRef: React.MutableRefObject<ReturnType<typeof useStoreApi> | null> }) {
  const store = useStoreApi();
  storeRef.current = store;
  return null;
}

function mapToReactFlowNode(
  node: WorkflowNode,
  index: number,
  nodeStatuses: Record<string, TaskNodeVisualStatus | undefined>,
  isSelected: boolean,
  registryNodes: NodeRegistryNode[] | undefined
): Node {
  const status: TaskNodeVisualStatus = nodeStatuses[node.id] ?? "idle";
  const nodeW = 190;
  const nodeH = 64;
  const handleSize = 10;

  // Resolve maxInputs from node data, falling back to the registry.
  // Template-created nodes may not carry maxInputs in their data.
  const effectiveMaxInputs = node.data.maxInputs ?? registryNodes?.find((n) => n.node_type === node.type)?.max_inputs;

  // Provide explicit handles so that brand-new nodes (not yet in React Flow's
  // internal nodeLookup) are immediately considered "initialized" by
  // isNodeInitialized().  getEdgePosition() will use toHandleBounds(handles)
  // as fallback when internals.handleBounds is not yet populated.
  const handles: Array<{
    id?: string;
    type: "source" | "target";
    position: typeof Position.Left | typeof Position.Right | typeof Position.Top;
    x: number;
    y: number;
    width: number;
    height: number;
  }> = [
    // target handle (left side)
    {
      type: "target",
      position: Position.Left,
      x: 0 - handleSize / 2,
      y: nodeH / 2 - handleSize / 2,
      width: handleSize,
      height: handleSize
    },
    // source handle (right side)
    {
      type: "source",
      position: Position.Right,
      x: nodeW - handleSize / 2,
      y: nodeH / 2 - handleSize / 2,
      width: handleSize,
      height: handleSize
    }
  ];

  // Multi-input nodes also have a context handle on top
  if (effectiveMaxInputs === -1) {
    handles.push({
      id: "input-context",
      type: "target",
      position: Position.Top,
      x: nodeW / 2 - handleSize / 2,
      y: 0 - handleSize / 2,
      width: handleSize,
      height: handleSize
    });
    // The primary handle gets an explicit id for multi-input nodes
    handles[0].id = "input-primary";
  }

  return {
    id: node.id,
    type: resolveWorkflowNodeComponentType(node.type),
    className: `workflow-node workflow-node-${status.replace(/_/g, "-")}${isSelected ? " workflow-node-selected" : ""}`,
    position: node.position ?? { x: 120 + index * 20, y: 120 + index * 20 },
    selected: isSelected,
    // initialWidth/initialHeight 讓 nodeHasDimensions() 立即回傳 true，
    // 節點在 ResizeObserver 測量前就能顯示（visibility: visible）
    initialWidth: nodeW,
    initialHeight: nodeH,
    // Keep measured truthy so React Flow's parseHandles() preserves existing
    // handleBounds when adoptUserNodes re-processes prop nodes (slow path).
    measured: { width: nodeW, height: nodeH },
    handles,
    data: {
      id: node.id,
      label: node.data.label,
      config: node.data.config,
      nodeType: node.type,
      status,
      maxInputs: effectiveMaxInputs
    } satisfies WorkflowCanvasNodeData
  };
}

export default function Canvas({
  onCancelTask,
  onManualReconnect,
  onExecuteWorkflow,
  taskStatus,
  readOnlyTrace = false,
  runOnly = false
}: CanvasProps) {
  const { t } = useTranslation(["common", "workflows"]);
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);
  const addEdge = useWorkflowStore((state) => state.addEdge);
  const addNode = useWorkflowStore((state) => state.addNode);
  const updateNodeConfig = useWorkflowStore((state) => state.updateNodeConfig);

  const setNodes = useWorkflowStore((state) => state.setNodes);
  const setEdges = useWorkflowStore((state) => state.setEdges);
  const selectNode = useWorkflowStore((state) => state.selectNode);
  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const alignNodes = useWorkflowStore((state) => state.alignNodes);
  const duplicateNodes = useWorkflowStore((state) => state.duplicateNodes);
  const removeNodes = useWorkflowStore((state) => state.removeNodes);
  const uiSelectNode = useUIStore((state) => state.selectNode);
  const nodePanelVisible = useUIStore((state) => state.nodePanelVisible);
  const nodeStatuses = useTaskExecutionStore((state) => state.nodeStatuses);
  const canvasResetKey = useWorkflowStore((state) => state.canvasResetKey);

  /* ── Persistence hook for version conflict banner ── */
  const {
    workflowId,
    baseVersion,
    latestVersion,
    newerVersionAvailable,
    pendingConflict,
    lastSavedBy,
    refreshLatestVersion,
    dismissConflict
  } = useWorkflowPersistence();

  const [contextMenu, setContextMenu] = useState<{ nodeId: string; x: number; y: number } | null>(
    null
  );
  const {
    selectedNodeIds,
    hasSelection,
    primarySelectedNodeId,
    syncSelection,
    replaceSelection,
    toggleSelection,
    clearSelection
  } = useMultiSelect(selectedNodeId ? [selectedNodeId] : []);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const reactFlowInstanceRef = useRef<ReactFlowInstance<any, any> | null>(null);
  // Ref filled by StoreBridge (rendered inside <ReactFlow> where the zustand context exists).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const reactFlowStoreRef = useRef<any>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const selectedNodeIdSet = useMemo(() => new Set(selectedNodeIds), [selectedNodeIds]);
  const [zoomLevel, setZoomLevel] = useState(0.9);
  const prevNodeCountRef = useRef(nodes.length);

  /* ── Connection failure tracking refs ── */
  const lastConnectionFailureRef = useRef<string | null>(null);
  const connectionSucceededRef = useRef(false);

  const reactFlowNodes = useMemo(
    () => nodes.map((node, index) => mapToReactFlowNode(node, index, nodeStatuses, selectedNodeIdSet.has(node.id), nodeRegistry.nodes)),
    [nodeRegistry.nodes, nodeStatuses, nodes, selectedNodeIdSet]
  );
  const reactFlowEdges = useMemo(
    () =>
      edges.map((edge) => {
        const executionStatus = resolveWorkflowEdgeExecutionStatus(
          nodeStatuses[edge.source],
          nodeStatuses[edge.target]
        );
        const isTypeWarning = Boolean(edge.data?.isTypeWarning);
        const edgeStyle = getCustomEdgeStyle({ isTypeWarning, executionStatus });
        const markerColor = typeof edgeStyle.stroke === "string" ? edgeStyle.stroke : undefined;

        return {
          ...edge,
          type: "workflowEdge",
          data: {
            ...edge.data,
            executionStatus,
            hideAddControl:
              readOnlyTrace || taskStatus === "pending" || taskStatus === "running"
          },
          style: edgeStyle,
          markerEnd: { type: MarkerType.ArrowClosed, color: markerColor }
        };
      }),
    [edges, nodeStatuses, readOnlyTrace, taskStatus]
  );

  const handleApplyTemplate = useCallback(
    (template: WorkflowTemplate) => {
      const localizedTemplate = localizeWorkflowTemplate(template, t);
      applyTemplateToWorkflowStore(localizedTemplate);
      const nextSelectedNodeId = useWorkflowStore.getState().selectedNodeId;
      replaceSelection(nextSelectedNodeId ? [nextSelectedNodeId] : []);
      message.success(t("workflows:editorText.templateApplied", { name: localizedTemplate.name }));
    },
    [replaceSelection, t]
  );

  const handleBatchDelete = useCallback(() => {
    if (readOnlyTrace) return;
    if (selectedNodeIds.length === 0) return;
    const confirmed = window.confirm(`Delete ${selectedNodeIds.length} selected node(s)?`);
    if (!confirmed) return;
    removeNodes(selectedNodeIds);
    clearSelection();
    setContextMenu(null);
  }, [clearSelection, readOnlyTrace, removeNodes, selectedNodeIds]);

  const handleBatchDuplicate = useCallback(() => {
    if (readOnlyTrace) return;
    if (selectedNodeIds.length === 0) return;
    const duplicatedIds = duplicateNodes(selectedNodeIds, { x: 50, y: 50 });
    if (duplicatedIds.length === 0) return;
    replaceSelection(duplicatedIds);
    setContextMenu(null);
  }, [duplicateNodes, readOnlyTrace, replaceSelection, selectedNodeIds]);

  const handleAlign = useCallback(
    (direction: "horizontal" | "vertical") => {
      if (readOnlyTrace) return;
      if (selectedNodeIds.length <= 1) return;
      alignNodes(selectedNodeIds, direction);
    },
    [alignNodes, readOnlyTrace, selectedNodeIds]
  );

  useEffect(() => {
    selectNode(primarySelectedNodeId);
    uiSelectNode(primarySelectedNodeId);
  }, [primarySelectedNodeId, selectNode, uiSelectNode]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      clearSelection();
      setContextMenu(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [clearSelection]);

  // Debug: expose store on window for console inspection
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    (window as unknown as Record<string, unknown>).__wfStore = useWorkflowStore;
    return () => { delete (window as unknown as Record<string, unknown>).__wfStore; };
  }, []);  // Reset viewport when canvas is cleared (nodes > 0 → 0) and
  // center content when first nodes appear (nodes 0 → > 0).
  useEffect(() => {
    const prev = prevNodeCountRef.current;
    prevNodeCountRef.current = nodes.length;

    const instance = reactFlowInstanceRef.current;
    if (!instance) return;

    if (prev > 0 && nodes.length === 0) {
      // Canvas was cleared — reset viewport to default 90 %
      instance.setViewport({ x: 0, y: 0, zoom: 0.9 });
      setZoomLevel(0.9);
    } else if (prev === 0 && nodes.length > 0) {
      // First node(s) appeared — center at 90 % after layout settles
      setTimeout(() => {
        reactFlowInstanceRef.current?.fitView({ padding: 0.2, duration: 300, maxZoom: 0.9 });
      }, 60);
    }
  }, [nodes.length]);

  // Force edge re-render when workflow is restored from history
  const edgeRefreshEpoch = useWorkflowStore((state) => state.edgeRefreshEpoch);
  useEffect(() => {
    if (edgeRefreshEpoch === 0) return;
    const instance = reactFlowInstanceRef.current;
    if (!instance) return;
    // Wait for nodes to be fully rendered and measured, then force edge refresh
    setTimeout(() => {
      instance.fitView({ padding: 0.2, duration: 300, maxZoom: 0.9 });
      const store = reactFlowStoreRef.current;
      if (store) {
        const { updateNodeInternals: storeUpdateNodeInternals } = store.getState();
        const nodeIds = useWorkflowStore.getState().nodes.map((n) => n.id);
        storeUpdateNodeInternals(new Set(nodeIds));
      }
      // Re-set edges through React Flow's internal store to force path recalculation
      const currentEdges = useWorkflowStore.getState().edges;
      const rfEdges = currentEdges.map((edge) => ({
        ...edge,
        type: "workflowEdge",
        markerEnd: { type: MarkerType.ArrowClosed }
      }));
      const rfStore = reactFlowStoreRef.current;
      if (rfStore) {
        const { setEdges: rfSetEdges } = rfStore.getState();
        rfSetEdges(rfEdges);
      }
    }, 300);
  }, [edgeRefreshEpoch]);

  // Handle drag over - allow drop on the canvas
  const handleDragOver = useCallback((event: DragEvent) => {
    if (readOnlyTrace) return;
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
  }, [readOnlyTrace]);

  // Handle drop - add node to canvas
  const handleDrop = useCallback(
    (event: DragEvent) => {
      if (readOnlyTrace) return;
      event.preventDefault();

      if (!event.dataTransfer) return;

      const nodeType = event.dataTransfer.getData("application/x-node-type");
      if (!nodeType) return;

      const position = reactFlowInstanceRef.current?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY
      });
      const nodeId = addNode(nodeType, position ?? { x: event.clientX, y: event.clientY });

      // Auto-fill default provider for engine-category nodes
      const engineCategory = ENGINE_CATEGORY_MAP[nodeType];
      if (engineCategory) {
        getDefaultProvider(engineCategory)
          .then((defaultProvider) => {
            if (!defaultProvider) return;
            const patch: Record<string, unknown> = {
              provider_id: defaultProvider.id,
              provider_name: defaultProvider.name,
            };
            if (defaultProvider.provider_type === "openai_compatible") {
              const enabled = defaultProvider.models.filter((m) => m.is_enabled);
              patch.model = enabled.length === 1 ? enabled[0].model_id : undefined;
            }
            // Fill in param defaults (language, det_thresh, etc.)
            const paramDefaults = getProviderParamDefaults(defaultProvider);
            Object.assign(patch, paramDefaults);
            updateNodeConfig(nodeId, patch);
          })
          .catch(() => { /* no default provider */ });
      }
    },
    [addNode, readOnlyTrace, updateNodeConfig]
  );

  // Use native DOM events with capture phase to intercept before ReactFlow can stop propagation
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell || readOnlyTrace) return;

    shell.addEventListener("dragover", handleDragOver, true);
    shell.addEventListener("drop", handleDrop, true);

    return () => {
      shell.removeEventListener("dragover", handleDragOver, true);
      shell.removeEventListener("drop", handleDrop, true);
    };
  }, [handleDragOver, handleDrop, readOnlyTrace]);

  const handleCenterView = useCallback(() => {
    const instance = reactFlowInstanceRef.current;
    if (!instance) return;
    const currentZoom = instance.getZoom();
    instance.fitView({
      padding: 0.2,
      duration: 300,
      maxZoom: currentZoom,
      minZoom: currentZoom
    });
  }, []);

  return (
    <section className="workflow-canvas" data-testid="workflow-canvas-panel">
      {!readOnlyTrace ? <WSConnectionBanner onManualReconnect={onManualReconnect} /> : null}
      {!readOnlyTrace ? (
        <VersionConflictBanner
          pendingConflict={pendingConflict}
          newerVersionAvailable={newerVersionAvailable}
          workflowId={workflowId}
          baseVersion={baseVersion}
          latestVersion={latestVersion}
          lastSavedBy={lastSavedBy}
          onRefreshLatest={refreshLatestVersion}
          onKeepLocalDraft={dismissConflict}
          onOpenSaveAs={() => {
            /* Publish As is triggered from the floating toolbar's own modal */
            window.dispatchEvent(new CustomEvent("workflow:open-publish-as"));
          }}
        />
      ) : null}
      <div
        ref={shellRef}
        className={`react-flow-shell${readOnlyTrace ? " is-trace-mode" : ""}`}
        data-testid="react-flow-shell"
      >
        {readOnlyTrace && !runOnly ? (
          <div className="trace-mode-banner" data-testid="trace-mode-banner">
            API trace mode · read-only run snapshot
          </div>
        ) : null}
        <ReactFlow
          key={canvasResetKey}
          edges={reactFlowEdges}
          defaultViewport={{ x: 0, y: 0, zoom: 0.9 }}
          deleteKeyCode={readOnlyTrace ? null : ["Backspace", "Delete"]}
          edgesFocusable={!readOnlyTrace}
          onMoveEnd={(_event, viewport) => setZoomLevel(viewport.zoom)}
          panOnDrag={true}
          isValidConnection={(connection) => {
            if (readOnlyTrace) return false;
            const result = buildValidatedEdge({
              connection,
              nodes,
              edges,
              registry: nodeRegistry
            });
            if (result.edge) {
              lastConnectionFailureRef.current = null;
            } else {
              lastConnectionFailureRef.current = result.errorReason
                ? getConnectionFailureMessage(result.errorReason, t)
                : null;
            }
            return result.edge !== null;
          }}
          minZoom={0.3}
          multiSelectionKeyCode={["Meta", "Control"]}
          nodes={reactFlowNodes}
          nodesConnectable={!readOnlyTrace}
          nodesDraggable={!readOnlyTrace}
          nodeTypes={workflowNodeTypes}
          edgeTypes={workflowEdgeTypes}
          selectionKeyCode="Shift"
          selectionMode={SelectionMode.Partial}
          onInit={(instance) => {
            reactFlowInstanceRef.current = instance;
            // Always reset to default zoom when the canvas initialises,
            // so a previously-adjusted zoom level does not carry over.
            instance.setViewport({ x: 0, y: 0, zoom: 0.9 });
          }}
          onConnect={(connection: Connection) => {
            if (readOnlyTrace) return;
            connectionSucceededRef.current = true;
            const result = buildValidatedEdge({
              connection,
              nodes,
              edges,
              registry: nodeRegistry
            });

            if (!result.edge) {
              const reason = result.errorReason
                ? getConnectionFailureMessage(result.errorReason, t)
                : t("workflows:editorText.connectionFailedUnknown");
              message.warning(reason);
              return;
            }

            const edge = result.edge;
            addEdge(edge);

            // Force React Flow to re-measure handle positions for both
            // endpoints so the edge path coordinates are computed correctly.
            setTimeout(() => {
              const store = reactFlowStoreRef.current;
              if (!store) return;
              const { domNode, updateNodeInternals: storeUpdateNodeInternals } = store.getState();
              const container = domNode;
              const sourceEl = container?.querySelector(`.react-flow__node[data-id="${edge.source}"]`);
              const targetEl = container?.querySelector(`.react-flow__node[data-id="${edge.target}"]`);
              if (sourceEl && targetEl) {
                const updates = new Map([
                  [edge.source, { id: edge.source, nodeElement: sourceEl as HTMLDivElement, force: true }],
                  [edge.target, { id: edge.target, nodeElement: targetEl as HTMLDivElement, force: true }]
                ]);
                storeUpdateNodeInternals(updates, { triggerFitView: false });
              }
            }, 50);

            if (result.warningCode === "type_mismatch") {
              message.warning(t("workflows:editorText.typeWarningConnection"));
            }
          }}
          onConnectStart={() => {
            if (readOnlyTrace) return;
            lastConnectionFailureRef.current = null;
            connectionSucceededRef.current = false;
          }}
          onConnectEnd={(event: MouseEvent | TouchEvent) => {
            if (readOnlyTrace) return;
            if (connectionSucceededRef.current) return;

            const failure = lastConnectionFailureRef.current;
            if (!failure) return;

            const target =
              event instanceof MouseEvent
                ? document.elementFromPoint(event.clientX, event.clientY)
                : document.elementFromPoint(
                    (event as TouchEvent).changedTouches[0].clientX,
                    (event as TouchEvent).changedTouches[0].clientY
                  );
            if (!target?.closest(".react-flow__handle, .react-flow__node")) return;

            message.warning(failure);
            lastConnectionFailureRef.current = null;
          }}
          onEdgesDelete={(deletedEdges) => {
            if (readOnlyTrace) return;
            const deleted = new Set(deletedEdges.map((edge) => edge.id));
            setEdges(edges.filter((edge) => !deleted.has(edge.id)));
          }}
          onPaneClick={() => {
            setContextMenu(null);
            clearSelection();
          }}
          onNodeClick={(event, node) => {
            if (event.metaKey || event.ctrlKey) {
              toggleSelection(node.id);
            } else {
              replaceSelection([node.id]);
            }
            setContextMenu(null);
          }}
          onSelectionChange={({ nodes: selectedNodes }) => {
            syncSelection(selectedNodes.map((node) => node.id));
          }}
          onNodeContextMenu={(event, node) => {
            event.preventDefault();
            replaceSelection([node.id]);
            if (readOnlyTrace) {
              setContextMenu(null);
              return;
            }
            setContextMenu({
              nodeId: node.id,
              x: event.clientX,
              y: event.clientY
            });
          }}
          onNodesChange={(changes: NodeChange<Node>[]) => {
            if (readOnlyTrace) return;
            // 只把 position 變化同步回 store，其餘 change 由 React Flow 內部處理
            const positionChanges = changes.filter(
              (c): c is NodeChange<Node> & { type: "position"; position: { x: number; y: number } } =>
                c.type === "position" && "position" in c && c.position != null
            );
            if (positionChanges.length > 0) {
              const changedPositions = new Map(positionChanges.map((c) => [c.id, c.position]));
              setNodes(
                nodes.map((node) => {
                  const nextPos = changedPositions.get(node.id);
                  return nextPos ? { ...node, position: nextPos } : node;
                })
              );
            }
          }}
          snapGrid={[20, 20]}
          snapToGrid
        >
          <Background gap={20} size={1} />
          <Controls showFitView={false}>
            <ControlButton onClick={handleCenterView} title={t("workflows:editorText.centerView")}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
              </svg>
            </ControlButton>
          </Controls>
          <div
            className="react-flow-minimap-wrapper"
            style={nodePanelVisible ? { right: 592 } : undefined}
          >
            <MiniMap pannable zoomable />
            <div className="react-flow-zoom-indicator">
              {Math.round(zoomLevel * 100)}%
            </div>
          </div>
          <StoreBridge storeRef={reactFlowStoreRef} />
        </ReactFlow>
        {!readOnlyTrace && nodes.length > 0 ? <CanvasEntryToolbar /> : null}
        {!readOnlyTrace && nodes.length === 0 ? (
          <EmptyCanvasGuide
            entryToolbar={<CanvasEntryToolbar className="is-inline-empty-state" label={t("workflows:editorText.addFirstNode")} />}
            onApplyTemplate={handleApplyTemplate}
          />
        ) : null}
        {!readOnlyTrace && contextMenu ? (
          <NodeContextMenu
            nodeId={contextMenu.nodeId}
            onClose={() => setContextMenu(null)}
            x={contextMenu.x}
            y={contextMenu.y}
          />
        ) : null}
        {!readOnlyTrace && hasSelection ? (
          <div className="canvas-batch-toolbar" data-testid="canvas-batch-toolbar">
            <button onClick={handleBatchDelete} type="button">{t("common:delete")}</button>
            <button onClick={handleBatchDuplicate} type="button">{t("workflows:editorText.duplicate")}</button>
            <button onClick={() => handleAlign("horizontal")} type="button">{t("workflows:editorText.alignH")}</button>
            <button onClick={() => handleAlign("vertical")} type="button">{t("workflows:editorText.alignV")}</button>
          </div>
        ) : null}
        {!readOnlyTrace || runOnly ? (
          <>
            <ProgressOverlay
              onCancel={() => {
                void onCancelTask?.();
              }}
            />
            <CanvasFloatingToolbar
              onExecuteWorkflow={onExecuteWorkflow}
              runOnly={runOnly}
              taskStatus={taskStatus}
            />
          </>
        ) : null}
      </div>
    </section>
  );
}
