import { Alert, Button, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import type { WorkflowActorSummary, WorkflowVersionConflictDetails } from "@/features/workflow-editor/workflowPersistenceStore";

interface VersionConflictBannerProps {
  pendingConflict: WorkflowVersionConflictDetails | null;
  newerVersionAvailable: boolean;
  workflowId: string | null;
  baseVersion: number | null;
  latestVersion: number;
  lastSavedBy: WorkflowActorSummary | null;
  onRefreshLatest: () => Promise<boolean>;
  onKeepLocalDraft: () => void;
  onOpenSaveAs: () => void;
}

export default function VersionConflictBanner({
  pendingConflict,
  newerVersionAvailable,
  workflowId,
  baseVersion,
  latestVersion,
  lastSavedBy,
  onRefreshLatest,
  onKeepLocalDraft,
  onOpenSaveAs
}: VersionConflictBannerProps) {
  const { t } = useTranslation("workflows");
  if (!(pendingConflict || newerVersionAvailable) || !workflowId) {
    return null;
  }

  const bannerDetails = pendingConflict ?? null;

  return (
    <Alert
      action={
        <Space size={8} wrap>
          <Button
            data-testid="workflow-refresh-latest"
            onClick={() => void onRefreshLatest()}
            size="small"
            type="primary"
          >
            {t("editorText.refreshLatest")}
          </Button>
          <Button
            data-testid="workflow-open-save-as"
            onClick={onOpenSaveAs}
            size="small"
          >
            {t("editorText.saveAsNewName")}
          </Button>
          <Button
            data-testid="workflow-keep-local-draft"
            onClick={onKeepLocalDraft}
            size="small"
          >
            {t("editorText.keepLocalDraft")}
          </Button>
        </Space>
      }
      banner
      data-testid={pendingConflict ? "workflow-conflict-banner" : "workflow-newer-version-banner"}
      message={pendingConflict ? t("editorText.conflictDetected") : t("editorText.newerVersion")}
      showIcon
      type={pendingConflict ? "warning" : "info"}
      description={
        <Space direction="vertical" size={4}>
          <Typography.Text>
            {pendingConflict
              ? t("editorText.conflictDescription", {
                  baseVersion: bannerDetails?.base_version ?? baseVersion ?? "?",
                  latestVersion: bannerDetails?.latest_version ?? latestVersion
                })
              : t("editorText.newerVersionDescription", { latestVersion, baseVersion: baseVersion ?? "?" })}
          </Typography.Text>
          {bannerDetails?.last_saved_by?.email || lastSavedBy?.email ? (
            <Typography.Text type="secondary">
              {t("editorText.lastSavedBy", { name: bannerDetails?.last_saved_by?.name?.trim() || bannerDetails?.last_saved_by?.email || lastSavedBy?.name?.trim() || lastSavedBy?.email })}
            </Typography.Text>
          ) : null}
        </Space>
      }
    />
  );
}
