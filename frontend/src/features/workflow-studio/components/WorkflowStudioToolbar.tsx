import { SearchOutlined } from "@ant-design/icons";
import { Input, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";

interface WorkflowStudioToolbarProps {
  loading: boolean;
  query: string;
  total: number;
  onCreateNew: () => void;
  onQueryChange: (value: string) => void;
}

export default function WorkflowStudioToolbar({
  loading,
  query,
  total,
  onCreateNew,
  onQueryChange
}: WorkflowStudioToolbarProps) {
  const { t } = useTranslation(["common", "workflows"]);
  return (
    <header className="workflow-studio-toolbar">
      <div className="workflow-studio-toolbar-copy">
        <span className="workflow-studio-kicker">{t("workflows:studioText.kicker")}</span>
        <Typography.Title level={2} style={{ margin: 0 }}>
          Workflow Studio
        </Typography.Title>
        <Typography.Paragraph className="workflow-studio-toolbar-description">
          {t("workflows:studioText.description")}
        </Typography.Paragraph>
        <div className="workflow-studio-toolbar-meta">
          <Tag bordered={false} color="blue" data-testid="workflow-studio-total">
            {loading ? t("common:loading") : t("workflows:studioText.count", { count: total })}
          </Tag>
          <Typography.Text type="secondary">
            {t("workflows:studioText.searchContract")}
          </Typography.Text>
        </div>
      </div>

      <Space className="workflow-studio-toolbar-actions" size={12}>
        <Input
          allowClear
          className="workflow-studio-search"
          data-testid="workflow-studio-search"
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={t("workflows:studioText.searchPlaceholder")}
          prefix={<SearchOutlined />}
          size="large"
          value={query}
        />
        <PermissionButton
          capability="workflow.create"
          data-testid="workflow-studio-create-button"
          onClick={onCreateNew}
          size="large"
          type="primary"
        >
          {t("workflows:newWorkflow")}
        </PermissionButton>
      </Space>
    </header>
  );
}
