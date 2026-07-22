import { ApiOutlined } from "@ant-design/icons";
import { Button, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import type { WorkflowListItem } from "@/services/workflowApi";

interface WorkflowStudioListItemProps {
  deleting: boolean;
  hasNewerVersion: boolean;
  onDelete: (workflow: WorkflowListItem) => void;
  onOpen: (workflow: WorkflowListItem) => void;
  onOpenApiAccess?: (workflow: WorkflowListItem) => void;
  onRename: (workflow: WorkflowListItem) => void;
  workflow: WorkflowListItem;
}

function formatUpdatedAt(value: string, unknownLabel: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return unknownLabel;
  }

  return date.toLocaleString(locale);
}

export default function WorkflowStudioListItem({
  deleting,
  hasNewerVersion,
  onDelete,
  onOpen,
  onOpenApiAccess,
  onRename,
  workflow
}: WorkflowStudioListItemProps) {
  const { t, i18n } = useTranslation("workflows");
  const isPublished = Boolean(workflow.published_version);
  return (
    <article className="workflow-studio-list-item" data-testid={`workflow-studio-item-${workflow.id}`}>
      <div className="workflow-studio-list-item-copy">
        <div className="workflow-studio-list-item-heading">
          <Typography.Title className="workflow-studio-list-item-title" level={4}>
            {workflow.name?.trim() || t("studioText.untitled")}
          </Typography.Title>
          <Typography.Text className="workflow-studio-list-item-updated" type="secondary">
            {t("studioText.lastUpdated", {
              time: formatUpdatedAt(workflow.updated_at, t("studioText.unknownTime"), i18n.language === "zh-TW" ? "zh-TW" : "en-US")
            })}
          </Typography.Text>
        </div>

        <Typography.Paragraph className="workflow-studio-list-item-description">
          {workflow.description?.trim() || t("studioText.noDescription")}
        </Typography.Paragraph>
      </div>

      <div className="workflow-studio-list-item-rail">
        <div className="workflow-studio-list-item-meta">
          <Tag bordered={false} color="blue">
            {t("studioText.latestVersion", { version: workflow.latest_version ?? 0 })}
          </Tag>
          {isPublished ? (
            <Tag bordered={false} color="green">
              {t("studioText.publishedVersion", { version: workflow.published_version })}
            </Tag>
          ) : null}
          {hasNewerVersion ? (
            <Tag bordered={false} color="gold" data-testid={`workflow-studio-newer-version-${workflow.id}`}>
              {t("studioText.newerVersion")}
            </Tag>
          ) : null}
        </div>

        <Space className="workflow-studio-list-item-actions" size={8}>
          <Button
            data-testid={`workflow-studio-open-${workflow.id}`}
            onClick={() => onOpen(workflow)}
            type="primary"
          >
            {t("studioText.open")}
          </Button>
          <PermissionButton
            capability="workflow.edit_draft"
            data-testid={`workflow-studio-rename-${workflow.id}`}
            onClick={() => onRename(workflow)}
          >
            {t("studioText.rename")}
          </PermissionButton>
          {onOpenApiAccess ? (
            <PermissionButton
              capability="api_key.view"
              data-testid={`workflow-studio-api-access-${workflow.id}`}
              disabled={!isPublished}
              disabledReason={t("studioText.publishForApi")}
              icon={<ApiOutlined />}
              onClick={() => onOpenApiAccess(workflow)}
            >
              {t("studioText.apiAccess")}
            </PermissionButton>
          ) : null}
          <PermissionButton
            capability="workflow.delete"
            danger
            data-testid={`workflow-studio-delete-${workflow.id}`}
            loading={deleting}
            onClick={() => onDelete(workflow)}
          >
            {t("common:delete", { ns: "common" })}
          </PermissionButton>
        </Space>
      </div>
    </article>
  );
}
