import { PlusOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Empty, Form, Input } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import type { UseWorkflowApiAccessResult } from "@/features/api-access/hooks/useWorkflowApiAccess";
import type { ApiKeyRecord, IssueApiKeyResponse } from "@/services/apiAccessApi";
import { usePermission } from "@/hooks/usePermission";
import { useWorkspaceStore } from "@/stores/workspaceStore";

import ApiKeyCreatedModal from "./ApiKeyCreatedModal";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

function formatDate(v: string | null | undefined, language: "en" | "zh-TW"): string {
  return v ? formatDateTime(v, language, { dateStyle: "medium" }) : "—";
}

function formatLastUsed(v: string | null | undefined, language: "en" | "zh-TW", never: string): string {
  return v ? formatDateTime(v, language, { dateStyle: "medium", timeStyle: "short" }) : never;
}

interface Props {
  access: UseWorkflowApiAccessResult;
  workflowId: string;
}

export default function ApiKeyManagerCard({ access, workflowId }: Props) {
  const { t } = useTranslation(["common", "apiAccess"]);
  const { language } = useLanguage();
  const { message, modal } = AntApp.useApp();
  const [form] = Form.useForm<{ description: string }>();
  const [createdKey, setCreatedKey] = useState<IssueApiKeyResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const { can, role } = usePermission();
  const canManage = role === null || can("api_key.manage");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id);

  useEffect(() => {
    setCreatedKey(null);
  }, [workflowId, workspaceId]);

  const { keys, page, total, limit, setPage } = access;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const safeKeys = keys ?? [];
  const activeKeys = safeKeys.filter((key) => key.is_active);

  const handleGenerate = async () => {
    if (!canManage) return;
    const description = form.getFieldValue("description") as string | undefined;
    const trimmed = description?.trim();
    setGenerating(true);
    try {
      const response = await access.actions.issueKey({
        workflow_id: workflowId,
        description: trimmed ? trimmed : null,
      });
      setCreatedKey(response);
      form.resetFields();
      message.success(t("apiAccess:keyGenerated"));
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : t("apiAccess:generateFailed"));
    } finally {
      setGenerating(false);
    }
  };

  const handleRevoke = (record: ApiKeyRecord) => {
    if (!canManage) return;
    modal.confirm({
      title: t("apiAccess:revokeTitle"),
      content: t("apiAccess:revokeConfirm", { prefix: record.key_prefix }),
      okText: t("apiAccess:revoke"),
      okButtonProps: { danger: true },
      cancelText: t("common:cancel"),
      onOk: async () => {
        try {
          await access.actions.revokeKey(record.id);
          message.success(t("apiAccess:keyRevoked"));
        } catch (err: unknown) {
          message.error(err instanceof Error ? err.message : t("apiAccess:revokeFailed"));
        }
      },
    });
  };

  return (
    <Card data-testid="api-key-manager-card" id="api-keys">
      <div className="panel-head">
        <div>
          <h2>{t("apiAccess:generateTitle")}</h2>
          <p className="mini-muted">{t("apiAccess:generateDescription")}</p>
        </div>
      </div>

      <Form
        form={form}
        layout="vertical"
        className="api-generate-form"
        onSubmitCapture={(e) => {
          e.preventDefault();
          if (canManage) void handleGenerate();
        }}
      >
        <Form.Item name="description" label={t("apiAccess:keyName")}>
          <Input placeholder={t("apiAccess:keyDescription")} />
        </Form.Item>
        <PermissionButton capability="api_key.manage" htmlType="submit" icon={<PlusOutlined />} loading={generating} type="primary">
          {t("apiAccess:generate")}
        </PermissionButton>
      </Form>

      <div className="panel-head" style={{ marginTop: 4 }}>
        <div>
          <h2>{t("apiAccess:apiKeys")}</h2>
          <p className="mini-muted">{t("apiAccess:keyScopeDescription")}</p>
        </div>
      </div>

      {activeKeys.length === 0 ? (
        <Empty description={t("apiAccess:noActiveKeys")} />
      ) : (
        <>
          <div className="key-list">
            {activeKeys.map((key) => (
              <div key={key.id} className="api-key-row">
                <div className="api-key-main">
                  <div>
                    <div className="api-key-name">{key.description?.trim() || t("apiAccess:untitledKey")}</div>
                    <div className="api-key-secret"><code>{key.key_prefix}</code></div>
                  </div>
                  <span className="tag tag-success">{t("apiAccess:active")}</span>
                  <PermissionButton capability="api_key.manage" danger size="small" onClick={() => handleRevoke(key)}>{t("apiAccess:revoke")}</PermissionButton>
                </div>
                <div className="api-key-meta">
                  <span>{t("apiAccess:scope", { scope: workflowId })}</span>
                  <span>{t("apiAccess:createdValue", { value: formatDate(key.created_at, language) })}</span>
                  <span>{t("apiAccess:lastUsedValue", { value: formatLastUsed(key.last_used_at, language, t("common:never")) })}</span>
                </div>
              </div>
            ))}
          </div>
          {total > limit && (
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <Button
                data-testid="pagination-prev"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                {t("apiAccess:previous")}
              </Button>
              <span data-testid="pagination-info">
                {t("apiAccess:pageSummary", { page, totalPages, total })}
              </span>
              <Button
                data-testid="pagination-next"
                disabled={page * limit >= total}
                onClick={() => setPage(page + 1)}
              >
                {t("common:next")}
              </Button>
            </div>
          )}
        </>
      )}

      <ApiKeyCreatedModal open={createdKey !== null} apiKey={createdKey} onClose={() => setCreatedKey(null)} />
    </Card>
  );
}
