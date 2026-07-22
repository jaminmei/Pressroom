import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Progress, Segmented, Select, Spin, Table, Tag } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { usePermission } from "@/hooks/usePermission";
import {
  type ApiKeyRecord,
  type ApiUsageRange,
  type ApiUsageRun,
  type ApiUsageSummary,
  getWorkflowApiUsageSummary,
  listWorkflowApiUsageRuns,
} from "@/services/apiAccessApi";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

interface Props {
  workflowId: string;
  keys: ApiKeyRecord[];
}

const RANGE_OPTIONS: Array<{ label: string; value: ApiUsageRange }> = [
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

function formatMs(value?: number | null): string {
  if (!value) return "0 ms";
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${value} ms`;
}

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MiB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${value} B`;
}

function formatDate(value: string | null | undefined, language: "en" | "zh-TW"): string {
  if (!value) return "—";
  return formatDateTime(value, language, { dateStyle: "medium", timeStyle: "short" });
}

function statusColor(value: string): string {
  if (value === "succeeded" || value === "completed" || value === "partial_completed") return "success";
  if (value === "failed" || value === "error" || value === "timeout") return "error";
  if (value === "rejected") return "warning";
  return "default";
}

function inputSummary(metadata?: Record<string, unknown> | null): string {
  const file = metadata?.file;
  if (file && typeof file === "object") {
    const fileMeta = file as Record<string, unknown>;
    const name = typeof fileMeta.filename === "string" ? fileMeta.filename : "file";
    const size = typeof fileMeta.size_bytes === "number" ? ` · ${formatBytes(fileMeta.size_bytes)}` : "";
    const source = typeof fileMeta.source_kind === "string" ? fileMeta.source_kind : "input";
    return `${source}: ${name}${size}`;
  }
  const keys = metadata?.input_keys;
  if (Array.isArray(keys) && keys.length > 0) return `inputs: ${keys.join(", ")}`;
  return "—";
}

function errorSummary(error?: Record<string, unknown> | null): string | null {
  if (!error) return null;
  const code = typeof error.code === "string" ? error.code : "ERROR";
  const message = typeof error.message === "string" ? error.message : "";
  return message ? `${code}: ${message}` : code;
}

function ApiMetric({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <article className="api-metric-card">
      <div className="api-metric-label">{label}</div>
      <div className="api-metric-value">{value}</div>
      <div className="api-metric-note">{note}</div>
    </article>
  );
}

function UsageTrend({ summary, language }: { summary: ApiUsageSummary; language: "en" | "zh-TW" }) {
  const maxCalls = Math.max(1, ...summary.trend.map((item) => item.calls));
  return (
    <div className="api-usage-trend" data-testid="api-usage-trend">
      {summary.trend.map((item) => {
        const height = Math.max(8, Math.round((item.calls / maxCalls) * 72));
        return (
          <div className="api-usage-trend-item" key={item.date}>
            <div className="api-usage-trend-bars">
              <span
                className="api-usage-trend-bar"
                style={{ height }}
                title={`${item.date}: ${item.calls} calls`}
              />
              {item.failures > 0 ? (
                <span
                  className="api-usage-trend-bar api-usage-trend-bar-error"
                  style={{ height: Math.max(6, Math.round((item.failures / maxCalls) * 72)) }}
                  title={`${item.failures} failures`}
                />
              ) : null}
            </div>
            <span className="api-usage-trend-label">
              {formatDateTime(`${item.date}T00:00:00`, language, { month: "short", day: "numeric" })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function ApiUsageTab({ workflowId, keys }: Props) {
  const { t } = useTranslation(["common", "apiAccess", "settings"]);
  const { language } = useLanguage();
  const navigate = useNavigate();
  const { can, role } = usePermission();
  const canViewUsage = role === null || can("api_usage.view");
  const [range, setRange] = useState<ApiUsageRange>("7d");
  const [status, setStatus] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [keyId, setKeyId] = useState("");
  const [page, setPage] = useState(1);
  const [limit] = useState(20);
  const [summary, setSummary] = useState<ApiUsageSummary | null>(null);
  const [runs, setRuns] = useState<ApiUsageRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!canViewUsage) return;
    setLoading(true);
    setError(null);
    try {
      const [nextSummary, nextRuns] = await Promise.all([
        getWorkflowApiUsageSummary(workflowId, range),
        listWorkflowApiUsageRuns({
          workflowId,
          range,
          status,
          endpoint,
          keyId,
          page,
          limit,
        }),
      ]);
      setSummary(nextSummary);
      setRuns(nextRuns.data);
      setTotal(nextRuns.meta.total);
    } catch {
      setError(t("apiAccess:loadUsageFailed"));
      setSummary(null);
      setRuns([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [canViewUsage, endpoint, keyId, limit, page, range, status, t, workflowId]);

  useEffect(() => {
    void load();
  }, [load]);

  const keyOptions = useMemo(
    () => [
      { label: t("apiAccess:allKeys"), value: "" },
      ...keys.map((key) => ({
        label: key.description?.trim() ? `${key.description} (${key.key_prefix})` : key.key_prefix,
        value: key.id,
      })),
    ],
    [keys, t],
  );

  if (!canViewUsage) {
    return <Alert message={t("apiAccess:usageForbidden")} showIcon type="error" />;
  }

  const columns: TableColumnsType<ApiUsageRun> = [
    {
      title: t("apiAccess:time"),
      dataIndex: "created_at",
      render: (value: string) => formatDate(value, language),
      width: 190,
    },
    {
      title: t("common:status"),
      dataIndex: "workflow_status",
      render: (value: string) => <Tag color={statusColor(value)}>{t(`apiAccess:${value}`, { defaultValue: value })}</Tag>,
      width: 120,
    },
    {
      title: t("apiAccess:endpoint"),
      dataIndex: "endpoint_kind",
      render: (value: string) => t(`apiAccess:${value === "json_run" ? "jsonRun" : value === "file_upload" ? "fileUpload" : value === "legacy_unknown" ? "legacy" : value}`, { defaultValue: value }),
      width: 130,
    },
    {
      title: t("apiAccess:key"),
      render: (_, record) => record.api_key_description || record.api_key_prefix || "—",
      width: 160,
      ellipsis: true,
    },
    {
      title: t("apiAccess:response"),
      dataIndex: "response_time_ms",
      render: (value?: number | null) => formatMs(value),
      width: 110,
    },
    {
      title: t("apiAccess:input"),
      render: (_, record) => inputSummary(record.input_metadata),
      ellipsis: true,
    },
    {
      title: t("apiAccess:outputError"),
      render: (_, record) => errorSummary(record.error) || record.result_preview || "—",
      ellipsis: true,
    },
    {
      title: "",
      key: "trace",
      render: (_, record) => (
        <Button
          disabled={!record.workflow_run_id}
          onClick={() => {
            if (!record.workflow_run_id) return;
            navigate(`/workflows/${workflowId}?traceRunId=${encodeURIComponent(record.workflow_run_id)}&from=api-usage`);
          }}
          size="small"
          type="link"
        >
          {t("apiAccess:openTrace")}
        </Button>
      ),
      width: 110,
    },
  ];

  const storagePercent = summary
    ? Math.min(100, Math.round((summary.storage_used_bytes / summary.storage_limit_bytes) * 100))
    : 0;

  return (
    <section className="api-usage-tab" data-testid="api-usage-tab">
      <Card>
        <div className="api-usage-toolbar">
          <div>
            <h2>{t("apiAccess:usage")}</h2>
            <p className="mini-muted">{t("apiAccess:usageDescription")}</p>
          </div>
          <div className="api-usage-toolbar-actions">
            <Segmented<ApiUsageRange>
              options={RANGE_OPTIONS}
              value={range}
              onChange={(value) => {
                setRange(value);
                setPage(1);
              }}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>
              {t("common:refresh")}
            </Button>
          </div>
        </div>

        {error ? <Alert message={error} showIcon type="error" /> : null}

        {loading && !summary ? (
          <div className="api-usage-loading">
            <Spin />
          </div>
        ) : summary ? (
          <>
            <section className="api-metric-grid api-usage-metrics" aria-label={t("apiAccess:usageSummary")}>
              <ApiMetric label={t("apiAccess:calls")} value={summary.calls} note={range} />
              <ApiMetric label={t("apiAccess:successRate")} value={`${Math.round(summary.success_rate * 100)}%`} note={t("apiAccess:failures", { count: summary.failures })} />
              <ApiMetric label={t("apiAccess:avgResponse")} value={formatMs(summary.avg_response_time_ms)} note={`P95 ${formatMs(summary.p95_response_time_ms)}`} />
              <ApiMetric label={t("apiAccess:storageUsed")} value={formatBytes(summary.storage_used_bytes)} note={t("apiAccess:storageLimit", { value: formatBytes(summary.storage_limit_bytes) })} />
            </section>

            <div className="api-usage-storage">
              <Progress
                percent={storagePercent}
                status={summary.storage_over_limit ? "exception" : "normal"}
                strokeColor={summary.storage_over_limit ? undefined : "#7132f5"}
              />
            </div>

            <UsageTrend summary={summary} language={language} />
          </>
        ) : null}
      </Card>

      <Card>
        <div className="api-usage-filters">
          <Select options={[
            { label: t("apiAccess:allStatuses"), value: "" },
            { label: t("apiAccess:succeeded"), value: "succeeded" },
            { label: t("common:statuses.failed"), value: "failed" },
            { label: t("apiAccess:rejected"), value: "rejected" },
            { label: t("apiAccess:timeout"), value: "timeout" },
            { label: t("settings:error"), value: "error" }
          ]} value={status} onChange={(value) => { setStatus(value); setPage(1); }} />
          <Select options={[
            { label: t("apiAccess:allEndpoints"), value: "" },
            { label: t("apiAccess:jsonRun"), value: "json_run" },
            { label: t("apiAccess:fileUpload"), value: "file_upload" },
            { label: t("apiAccess:legacy"), value: "legacy_unknown" }
          ]} value={endpoint} onChange={(value) => { setEndpoint(value); setPage(1); }} />
          <Select options={keyOptions} value={keyId} onChange={(value) => { setKeyId(value); setPage(1); }} />
        </div>

        <Table<ApiUsageRun>
          columns={columns}
          dataSource={runs}
          loading={loading}
          locale={{ emptyText: <Empty description={t("apiAccess:noCalls")} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          pagination={{
            current: page,
            pageSize: limit,
            total,
            onChange: (nextPage) => setPage(nextPage),
            showSizeChanger: false,
          }}
          rowKey="id"
          size="middle"
        />
      </Card>
    </section>
  );
}
