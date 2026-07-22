import { Alert, Button, Empty, Skeleton, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import type { WorkflowListItem } from "@/services/workflowApi";
import WorkflowStudioListItem from "@/features/workflow-studio/components/WorkflowStudioListItem";
import { PermissionButton } from "@/components/Permissions/PermissionButton";

interface WorkflowStudioListProps {
  deletingId: string | null;
  error: string | null;
  hasMore: boolean;
  items: WorkflowListItem[];
  loading: boolean;
  loadingMore: boolean;
  newerVersionWorkflowId: string | null;
  query: string;
  total: number;
  onClearQuery: () => void;
  onCreateNew: () => void;
  onDelete: (workflow: WorkflowListItem) => void;
  onLoadMore: () => void;
  onOpen: (workflow: WorkflowListItem) => void;
  onOpenApiAccess?: (workflow: WorkflowListItem) => void;
  onRename: (workflow: WorkflowListItem) => void;
  onRetry: () => void;
}

function LoadingState() {
  return (
    <div className="workflow-studio-loading" data-testid="workflow-studio-loading">
      {[0, 1, 2].map((index) => (
        <div className="workflow-studio-loading-card" key={index}>
          <Skeleton active paragraph={{ rows: 2 }} title={{ width: "45%" }} />
        </div>
      ))}
    </div>
  );
}

export default function WorkflowStudioList({
  deletingId,
  error,
  hasMore,
  items,
  loading,
  loadingMore,
  newerVersionWorkflowId,
  query,
  total,
  onClearQuery,
  onCreateNew,
  onDelete,
  onLoadMore,
  onOpen,
  onOpenApiAccess,
  onRename,
  onRetry
}: WorkflowStudioListProps) {
  const { t } = useTranslation(["common", "workflows"]);
  const normalizedQuery = query.trim();
  const isEmpty = !loading && items.length === 0 && !error;
  const isSearchEmpty = isEmpty && normalizedQuery.length > 0;
  const isInitialLoading = loading && items.length === 0;

  return (
    <section className="workflow-studio-list-shell">
      {error ? (
        <Alert
          action={
            <Button data-testid="workflow-studio-retry" onClick={onRetry} size="small" type="primary">
              {t("common:retry")}
            </Button>
          }
          className="workflow-studio-alert"
          data-testid="workflow-studio-error"
          message={t("workflows:studioText.loadFailed")}
          showIcon
          type="error"
          description={error}
        />
      ) : null}

      {isInitialLoading ? <LoadingState /> : null}

      {isSearchEmpty ? (
        <Empty
          className="workflow-studio-empty"
          data-testid="workflow-studio-empty-search"
          description={t("workflows:studioText.noMatches")}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <Space>
            <Button data-testid="workflow-studio-clear-search" onClick={onClearQuery}>
              {t("workflows:studioText.clearSearch")}
            </Button>
            <Button onClick={onRetry} type="primary">
              {t("workflows:studioText.reload")}
            </Button>
          </Space>
        </Empty>
      ) : null}

      {!isSearchEmpty && isEmpty ? (
        <Empty
          className="workflow-studio-empty"
          data-testid="workflow-studio-empty"
          description={t("workflows:studioText.empty")}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <PermissionButton capability="workflow.create" onClick={onCreateNew} type="primary">
            {t("workflows:studioText.goEditor")}
          </PermissionButton>
        </Empty>
      ) : null}

      {items.length > 0 ? (
        <>
          <div className="workflow-studio-list-summary">
            <Typography.Text type="secondary">
              {normalizedQuery
                ? t("workflows:studioText.searchSummary", { query: normalizedQuery, count: total })
                : t("workflows:studioText.totalSummary", { count: total })}
            </Typography.Text>
          </div>

          <div className="workflow-studio-list-grid" data-testid="workflow-studio-list">
            {items.map((item) => (
              <WorkflowStudioListItem
                deleting={deletingId === item.id}
                hasNewerVersion={newerVersionWorkflowId === item.id}
                key={item.id}
                onDelete={onDelete}
                onOpen={onOpen}
                onOpenApiAccess={onOpenApiAccess}
                onRename={onRename}
                workflow={item}
              />
            ))}
          </div>

          {hasMore ? (
            <div className="workflow-studio-load-more">
              <Button
                data-testid="workflow-studio-load-more"
                loading={loadingMore}
                onClick={onLoadMore}
                size="large"
              >
                {t("workflows:studioText.loadMore")}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
