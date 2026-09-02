import { useCallback, useEffect, useState } from "react";
import { Button, Empty, Result, Spin, Typography } from "antd";
import { SettingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import type { EngineWithProviders } from "@/types/engine";
import { getEngines } from "@/services/enginesApi";

import EngineSection from "./EngineSection";
import AgentLlmSettingsCard from "./AgentLlmSettingsCard";

export default function SettingsPage() {
  const { t } = useTranslation(["common", "settings"]);
  const [engines, setEngines] = useState<EngineWithProviders[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEngines = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getEngines();
      setEngines(data.engines);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("settings:failedLoadEngines");
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadEngines();
  }, [loadEngines]);

  const renderEngines = () => {
    if (loading) return <Spin size="large" />;
    if (error !== null) {
      return (
        <Result
          status="error"
          title={t("settings:failedLoadEngines")}
          subTitle={error}
          extra={<Button onClick={loadEngines}>{t("common:retry")}</Button>}
        />
      );
    }
    if (engines.length === 0) {
      return <Empty description={t("settings:noEngines")} />;
    }
    return engines.map((engine) => (
      <EngineSection key={engine.category} engine={engine} />
    ));
  };

  return (
    <div style={{ position: "absolute", inset: 0, padding: 24, overflowY: "auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 24 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          <SettingOutlined style={{ marginRight: 8 }} />
          {t("settings:title")}
        </Typography.Title>
      </div>

      <AgentLlmSettingsCard />

      {renderEngines()}
    </div>
  );
}
