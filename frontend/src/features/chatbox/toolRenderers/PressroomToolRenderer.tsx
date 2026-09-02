import { useTranslation } from "react-i18next";

import { ToolCard } from "@/features/chatbox/toolRenderers/ToolCard";
import { UnknownToolRenderer } from "@/features/chatbox/toolRenderers/UnknownToolRenderer";
import type {
  ToolRendererProps,
  ToolResultPayload,
} from "@/features/chatbox/toolRenderers/types";

const PRESSROOM_ENVELOPE_VERSION = "pressroom-envelope.v1";
const MAX_LIST_ITEMS = 50;

interface PressroomEnvelope {
  readonly ok: boolean;
  readonly data: unknown;
  readonly error: unknown;
}

interface SummaryRow {
  readonly label: string;
  readonly value: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function envelopeFrom(payload: ToolResultPayload | null): PressroomEnvelope | null {
  const details = payload?.details;
  if (
    !isRecord(details)
    || details.schema_version !== PRESSROOM_ENVELOPE_VERSION
    || typeof details.ok !== "boolean"
  ) {
    return null;
  }
  return {
    ok: details.ok,
    data: details.data,
    error: details.error,
  };
}

function humanize(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function scalarText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null) return "—";
  return null;
}

function firstRecordArray(value: unknown): readonly Record<string, unknown>[] {
  if (Array.isArray(value)) return value.filter(isRecord);
  if (!isRecord(value)) return [];
  for (const key of ["data", "items", "workflows", "versions", "runs"]) {
    const candidate = value[key];
    if (Array.isArray(candidate)) return candidate.filter(isRecord);
  }
  return [];
}

const SUMMARY_FIELDS = [
  "name",
  "id",
  "workflow_id",
  "workflow_key",
  "version",
  "latest_version",
  "published_version",
  "status",
  "run_id",
  "task_id",
  "success",
  "valid",
  "total_nodes",
  "updated_at",
  "created_at",
] as const;

function collectSummaryRows(value: unknown): readonly SummaryRow[] {
  if (!isRecord(value)) return [];
  const sources = [value];
  for (const key of ["data", "validation", "static", "execution_plan", "meta"]) {
    if (isRecord(value[key])) sources.push(value[key]);
  }
  const rows: SummaryRow[] = [];
  const seen = new Set<string>();
  for (const source of sources) {
    for (const field of SUMMARY_FIELDS) {
      const text = scalarText(source[field]);
      if (text === null || seen.has(field)) continue;
      seen.add(field);
      rows.push({ label: humanize(field), value: text });
    }
  }
  for (const source of sources) {
    for (const field of ["errors", "warnings"] as const) {
      const items = source[field];
      if (!Array.isArray(items) || seen.has(field)) continue;
      seen.add(field);
      rows.push({ label: humanize(field), value: String(items.length) });
    }
  }
  return rows.slice(0, 20);
}

function recordText(item: Record<string, unknown>, fields: readonly string[]): string {
  for (const field of fields) {
    const text = scalarText(item[field]);
    if (text !== null && text !== "—") return text;
  }
  return "—";
}

function PressroomListResult({ data }: { readonly data: unknown }) {
  const { t } = useTranslation("chatbox");
  const items = firstRecordArray(data);
  if (items.length === 0) {
    return <div className="chatbox-pressroom-empty">{t("pressroomNoItems")}</div>;
  }
  const visibleItems = items.slice(0, MAX_LIST_ITEMS);
  return (
    <div className="chatbox-pressroom-result" data-testid="chatbox-pressroom-result">
      <div className="chatbox-pressroom-count">
        {t("pressroomResultCount", { count: items.length })}
      </div>
      <div className="chatbox-pressroom-table-wrap">
        <table className="chatbox-pressroom-table">
          <thead>
            <tr>
              <th>{t("pressroomFieldName")}</th>
              <th>{t("pressroomFieldVersion")}</th>
              <th>{t("pressroomFieldUpdated")}</th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map((item, index) => (
              <tr key={recordText(item, ["id", "workflow_id", "version", "name"]) + index}>
                <td>
                  <span className="chatbox-pressroom-name">
                    {recordText(item, ["name", "title", "id", "workflow_id"])}
                  </span>
                  <span className="chatbox-pressroom-id">
                    {recordText(item, ["id", "workflow_id", "workflow_key"])}
                  </span>
                </td>
                <td>{recordText(item, ["latest_version", "version", "status"])}</td>
                <td>{recordText(item, ["updated_at", "created_at"])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length > visibleItems.length ? (
        <div className="chatbox-pressroom-count">
          {t("pressroomMoreItems", { count: items.length - visibleItems.length })}
        </div>
      ) : null}
    </div>
  );
}

function PressroomSummaryResult({ data }: { readonly data: unknown }) {
  const { t } = useTranslation("chatbox");
  const rows = collectSummaryRows(data);
  if (rows.length === 0) {
    return <div className="chatbox-pressroom-empty">{t("pressroomOperationComplete")}</div>;
  }
  return (
    <dl className="chatbox-pressroom-summary" data-testid="chatbox-pressroom-result">
      {rows.map((row) => (
        <div className="chatbox-pressroom-summary-row" key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PressroomErrorResult({ error }: { readonly error: unknown }) {
  const { t } = useTranslation("chatbox");
  const code = isRecord(error) ? scalarText(error.code) : null;
  const message = isRecord(error) ? scalarText(error.message) : scalarText(error);
  return (
    <div className="chatbox-pressroom-error" data-testid="chatbox-pressroom-result">
      <strong>{code ?? t("toolStatus.error")}</strong>
      {message !== null ? <span>{message}</span> : null}
    </div>
  );
}

export function PressroomToolRenderer({ exec, forceExpand }: ToolRendererProps) {
  const { t } = useTranslation("chatbox");
  const envelope = envelopeFrom(exec.result ?? exec.partial);
  if (envelope === null) {
    return <UnknownToolRenderer exec={exec} forceExpand={forceExpand} />;
  }
  const defaultLabel = humanize(exec.toolName);
  const title = t(`tools.${exec.toolName}`, { defaultValue: defaultLabel });
  const meta = scalarText(exec.args?.workflow_id) ?? scalarText(exec.args?.name);
  const isList = exec.toolName.endsWith("_list");
  return (
    <ToolCard
      forceExpand={forceExpand}
      meta={meta}
      status={exec.status}
      title={title}
    >
      {!envelope.ok
        ? <PressroomErrorResult error={envelope.error} />
        : isList
          ? <PressroomListResult data={envelope.data} />
          : <PressroomSummaryResult data={envelope.data} />}
    </ToolCard>
  );
}
