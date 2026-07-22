import { Alert, Button, Space } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useTaskExecutionStore } from "@/features/task-execution/store";

interface WSConnectionBannerProps {
  onManualReconnect?: () => Promise<boolean>;
}

export default function WSConnectionBanner({ onManualReconnect }: WSConnectionBannerProps) {
  const { t } = useTranslation("workflows");
  const [reconnecting, setReconnecting] = useState(false);

  const taskStatus = useTaskExecutionStore((state) => state.taskStatus);
  const wsWarning = useTaskExecutionStore((state) => state.wsWarning);
  const manualReconnectAvailable = useTaskExecutionStore((state) => state.manualReconnectAvailable);

  if (!wsWarning || (taskStatus !== "pending" && taskStatus !== "running")) {
    return null;
  }

  return (
    <Alert
      action={
        manualReconnectAvailable && onManualReconnect ? (
          <Space>
            <Button
              loading={reconnecting}
              onClick={async () => {
                setReconnecting(true);
                try {
                  await onManualReconnect();
                } finally {
                  setReconnecting(false);
                }
              }}
              size="small"
              type="primary"
            >
              {t("resultText.reconnect")}
            </Button>
          </Space>
        ) : null
      }
      data-testid="ws-connection-banner"
      message={wsWarning}
      showIcon
      type="warning"
    />
  );
}
