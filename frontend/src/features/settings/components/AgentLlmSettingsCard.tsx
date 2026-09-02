import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, List, Space, Spin, Tag, Typography } from "antd";
import { MessageOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { listProviders } from "@/services/providerApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { Provider } from "@/types/provider";

import AddProviderDialog from "./AddProviderDialog";

function providerModelLabel(provider: Provider, missingLabel: string): string {
  if (provider.model_display_name) {
    if (provider.model_id && provider.model_display_name !== provider.model_id) {
      return `${provider.model_display_name} (${provider.model_id})`;
    }
    return provider.model_display_name;
  }
  return provider.model_id ?? missingLabel;
}

export default function AgentLlmSettingsCard() {
  const { t } = useTranslation("settings");
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);

  const loadAgentProviders = useCallback(async () => {
    const requestGeneration = contextGeneration;
    setLoading(true);
    setError(null);
    try {
      const visibleProviders = await listProviders({ provider_type: "llm_api" });
      if (useWorkspaceStore.getState().contextGeneration !== requestGeneration) return;
      setProviders(visibleProviders);
    } catch (loadError: unknown) {
      if (useWorkspaceStore.getState().contextGeneration !== requestGeneration) return;
      setError(loadError instanceof Error ? loadError.message : t("agentLlmLoadFailed"));
    } finally {
      if (useWorkspaceStore.getState().contextGeneration === requestGeneration) setLoading(false);
    }
  }, [contextGeneration, t]);

  useEffect(() => {
    setProviders([]);
    setDialogOpen(false);
    setEditingProvider(null);
    void loadAgentProviders();
  }, [loadAgentProviders]);

  const openNewProvider = () => {
    setEditingProvider(null);
    setDialogOpen(true);
  };
  const defaultProvider = providers.find((provider) => provider.is_chatbot_default) ?? null;
  const renderProviderContent = () => {
    if (loading) return <Spin size="small" />;
    if (error) {
      return (
        <Alert
          action={<Button onClick={() => void loadAgentProviders()}>{t("agentLlmRetry")}</Button>}
          description={error}
          message={t("agentLlmLoadFailed")}
          showIcon
          type="error"
        />
      );
    }
    if (providers.length === 0) {
      return (
        <Alert
          description={t("agentLlmEmptyDescription")}
          message={t("agentLlmEmptyTitle")}
          showIcon
          type="warning"
        />
      );
    }
    return (
      <>
        {defaultProvider === null ? (
          <Alert message={t("agentLlmNoDefaultTitle")} description={t("agentLlmNoDefaultDescription")} showIcon style={{ marginBottom: 12 }} type="warning" />
        ) : null}
        <List
          dataSource={providers}
          renderItem={(provider) => {
            const modelLabel = providerModelLabel(provider, t("agentLlmModelMissing"));
            return (
              <List.Item actions={[
                <PermissionButton capability="provider.manage" key="edit" onClick={() => { setEditingProvider(provider); setDialogOpen(true); }} size="small">
                  {t("agentLlmEdit")}
                </PermissionButton>,
              ]}>
                <List.Item.Meta
                  title={<Space wrap><span>{provider.name}</span>{provider.is_chatbot_default ? <Tag color="purple">{t("agentLlmDefault")}</Tag> : null}{provider.chatbot_ready ? <Tag color="green">{t("agentLlmReady")}</Tag> : <Tag>{t("agentLlmNotReady")}</Tag>}</Space>}
                  description={`${modelLabel} · ${provider.api_protocol ?? t("agentLlmProtocolMissing")}`}
                />
              </List.Item>
            );
          }}
        />
      </>
    );
  };

  return (
    <Card data-testid="agent-llm-settings" id="agent-llm-settings" style={{ marginBottom: 16 }}>
      <div style={{ alignItems: "flex-start", display: "flex", gap: 16, justifyContent: "space-between" }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <MessageOutlined style={{ marginRight: 8 }} />
            {t("agentLlmTitle")}
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: "6px 0 16px" }}>
            {t("agentLlmDescription")}
          </Typography.Paragraph>
        </div>
        <PermissionButton capability="provider.manage" icon={<PlusOutlined />} onClick={openNewProvider} type="primary">
          {t("configureAgentLlm")}
        </PermissionButton>
      </div>

      {renderProviderContent()}

      <AddProviderDialog
        defaultCategory="llm"
        defaultChatbotDefault
        defaultProviderType="llm_api"
        onCancel={() => setDialogOpen(false)}
        onSuccess={() => { setDialogOpen(false); void loadAgentProviders(); }}
        open={dialogOpen}
        provider={editingProvider}
      />
    </Card>
  );
}
