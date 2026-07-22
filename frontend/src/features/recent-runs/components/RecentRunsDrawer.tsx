import { Button, Drawer, Skeleton, Typography } from "antd";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import RunItem from "@/features/recent-runs/components/RunItem";
import { useRecentRuns } from "@/features/recent-runs/hooks/useRecentRuns";

interface RecentRunsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export default function RecentRunsDrawer({ open, onClose }: RecentRunsDrawerProps) {
  const { t } = useTranslation("workflows");
  const navigate = useNavigate();
  const { items, loading, error, hasMore, refresh, fetchMore } = useRecentRuns();

  useEffect(() => {
    if (open) {
      void refresh();
    }
  }, [open, refresh]);

  return (
    <Drawer
      data-testid="recent-runs-drawer"
      onClose={onClose}
      open={open}
      placement="right"
      title={t("recentRuns")}
      width={360}
    >
      <div className="recent-runs-drawer-content">
        {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : null}

        {!loading && items.length === 0 && !error ? <p>{t("noRecentRuns")}</p> : null}

        {!loading && error ? (
          <Typography.Text type="danger">{error}</Typography.Text>
        ) : null}

        {!loading
          ? items.map((item) => (
              <RunItem
                item={item}
                key={item.task_id}
                onClick={() => {
                  navigate(`/tasks/${item.task_id}/results`);
                  onClose();
                }}
              />
            ))
          : null}

        {hasMore && !loading ? (
          <Button onClick={() => void fetchMore()} type="default">
            {t("studioText.loadMore")}
          </Button>
        ) : null}
      </div>
    </Drawer>
  );
}
