import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Empty, Result, Spin, Typography, message, notification } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import type { Provider, TestConnectionResponse, TestModelResponse } from "@/types/provider";
import type { ProviderModelCreate } from "@/types/provider";
import {
  listProviders,
  deleteProvider,
  testConnection,
  addModel,
  removeModel,
  toggleModel,
  testModel,
  setDefaultProvider,
  getDefaultProvider,
} from "@/services/providerApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

import ProviderCard from "./ProviderCard";
import AddProviderDialog from "./AddProviderDialog";

export interface ProviderSettingsContentProps {
  /**
   * Removes the full-page positioning used by the legacy settings route so
   * the provider manager can be composed inside Workspace Settings.
   */
  embedded?: boolean;
  title?: string;
  description?: string;
}

export function ProviderSettingsContent({
  embedded = false,
  title,
  description,
}: ProviderSettingsContentProps) {
  const { t } = useTranslation(["common", "settings"]);
  const resolvedTitle = title ?? t("settings:modelProviders");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());
  const [connectionResults, setConnectionResults] = useState<
    Record<string, TestConnectionResponse | null>
  >({});
  const [effectiveDefaultIds, setEffectiveDefaultIds] = useState<Set<string>>(new Set());
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);

  const loadProviders = useCallback(async () => {
    const requestGeneration = contextGeneration;
    try {
      setLoading(true);
      setError(null);
      const data = await listProviders();
      const categories = Array.from(new Set(data.map((provider) => provider.engine_category)));
      const defaults = await Promise.all(categories.map((category) => getDefaultProvider(category)));
      if (useWorkspaceStore.getState().contextGeneration !== requestGeneration) return;
      setProviders(data);
      setEffectiveDefaultIds(new Set(defaults.flatMap((provider) => provider ? [provider.id] : [])));
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("settings:loadProvidersFailed");
      setError(msg);
      notification.error({
        message: t("settings:error"),
        description: msg,
      });
    } finally {
      if (useWorkspaceStore.getState().contextGeneration === requestGeneration) {
        setLoading(false);
      }
    }
  }, [contextGeneration, t]);

  useEffect(() => {
    setProviders([]);
    setDialogOpen(false);
    setEditingProvider(null);
    setTestingIds(new Set());
    setConnectionResults({});
    setEffectiveDefaultIds(new Set());
    void loadProviders();
  }, [loadProviders]);

  const handleAddProvider = () => {
    setEditingProvider(null);
    setDialogOpen(true);
  };

  const handleEditProvider = (provider: Provider) => {
    if (provider.scope === "system") return;
    setEditingProvider(provider);
    setDialogOpen(true);
  };

  const handleDeleteProvider = async (provider: Provider) => {
    if (provider.scope === "system") return;
    try {
      await deleteProvider(provider.id);
      message.success(t("settings:providerDeleted", { name: provider.name }));
      loadProviders();
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("settings:deleteProviderFailed");
      notification.error({
        message: t("settings:deleteFailed"),
        description: msg,
      });
    }
  };

  const handleSetDefaultProvider = async (provider: Provider) => {
    if (provider.scope === "system") return;
    try {
      await setDefaultProvider(provider.id);
      message.success(t("settings:providerDefaulted", { name: provider.name }));
      void loadProviders();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("settings:setDefaultFailed");
      notification.error({
        message: t("settings:setDefaultFailedTitle"),
        description: msg,
      });
    }
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
      const msg =
        err instanceof Error ? err.message : t("settings:connectionFailed");
      notification.error({
        message: t("settings:connectionFailedTitle"),
        description: msg,
      });
      setConnectionResults((prev) => ({
        ...prev,
        [provider.id]: {
          status: "unhealthy",
          latency_ms: null,
          error: msg,
          details: null,
          model_results: null,
        },
      }));
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(provider.id);
        return next;
      });
    }
  };

  const handleAddModel = async (providerId: string, data: ProviderModelCreate) => {
    if (providers.find((provider) => provider.id === providerId)?.scope === "system") return;
    await addModel(providerId, data);
    loadProviders();
  };

  const handleRemoveModel = async (providerId: string, modelId: string) => {
    if (providers.find((provider) => provider.id === providerId)?.scope === "system") return;
    await removeModel(providerId, modelId);
    loadProviders();
  };

  const handleDialogSuccess = () => {
    setDialogOpen(false);
    loadProviders();
  };

  const handleToggleModel = async (
    providerId: string,
    modelId: string,
    isEnabled: boolean,
  ): Promise<void> => {
    if (providers.find((provider) => provider.id === providerId)?.scope === "system") return;
    try {
      await toggleModel(providerId, modelId, isEnabled);
      message.success(t(isEnabled ? "settings:modelEnabled" : "settings:modelDisabled"));
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("settings:toggleModelFailed");
      notification.error({
        message: t("settings:toggleFailed"),
        description: msg,
      });
    }
  };

  const handleTestModel = async (
    providerId: string,
    modelId: string,
  ): Promise<TestModelResponse> => {
    return testModel(providerId, modelId);
  };

  return (
    <section
      className={`provider-settings-surface${embedded ? " is-embedded" : ""}`}
      data-testid={embedded ? "workspace-provider-settings" : "provider-settings"}
    >
      <div className="provider-settings-header">
        <div className="provider-settings-heading">
          <Typography.Title level={embedded ? 4 : 3} style={{ margin: 0 }}>
            {resolvedTitle}
          </Typography.Title>
          {description ? (
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {description}
            </Typography.Paragraph>
          ) : null}
        </div>
        <PermissionButton capability="provider.manage" type="primary" icon={<PlusOutlined />} onClick={handleAddProvider}>
          {t("settings:addProviderShort")}
        </PermissionButton>
      </div>

      <Alert
        data-testid="provider-private-network-warning"
        type="warning"
        showIcon
        message={t("settings:privateProviderWarningTitle")}
        description={t("settings:privateProviderWarningDescription")}
      />

      <div className="provider-settings-panel" aria-busy={loading}>
        {loading ? (
          <div className="provider-settings-state" data-testid="provider-settings-loading">
            <Spin size="large" />
          </div>
        ) : error ? (
          <div className="provider-settings-state">
            <Result
              status="error"
              title={t("settings:failedLoadProviders")}
              subTitle={error}
              extra={<Button onClick={loadProviders}>{t("common:retry")}</Button>}
            />
          </div>
        ) : providers.length === 0 ? (
          <div className="provider-settings-state">
            <Empty
              description={
                embedded
                  ? t("settings:noWorkspaceProviders")
                  : t("settings:noSystemProviders")
              }
            />
          </div>
        ) : (
          <div className="provider-settings-list">
            {(["workspace", "system"] as const).map((scope) => {
              const scopedProviders = providers.filter((provider) => (provider.scope ?? "workspace") === scope);
              if (scopedProviders.length === 0) return null;
              return <section key={scope} aria-labelledby={`${scope}-providers-heading`}>
                <Typography.Title id={`${scope}-providers-heading`} level={5}>
                  {scope === "workspace" ? t("settings:workspaceProviders") : t("settings:systemProviders")}
                </Typography.Title>
                {scopedProviders.map((provider) => (
                  <ProviderCard
                    key={provider.id}
                    provider={provider}
                    category={provider.engine_category}
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
                    isDefault={effectiveDefaultIds.has(provider.id)}
                  />
                ))}
              </section>;
            })}
          </div>
        )}
      </div>

      {/* Add/Edit Dialog */}
      <AddProviderDialog
        open={dialogOpen}
        provider={editingProvider}
        onCancel={() => setDialogOpen(false)}
        onSuccess={handleDialogSuccess}
      />
    </section>
  );
}

export default function ProviderSettingsPage() {
  return <ProviderSettingsContent />;
}
