import { Link } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { Divider, Empty, Select, Spin, Typography } from "antd";
import type { DefaultOptionType } from "antd/es/select";
import { useTranslation } from "react-i18next";

import { useProviders } from "@/features/workflow-editor/hooks/useProviders";
import type { Provider } from "@/types/provider";
import { replaceVisibleProviders, resetProviderScopeState } from "@/services/providerApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";

interface ProviderSelectorProps {
  engineCategory: string;
  value?: string;
  onChange: (provider: Provider) => void;
  disabled?: boolean;
}

const UNAVAILABLE_PROVIDER_VALUE = "__provider_unavailable__";

export default function ProviderSelector({
  engineCategory,
  value,
  onChange,
  disabled,
}: ProviderSelectorProps) {
  const { t } = useTranslation("workflows");
  const { providers, loading, error, refetch } = useProviders(engineCategory);
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);
  const [switching, setSwitching] = useState(false);
  const observedReload = useRef(false);
  const previousGeneration = useRef(contextGeneration);

  useEffect(() => {
    if (previousGeneration.current === contextGeneration) return;
    previousGeneration.current = contextGeneration;
    resetProviderScopeState();
    observedReload.current = false;
    setSwitching(true);
    refetch();
  }, [contextGeneration, refetch]);

  useEffect(() => {
    if (!switching) return;
    if (loading) {
      observedReload.current = true;
    } else if (observedReload.current) {
      setSwitching(false);
    }
  }, [loading, switching]);

  // Build a map for type-safe provider lookup from selected value
  const providerMap = useMemo(() => {
    const map = new Map<string, Provider>();
    for (const p of providers) map.set(p.id, p);
    return map;
  }, [providers]);

  useEffect(() => {
    replaceVisibleProviders(providers);
  }, [providers]);

  if (loading || switching) {
    return <Spin size="small" />;
  }

  if (error) {
    return <Typography.Text type="danger">{t("editorText.loadProvidersFailed")}</Typography.Text>;
  }

  const unavailable = value !== undefined && !providerMap.has(value);
  const groupedOptions: DefaultOptionType[] = (["workspace", "system"] as const).flatMap((scope) => {
    const scopedProviders = providers.filter((provider) => provider.scope === scope);
    return scopedProviders.length === 0 ? [] : [{
      label: scope === "workspace" ? t("editorText.workspaceProviders") : t("editorText.systemProviders"),
      options: scopedProviders.map((p) => ({
        value: p.id,
        label: (
          <span>
            {p.is_default && <span title={t("editorText.default")}>⭐</span>} {p.name}
            {p.auth_type && p.auth_type !== "none" && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {" "}({p.auth_type})
              </Typography.Text>
            )}
          </span>
        ),
      })),
    }];
  });
  const options: DefaultOptionType[] = [
    ...(unavailable ? [{ value: UNAVAILABLE_PROVIDER_VALUE, label: t("editorText.providerUnavailable"), disabled: true }] : []),
    ...groupedOptions,
  ];

  return (
    <Select
      style={{ width: "100%" }}
      placeholder={t("editorText.selectProvider")}
      value={unavailable ? UNAVAILABLE_PROVIDER_VALUE : value || undefined}
      options={options}
      onChange={(val) => {
        if (typeof val !== "string") return;
        const prov = providerMap.get(val);
        if (prov) onChange(prov);
      }}
      disabled={disabled}
      notFoundContent={
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span>
              {t("editorText.noProvidersAvailable")} {" "}
              <Link to="/settings/engines">{t("editorText.addProvider")}</Link>
            </span>
          }
        />
      }
      popupRender={(menu) => (
        <>
          {menu}
          <Divider style={{ margin: "8px 0" }} />
          <div style={{ padding: "4px 12px" }}>
            <Link to="/settings/engines">{t("editorText.manageProviders")}</Link>
          </div>
        </>
      )}
    />
  );
}
