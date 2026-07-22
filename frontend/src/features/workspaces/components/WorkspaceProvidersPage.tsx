import { ProviderSettingsContent } from "@/features/settings/components/ProviderSettingsPage";
import { useTranslation } from "react-i18next";

export default function WorkspaceProvidersPage() {
  const { t } = useTranslation("workspaces");
  return (
    <ProviderSettingsContent
      embedded
      title={t("providers")}
      description={t("providersDescription")}
    />
  );
}
