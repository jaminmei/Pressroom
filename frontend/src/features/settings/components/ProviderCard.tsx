import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, Input, Modal, Space, Spin, Tag, Tooltip, Typography } from "antd";
import {
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  PlusOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import type { Provider, TestConnectionResponse, TestModelResponse, ProviderModelCreate } from "@/types/provider";
import { authTypeRegistry } from "@/types/authTypeRegistry";
import { getProvider } from "@/services/providerApi";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import ModelToggleList from "./ModelToggleList";

interface ProviderCardProps {
  provider: Provider;
  category: string;
  onEdit: (provider: Provider) => void;
  onDelete: (provider: Provider) => void;
  onSetDefault: (provider: Provider) => void;
  onTestConnection: (provider: Provider) => void;
  onAddModel: (providerId: string, data: ProviderModelCreate) => Promise<void>;
  onRemoveModel: (providerId: string, modelId: string) => Promise<void>;
  onToggleModel: (providerId: string, modelId: string, isEnabled: boolean) => Promise<void>;
  onTestModel: (providerId: string, modelId: string) => Promise<TestModelResponse>;
  isTesting: boolean;
  connectionResult: TestConnectionResponse | null;
  isDefault?: boolean;
}

const isVlmCategory = (category: string) => category === "vlm";

/** Inline status tag for provider title row */
function InlineStatusBadge({ result }: { result: TestConnectionResponse }) {
  const { t } = useTranslation(["common", "settings"]);
  if (result.status === "no_health_url") {
    return (
      <Tooltip title={t("settings:noHealthConfigured")}>
        <Tag color="warning" style={{ fontSize: 11 }}>{t("settings:noHealthUrl")}</Tag>
      </Tooltip>
    );
  }
  if (result.status === "no_models") {
    return (
      <Tooltip title={t("settings:noModelsConfigured")}>
        <Tag color="warning" style={{ fontSize: 11 }}>{t("settings:noModels")}</Tag>
      </Tooltip>
    );
  }
  // VLM with per-model results — show summary
  if (result.model_results && result.model_results.length > 0) {
    const okCount = result.model_results.filter(m => m.status === "ok").length;
    const total = result.model_results.length;
    return (
      <Tag color={okCount === total ? "success" : "error"} style={{ fontSize: 11 }}>
        {t("settings:modelsOk", { ok: okCount, total })}
      </Tag>
    );
  }
  // Simple healthy/unhealthy
  if (result.status === "healthy") {
    const ms = result.latency_ms != null ? ` ${result.latency_ms}ms` : "";
    return <Tag color="success" style={{ fontSize: 11 }}>{t("settings:healthy")}{ms}</Tag>;
  }
  return (
    <Tooltip title={result.error}>
      <Tag color="error" style={{ fontSize: 11 }}>{t("settings:unhealthy")}</Tag>
    </Tooltip>
  );
}

/** Detail block for VLM per-model results */
function VlmModelResults({ result }: { result: TestConnectionResponse }) {
  const { t } = useTranslation("common");
  if (!result.model_results || result.model_results.length === 0) return null;
  return (
    <div style={{ marginTop: 4, paddingLeft: 16 }}>
      {result.model_results.map((m) => (
        <span key={m.model_id} style={{ marginRight: 8 }}>
          {m.status === "ok" ? (
            <Tag
              icon={<CheckCircleOutlined />}
              color="success"
              style={{ fontSize: 11 }}
            >
              {m.display_name || m.model_id}
              {m.latency_ms != null ? ` ${m.latency_ms}ms` : ""}
            </Tag>
          ) : (
            <Tooltip title={m.error || t("statuses.failed")}>
              <Tag
                icon={<CloseCircleOutlined />}
                color="error"
                style={{ fontSize: 11 }}
              >
                {m.display_name || m.model_id}
              </Tag>
            </Tooltip>
          )}
        </span>
      ))}
    </div>
  );
}

export default function ProviderCard({
  provider,
  category,
  onEdit,
  onDelete,
  onSetDefault,
  onTestConnection,
  onAddModel,
  onRemoveModel,
  onToggleModel,
  onTestModel,
  isTesting,
  connectionResult,
  isDefault = provider.is_default,
}: ProviderCardProps) {
  const { t } = useTranslation(["common", "settings"]);
  const isSystem = provider.scope === "system";
  const [expanded, setExpanded] = useState(false);
  const [detailProvider, setDetailProvider] = useState<Provider | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newModelId, setNewModelId] = useState("");
  const [addingModel, setAddingModel] = useState(false);

  useEffect(() => {
    setExpanded(false);
    setDetailProvider(null);
    setAddModalOpen(false);
    setNewModelId("");
  }, [provider.id]);

  useEffect(() => {
    if (expanded && detailProvider === null) {
      setLoadingDetail(true);
      getProvider(provider.id)
        .then((data) => setDetailProvider(data))
        .finally(() => setLoadingDetail(false));
    }
  }, [expanded, detailProvider, provider.id]);

  const reloadDetail = async () => {
    const updated = await getProvider(provider.id);
    setDetailProvider(updated);
  };

  const handleToggleModel = async (modelId: string, isEnabled: boolean) => {
    await onToggleModel(provider.id, modelId, isEnabled);
    await reloadDetail();
  };

  const handleRemoveModel = async (modelId: string) => {
    await onRemoveModel(provider.id, modelId);
    await reloadDetail();
  };

  const handleAddModel = async () => {
    if (!newModelId.trim()) return;
    setAddingModel(true);
    try {
      await onAddModel(provider.id, {
        model_id: newModelId.trim(),
        display_name: newModelId.trim(),
      });
      setAddModalOpen(false);
      setNewModelId("");
      await reloadDetail();
    } finally {
      setAddingModel(false);
    }
  };

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      {/* Row 1 — Provider info + inline status badge */}
      <div style={{ marginBottom: 8 }}>
        <Space size={6} align="center" wrap>
          <span
            style={{
              color: provider.is_enabled ? "#52c41a" : "#d9d9d9",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            <svg width={10} height={10} viewBox="0 0 10 10"><circle cx={5} cy={5} r={4} fill={provider.is_enabled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1} /></svg>
          </span>
          <Typography.Text strong>{provider.name}</Typography.Text>
          {isSystem && <Tag>{t("settings:systemManaged")}</Tag>}
          {isDefault && <Tag color="blue">{t("settings:default")}</Tag>}
          {provider.auth_type === "api_key" && <Tag>{t("settings:apiKey")}</Tag>}
          {(() => {
            const DC = authTypeRegistry.getDisplayComponent(provider.auth_type);
            return DC ? <DC provider={provider} /> : null;
          })()}
          {isVlmCategory(category) && (
            <Typography.Text type="secondary">
              {t("settings:modelCount", { count: provider.models.length })}
            </Typography.Text>
          )}
          {/* Inline status badge — same row as title */}
          {connectionResult && <InlineStatusBadge result={connectionResult} />}
        </Space>
      </div>

      {/* Row 1.6 — VLM per-model detail results */}
      {connectionResult && isVlmCategory(category) && connectionResult.model_results && (
        <VlmModelResults result={connectionResult} />
      )}

      {/* Row 2 — Action buttons */}
      <div style={{ marginBottom: 8 }}>
        <Space size={4}>
          {!isSystem && <PermissionButton
            capability="provider.manage"
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(provider)}
          >
            {t("common:edit")}
          </PermissionButton>}
          <PermissionButton
            capability="provider.manage"
            type="text"
            size="small"
            icon={<ApiOutlined />}
            loading={isTesting}
            onClick={() => onTestConnection(provider)}
          >
            {t("settings:testConnection")}
          </PermissionButton>
          {!isSystem && <PermissionButton
            capability="provider.manage"
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
              Modal.confirm({
                title: t("settings:deleteProviderQuestion", { name: provider.name }),
                content: t("settings:deleteProviderConfirm"),
                okText: t("common:delete"),
                okType: "danger",
                cancelText: t("common:cancel"),
                onOk: () => onDelete(provider),
              });
            }}
          >
            {t("common:delete")}
          </PermissionButton>}
          {!isSystem && provider.is_enabled && !isDefault && <PermissionButton
            capability="provider.manage"
            type="text"
            size="small"
            onClick={() => onSetDefault(provider)}
          >
            {t("settings:setDefault")}
          </PermissionButton>}
          {isVlmCategory(category) && (
            <Button
              type="text"
              size="small"
              icon={<DownOutlined rotate={expanded ? 180 : 0} />}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? t("settings:hideModels") : t("settings:showModels")}
            </Button>
          )}
        </Space>
      </div>

      {/* Expandable model list — VLM only */}
      {isVlmCategory(category) && expanded && (
        <div style={{ marginTop: 12, paddingLeft: 8 }}>
          {loadingDetail ? (
            <Spin size="small" />
          ) : detailProvider && detailProvider.models.length > 0 ? (
            <>
              {isSystem ? (
                <Space direction="vertical" size={2}>
                  {detailProvider.models.map((model) => (
                    <Typography.Text key={model.id}>{model.display_name}</Typography.Text>
                  ))}
                </Space>
              ) : <ModelToggleList
                models={detailProvider.models}
                providerId={provider.id}
                onToggle={handleToggleModel}
                onRemoveModel={handleRemoveModel}
                onTestModel={onTestModel}
              />}
              {!isSystem && <PermissionButton
                capability="provider.manage"
                type="dashed"
                size="small"
                icon={<PlusOutlined />}
                style={{ marginTop: 8 }}
                onClick={() => setAddModalOpen(true)}
              >
                {t("settings:addModel")}
              </PermissionButton>}
            </>
          ) : (
            <>
              <Typography.Text type="secondary">
                {t("settings:noModelsConfiguredShort")}
              </Typography.Text>
              {!isSystem && <PermissionButton
                capability="provider.manage"
                type="dashed"
                size="small"
                icon={<PlusOutlined />}
                style={{ marginLeft: 8 }}
                onClick={() => setAddModalOpen(true)}
              >
                {t("settings:addModel")}
              </PermissionButton>}
            </>
          )}
        </div>
      )}

      {/* Add Model Modal */}
      {!isSystem && <Modal
        title={t("settings:addModel")}
        open={addModalOpen}
        onOk={handleAddModel}
        onCancel={() => { setAddModalOpen(false); setNewModelId(""); }}
        confirmLoading={addingModel}
        okText={t("settings:add")}
        okButtonProps={{ disabled: !newModelId.trim() }}
      >
        <Typography.Text type="secondary">
          {t("settings:enterDeployment")}
        </Typography.Text>
        <Input
          placeholder={t("settings:modelDeploymentPlaceholder")}
          value={newModelId}
          onChange={(e) => setNewModelId(e.target.value)}
          onPressEnter={handleAddModel}
          style={{ marginTop: 12 }}
          autoFocus
        />
      </Modal>}
    </Card>
  );
}
