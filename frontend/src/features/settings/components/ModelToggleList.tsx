import { useState } from "react";
import { useTranslation } from "react-i18next";
import { List, Modal, Spin, Switch, Tag, Tooltip, Typography, message } from "antd";
import { DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons";
import type { ProviderModel, TestModelResponse } from "@/types/provider";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";

interface ModelToggleListProps {
  models: ProviderModel[];
  providerId: string;
  onToggle: (modelId: string, isEnabled: boolean) => Promise<void>;
  onRemoveModel?: (modelId: string) => Promise<void>;
  onTestModel?: (providerId: string, modelId: string) => Promise<TestModelResponse>;
}

export default function ModelToggleList({
  models,
  providerId,
  onToggle,
  onRemoveModel,
  onTestModel,
}: ModelToggleListProps) {
  const { t } = useTranslation(["common", "settings"]);
  const { can, explain } = usePermission();
  const canManage = can("provider.manage");
  const manageReason = explain("provider.manage").reason || t("settings:noPermission");
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [testResults, setTestResults] = useState<Record<string, TestModelResponse>>({});
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set());

  // Sort by sort_order
  const sorted = [...models].sort((a, b) => a.sort_order - b.sort_order);

  const handleToggle = async (
    model: ProviderModel,
    newEnabled: boolean,
  ) => {
    setLoadingIds((prev) => {
      const next = new Set(prev);
      next.add(model.id);
      return next;
    });

    try {
      await onToggle(model.id, newEnabled);
    } catch {
      message.error(t("settings:updateModelFailed", { name: model.display_name }));
    } finally {
      setLoadingIds((prev) => {
        const next = new Set(prev);
        next.delete(model.id);
        return next;
      });
    }
  };

  const handleRemove = (model: ProviderModel) => {
    Modal.confirm({
      title: t("settings:removeModelQuestion", { name: model.display_name }),
      content: t("settings:removeModelConfirm"),
      okText: t("common:remove"),
      okType: "danger",
      cancelText: t("common:cancel"),
      onOk: () => onRemoveModel?.(model.id),
    });
  };

  const handleTest = async (model: ProviderModel) => {
    if (!onTestModel) return;
    setTestingIds((prev) => {
      const next = new Set(prev);
      next.add(model.id);
      return next;
    });
    // Clear previous result
    setTestResults((prev) => {
      const next = { ...prev };
      delete next[model.id];
      return next;
    });

    try {
      const result = await onTestModel(providerId, model.id);
      setTestResults((prev) => ({ ...prev, [model.id]: result }));
    } catch {
      message.error(t("settings:testModelFailed", { name: model.display_name }));
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(model.id);
        return next;
      });
    }
  };

  return (
    <List
      split={true}
      dataSource={sorted}
      renderItem={(model) => {
        const testResult = testResults[model.id];
        return (
          <List.Item
            style={{ padding: "8px 0" }}
            actions={[
              testingIds.has(model.id) ? (
                <Spin key="test-spin" size="small" />
              ) : onTestModel ? (
                <PermissionButton
                  capability="provider.manage"
                  key="test"
                  type="text"
                  size="small"
                  icon={<ThunderboltOutlined />}
                  onClick={() => handleTest(model)}
                >
                  {t("settings:test")}
                </PermissionButton>
              ) : null,
              loadingIds.has(model.id) ? (
                <Spin key="spin" size="small" />
              ) : null,
              <Tooltip key="toggle-tooltip" title={canManage ? undefined : manageReason}>
                <span>
                  <Switch
                    key="toggle"
                    size="small"
                    checked={model.is_enabled}
                    disabled={!canManage}
                    onChange={(checked) => handleToggle(model, checked)}
                  />
                </span>
              </Tooltip>,
              onRemoveModel ? (
                <PermissionButton
                  capability="provider.manage"
                  key="delete"
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleRemove(model)}
                />
              ) : null,
            ]}
          >
            <List.Item.Meta
              title={
                <span>
                  <Typography.Text>{model.display_name}</Typography.Text>
                  {testResult && (
                    <Tag
                      color={testResult.status === "ok" ? "success" : "error"}
                      style={{ marginLeft: 8 }}
                    >
                      {testResult.status === "ok"
                        ? `${testResult.latency_ms}ms`
                        : t("common:statuses.failed")}
                    </Tag>
                  )}
                </span>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}
