import { DeleteOutlined } from "@ant-design/icons";
import { Button, Popconfirm, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import DynamicForm from "@/features/workflow-editor/components/DynamicForm";
import DynamicWarningBadge from "@/features/workflow-editor/components/DynamicWarningBadge";
import EngineConfigPanel, { ENGINE_CATEGORY_MAP } from "@/features/workflow-editor/components/EngineConfigPanel";
import { useWorkflowStore } from "@/features/workflow-editor/store";

export default function ConfigPanel() {
  const { t } = useTranslation(["workflows", "common"]);
  const nodes = useWorkflowStore((state) => state.nodes);
  const nodeRegistry = useWorkflowStore((state) => state.nodeRegistry);
  const selectedNodeId = useWorkflowStore((state) => state.selectedNodeId);
  const nodeConfigs = useWorkflowStore((state) => state.nodeConfigs);
  const uploadedFiles = useWorkflowStore((state) => state.uploadedFiles);
  const updateNodeConfig = useWorkflowStore((state) => state.updateNodeConfig);
  const setUploadedFile = useWorkflowStore((state) => state.setUploadedFile);
  const removeUploadedFile = useWorkflowStore((state) => state.removeUploadedFile);
  const removeNode = useWorkflowStore((state) => state.removeNode);
  const dynamicWarnings = useWorkflowStore((state) => state.dynamicValidation.warnings);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );
  const registeredNode = useMemo(
    () => nodeRegistry.nodes.find((node) => node.node_type === selectedNode?.type) ?? null,
    [nodeRegistry.nodes, selectedNode?.type]
  );

  useEffect(() => {
    setIsDeleteConfirmOpen(false);
  }, [selectedNodeId]);

  useEffect(() => {
    if (!selectedNode) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Delete") {
        event.preventDefault();
        setIsDeleteConfirmOpen(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedNode]);

  if (!selectedNode) {
    return (
      <div className="config-panel-empty" data-testid="config-panel-empty">
        <Typography.Text type="secondary">
          {t("selectNode")}
        </Typography.Text>
      </div>
    );
  }

  const nodeConfig = nodeConfigs[selectedNode.id] ?? selectedNode.data.config ?? {};

  return (
    <div className="config-panel-content" data-testid="config-panel-content">
      <div className="config-panel-node-header">
        <div className="config-panel-node-info">
          <Typography.Text strong>{registeredNode?.display_name ?? selectedNode.data.label}</Typography.Text>
          <Typography.Text type="secondary" className="config-panel-node-type">
            {selectedNode.type}
          </Typography.Text>
        </div>

        <Popconfirm
          cancelText={t("common:cancel")}
          okText={t("editorText.confirm")}
          onCancel={() => setIsDeleteConfirmOpen(false)}
          onConfirm={() => {
            removeNode(selectedNode.id);
            setIsDeleteConfirmOpen(false);
          }}
          open={isDeleteConfirmOpen}
          title={t("editorText.deleteNodeConfirm")}
        >
          <Button
            aria-label={t("editorText.deleteNode")}
            danger
            icon={<DeleteOutlined />}
            onClick={() => setIsDeleteConfirmOpen(true)}
            size="small"
            type="text"
          />
        </Popconfirm>
      </div>

      {(selectedNode.type && selectedNode.type in ENGINE_CATEGORY_MAP) ? (
        <EngineConfigPanel />
      ) : (
        <DynamicForm
          nodeId={selectedNode.id}
          nodeType={selectedNode.type}
          onChange={(nextConfig) => updateNodeConfig(selectedNode.id, nextConfig)}
          onFileChange={(fieldName, file) => {
            if (file) {
              setUploadedFile(selectedNode.id, file);
              updateNodeConfig(selectedNode.id, { [fieldName]: file.name });
              return;
            }

            removeUploadedFile(selectedNode.id);
            updateNodeConfig(selectedNode.id, { [fieldName]: undefined });
          }}
          schema={registeredNode?.config_schema ?? selectedNode.data.configSchema}
          value={{
            ...nodeConfig,
            ...(uploadedFiles[selectedNode.id] ? { file: uploadedFiles[selectedNode.id] } : {})
          }}
        />
      )}

      {dynamicWarnings.some((warning) => warning.node_id === selectedNode.id) && (
        <DynamicWarningBadge
          warnings={dynamicWarnings}
          nodeId={selectedNode.id}
        />
      )}
    </div>
  );
}
