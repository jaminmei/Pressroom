import { useEffect, useMemo } from "react";
import { Select } from "antd";
import type { DefaultOptionType } from "antd/es/select";
import { useTranslation } from "react-i18next";

import type { Provider, ProviderModel } from "@/types/provider";

interface ModelSelectorProps {
  provider: Provider;
  value?: string;
  onChange: (model: ProviderModel) => void;
  disabled?: boolean;
}

export default function ModelSelector({
  provider,
  value,
  onChange,
  disabled,
}: ModelSelectorProps) {
  const { t } = useTranslation("workflows");
  const groups = useMemo(() => {
    const map = new Map<string, ProviderModel[]>();
    for (const m of provider.models.filter((m) => m.is_enabled)) {
      const group = m.model_group || t("editorText.other");
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(m);
    }
    for (const models of map.values()) {
      models.sort((a, b) => a.sort_order - b.sort_order);
    }
    return map;
  }, [provider.models, t]);

  const options: DefaultOptionType[] = [];
  for (const [groupName, models] of groups) {
    options.push({
      label: groupName,
      options: models.map((m) => ({
        value: m.model_id,
        label: m.display_name,
        model: m,
      })),
    });
  }

  // Auto-select single model
  const enabledModels = provider.models.filter((m) => m.is_enabled);
  const onlyEnabledModel = enabledModels.length === 1 ? enabledModels[0] : null;
  useEffect(() => {
    if (onlyEnabledModel && !value) {
      onChange(onlyEnabledModel);
    }
  }, [onlyEnabledModel, value, onChange]);

  // Clear value if not in current provider's models
  const currentModelIds = new Set(enabledModels.map((m) => m.model_id));
  const safeValue = value && currentModelIds.has(value) ? value : undefined;

  return (
    <Select
      style={{ width: "100%" }}
      placeholder={t("editorText.selectModel")}
      value={safeValue}
      options={options}
      onChange={(_val, option) => {
        const mod = (option as DefaultOptionType & { model: ProviderModel }).model;
        onChange(mod);
      }}
      disabled={disabled}
    />
  );
}
