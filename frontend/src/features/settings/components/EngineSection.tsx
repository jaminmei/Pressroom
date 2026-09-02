import { createElement, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, Collapse, Space, Spin, Tag, Typography, message, notification } from "antd";
import {
  PlusOutlined,
  HeartOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";

import { getEngineIcon } from "@/components/Icons/IconRegistry";
import type { EngineWithProviders } from "@/types/engine";
import type { Provider, TestConnectionResponse, TestModelResponse, ProviderModelCreate } from "@/types/provider";
import { listProviders, deleteProvider, setDefaultProvider, testConnection, addModel, removeModel, toggleModel, testModel } from "@/services/providerApi";
import { PermissionButton } from "@/components/Permissions/PermissionButton";

import ProviderCard from "./ProviderCard";
import AddProviderDialog from "./AddProviderDialog";

interface EngineSectionProps {
  engine: EngineWithProviders;
}

const isVlmCategory = (category: string) => category === "vlm";

export default function EngineSection({ engine }: EngineSectionProps) {
  const { t } = useTranslation("settings");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());
  const [connectionResults, setConnectionResults] = useState<Record<string, TestConnectionResponse | null>>({});
  const [checkingHealth, setCheckingHealth] = useState(false);

  const loadProviders = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listProviders({ category: engine.category });
      setProviders(data);
      setLoaded(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("loadProvidersFailed");
      notification.error({ message: t("error"), description: msg });
    } finally {
      setLoading(false);
    }
  }, [engine.category, t]);

  const handleExpand = (keys: string | string[]) => {
    if (Array.isArray(keys) ? keys.includes(engine.category) : keys === engine.category) {
      if (!loaded) loadProviders();
    }
  };

  const handleAddProvider = () => {
    setEditingProvider(null);
    setDialogOpen(true);
  };

  const handleEditProvider = (provider: Provider) => {
    setEditingProvider(provider);
    setDialogOpen(true);
  };

  const handleDeleteProvider = async (provider: Provider) => {
    try {
      await deleteProvider(provider.id);
      message.success(t("providerDeleted", { name: provider.name }));
      loadProviders();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("deleteProviderFailed");
      notification.error({ message: t("deleteFailed"), description: msg });
    }
  };

  const handleSetDefaultProvider = async (provider: Provider) => {
    await setDefaultProvider(provider.id);
    loadProviders();
  };

  const handleTestConnection = async (provider: Provider) => {
    setTestingIds((prev) => new Set(prev).add(provider.id));
    // Clear previous result before testing
    setConnectionResults((prev) => {
      const next = { ...prev };
      delete next[provider.id];
      return next;
    });
    try {
      const result = await testConnection(provider.id);
      setConnectionResults((prev) => ({ ...prev, [provider.id]: result }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("connectionFailed");
      setConnectionResults((prev) => ({
        ...prev,
        [provider.id]: { status: "unhealthy", latency_ms: null, error: msg, details: null, model_results: null },
      }));
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(provider.id);
        return next;
      });
    }
  };

  const handleCheckAllHealth = async () => {
    if (!loaded) await loadProviders();
    // Re-read current providers
    const currentProviders = await listProviders({ category: engine.category });
    // Clear all previous results before testing
    setConnectionResults({});
    setCheckingHealth(true);
    try {
      const results = await Promise.allSettled(
        currentProviders.map(p => testConnection(p.id)),
      );
      const resultMap: Record<string, TestConnectionResponse | null> = {};
      currentProviders.forEach((p, i) => {
        const r = results[i];
        if (r.status === "fulfilled") resultMap[p.id] = r.value;
        else resultMap[p.id] = { status: "unhealthy", latency_ms: null, error: r.reason?.message || t("unknownError"), details: null, model_results: null };
      });
      setConnectionResults(resultMap);
    } finally {
      setCheckingHealth(false);
    }
  };

  const handleAddModel = async (providerId: string, data: ProviderModelCreate) => {
    await addModel(providerId, data);
    loadProviders();
  };

  const handleRemoveModel = async (providerId: string, modelId: string) => {
    await removeModel(providerId, modelId);
    loadProviders();
  };

  const handleToggleModel = async (providerId: string, modelId: string, isEnabled: boolean) => {
    try {
      await toggleModel(providerId, modelId, isEnabled);
      message.success(t(isEnabled ? "modelEnabled" : "modelDisabled"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("toggleModelFailed");
      notification.error({ message: t("toggleFailed"), description: msg });
    }
  };

  const handleTestModel = async (providerId: string, modelId: string): Promise<TestModelResponse> => {
    return testModel(providerId, modelId);
  };

  const handleDialogSuccess = () => {
    setDialogOpen(false);
    loadProviders();
  };

  // Health badge for section header (from batch test connection results)
  const healthResults = Object.values(connectionResults).filter(
    (r): r is TestConnectionResponse => r !== null,
  );

  const healthBadge = (() => {
    if (healthResults.length === 0) return null;

    if (isVlmCategory(engine.category)) {
      // VLM: aggregate providers + models
      const providerOk = healthResults.filter(h => h.status === "healthy").length;
      const totalProviders = healthResults.length;
      let totalModels = 0;
      let modelsOk = 0;
      for (const r of healthResults) {
        if (r.model_results) {
          totalModels += r.model_results.length;
          modelsOk += r.model_results.filter(m => m.status === "ok").length;
        }
      }
      if (totalModels > 0) {
        const allOk = modelsOk === totalModels;
        return (
          <Tag
            icon={allOk ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            color={allOk ? "success" : "error"}
          >
            {t("providersAndModelsOk", {
              providersOk: providerOk,
              providersTotal: totalProviders,
              modelsOk,
              modelsTotal: totalModels
            })}
          </Tag>
        );
      }
      // No model results — show provider-level only
      const allHealthy = providerOk === totalProviders;
      return (
        <Tag
          icon={allHealthy ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          color={allHealthy ? "success" : "error"}
        >
          {t("providersOk", { ok: providerOk, total: totalProviders })}
        </Tag>
      );
    }

    // Non-VLM: simple provider-level count
    const healthyCount = healthResults.filter(h => h.status === "healthy").length;
    const noUrlCount = healthResults.filter(
      h => h.status === "unavailable" && h.error_code === "PROVIDER_HEALTH_URL_MISSING",
    ).length;
    const totalChecked = healthResults.length;
    if (healthyCount === totalChecked) {
      return <Tag icon={<CheckCircleOutlined />} color="success">{healthyCount}/{totalChecked}</Tag>;
    }
    if (healthyCount + noUrlCount === totalChecked && healthyCount < totalChecked) {
      return <Tag icon={<QuestionCircleOutlined />} color="warning">{healthyCount}/{totalChecked}</Tag>;
    }
    return <Tag icon={<CloseCircleOutlined />} color="error">{healthyCount}/{totalChecked}</Tag>;
  })();

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Collapse
        ghost
        activeKey={undefined}
        onChange={handleExpand}
        items={[
          {
            key: engine.category,
            label: (
              <Space size={8} align="center">
                <span style={{ fontSize: 18, display: "inline-flex" }}>{createElement(getEngineIcon(engine.category), { size: 22 })}</span>
                <Typography.Text strong>{engine.display_name}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  ({t("providerCount", { count: engine.provider_count })})
                </Typography.Text>
                {healthBadge}
              </Space>
            ),
            extra: (
              <Space size={4} onClick={(e) => e.stopPropagation()}>
                <PermissionButton
                  capability="provider.manage"
                  type="text"
                  size="small"
                  icon={<HeartOutlined />}
                  loading={checkingHealth}
                  onClick={handleCheckAllHealth}
                >
                  {t("checkHealth")}
                </PermissionButton>
                <PermissionButton
                  capability="provider.manage"
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={handleAddProvider}
                >
                  {t("addProviderShort")}
                </PermissionButton>
              </Space>
            ),
            children: loading ? (
              <Spin size="small" />
            ) : providers.length === 0 ? (
              <Typography.Text type="secondary">
                {t("noProvidersForEngine", { engine: engine.display_name })}
              </Typography.Text>
            ) : (
              providers.map((provider) => (
                <ProviderCard
                  key={provider.id}
                  provider={provider}
                  category={engine.category}
                  onEdit={handleEditProvider}
                  onDelete={handleDeleteProvider}
                  onSetDefault={handleSetDefaultProvider}
                  onTestConnection={handleTestConnection}
                  onAddModel={handleAddModel}
                  onRemoveModel={handleRemoveModel}
                  onToggleModel={handleToggleModel}
                  onTestModel={handleTestModel}
                  isTesting={testingIds.has(provider.id)}
                  connectionResult={connectionResults[provider.id] ?? null}
                />
              ))
            ),
          },
        ]}
      />

      <AddProviderDialog
        open={dialogOpen}
        provider={editingProvider}
        onCancel={() => setDialogOpen(false)}
        onSuccess={handleDialogSuccess}
        defaultCategory={engine.category}
        defaultProviderType={engine.default_provider_type}
      />
    </Card>
  );
}
