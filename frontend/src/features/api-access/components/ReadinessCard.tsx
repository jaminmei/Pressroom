import { Card } from "antd";
import { useTranslation } from "react-i18next";

import type { ApiKeyRecord } from "@/services/apiAccessApi";

interface Props {
  isPublished: boolean;
  keys: ApiKeyRecord[];
  workflowId: string;
}

interface CheckItem {
  label: string;
  ok: boolean;
  hint?: string;
}

export default function ReadinessCard({ isPublished, keys }: Props) {
  const { t } = useTranslation("apiAccess");
  const activeKeys = keys.filter((k) => k.is_active);

  const checks: CheckItem[] = [
    { label: t("savedExists"), ok: true },
    { label: t("publishedSelected"), ok: isPublished },
    {
      label: t("workflowKey"),
      ok: activeKeys.length > 0,
      hint: activeKeys.length === 0 ? t("issueKey") : undefined,
    },
    { label: t("remoteUrl"), ok: isPublished },
    { label: t("ownershipChecks"), ok: isPublished },
  ];

  const allReady = checks.every((c) => c.ok);

  return (
    <Card data-testid="readiness-card">
      <div className="panel-head">
        <div>
          <h2>{t("readiness")}</h2>
          <p className="mini-muted">{t("readinessDescription")}</p>
        </div>
        {allReady ? (
          <span className="tag tag-success">{t("ready")}</span>
        ) : (
          <span className="tag tag-warning">{t("notReady")}</span>
        )}
      </div>
      <div className="api-checklist">
        {checks.map((item, idx) => (
          <div key={idx} className="api-check-item">
            <span>{item.label}</span>
            {item.ok ? (
              <span className="check-dot" aria-label={t("done")}>✓</span>
            ) : (
              <span className="tag tag-warning">{item.hint ?? t("notReady")}</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
