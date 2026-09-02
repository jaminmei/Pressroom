import { Tag, Tooltip, Space } from "antd";
import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import type { TestConnectionResponse } from "@/types/provider";
import { useTranslation } from "react-i18next";

interface ConnectionStatusBadgeProps {
  result: TestConnectionResponse | null;
}

export default function ConnectionStatusBadge({
  result,
}: ConnectionStatusBadgeProps) {
  const { t } = useTranslation(["common", "settings"]);
  if (result === null) {
    return null;
  }

  if (result.status === "unavailable" && result.error_code === "PROVIDER_HEALTH_URL_MISSING") {
    return (
      <Tooltip title={t("settings:noHealthConfigured")}>
        <Tag color="warning">{t("settings:noHealthUrl")}</Tag>
      </Tooltip>
    );
  }

  if (result.status === "unavailable") {
    return (
      <Tooltip title={t("settings:noModelsConfigured")}>
        <Tag color="warning">{t("settings:noModels")}</Tag>
      </Tooltip>
    );
  }

  // VLM provider with per-model results
  if (result.model_results && result.model_results.length > 0) {
    const okCount = result.model_results.filter((m) => m.status === "ok").length;
    const failCount = result.model_results.length - okCount;

    return (
      <div style={{ marginTop: 4 }}>
        {/* Provider-level summary */}
        <Space size={4} wrap>
          <Tag color={failCount === 0 ? "success" : "error"}>
            {t("settings:modelsOk", { ok: okCount, total: result.model_results.length })}
          </Tag>
          {result.latency_ms != null && (
            <Tag>{result.latency_ms}ms</Tag>
          )}
        </Space>
        {/* Per-model results */}
        <div style={{ marginTop: 4, paddingLeft: 8 }}>
          {result.model_results.map((m) => (
            <div key={m.model_id} style={{ marginBottom: 2 }}>
              <Space size={4}>
                {m.status === "ok" ? (
                  <Tag
                    icon={<CheckCircleOutlined />}
                    color="success"
                    style={{ fontSize: 11 }}
                  >
                    {m.display_name || m.model_id}
                    {m.latency_ms != null ? ` (${m.latency_ms}ms)` : ""}
                  </Tag>
                ) : (
                  <Tooltip title={m.error || t("common:statuses.failed")}>
                    <Tag
                      icon={<CloseCircleOutlined />}
                      color="error"
                      style={{ fontSize: 11 }}
                    >
                      {m.display_name || m.model_id}
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // engine_service provider (simple healthy/unhealthy)
  if (result.status === "healthy") {
    const latencyLabel =
      result.latency_ms != null ? ` (${result.latency_ms}ms)` : "";
    return <Tag color="success">{t("settings:healthy")}{latencyLabel}</Tag>;
  }

  return (
    <Tooltip title={result.error}>
      <Tag color="error">{t("settings:unhealthy")}</Tag>
    </Tooltip>
  );
}
