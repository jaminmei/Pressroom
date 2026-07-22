import { CheckCircleOutlined, CopyOutlined } from "@ant-design/icons";
import { Alert, App as AntApp, Button, Modal, Typography } from "antd";
import { useTranslation } from "react-i18next";

import type { IssueApiKeyResponse } from "@/services/apiAccessApi";

const { Paragraph, Text } = Typography;

interface Props {
  open: boolean;
  apiKey: IssueApiKeyResponse | null;
  onClose: () => void;
}

export default function ApiKeyCreatedModal({ open, apiKey, onClose }: Props) {
  const { t } = useTranslation("apiAccess");
  const { message } = AntApp.useApp();
  const copy = () => {
    if (apiKey) {
      void navigator.clipboard.writeText(apiKey.key).then(() => message.success(t("keyCopied")));
    }
  };

  return (
    <Modal
      data-testid="api-key-created-modal"
      open={open && Boolean(apiKey)}
      title={t("keyCreated")}
      destroyOnHidden
      onCancel={onClose}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={copy}>{t("copyKey")}</Button>,
        <Button key="done" type="primary" icon={<CheckCircleOutlined />} onClick={onClose}>{t("savedKey")}</Button>,
      ]}
    >
      {apiKey ? (
        <>
          <Alert
            showIcon
            type="warning"
            message={t("copyKeyNow")}
            description={t("keyOneTime")}
            style={{ marginBottom: 12 }}
          />
          <Paragraph code copyable={false} style={{ wordBreak: "break-all" }}>
            {apiKey.key}
          </Paragraph>
          <Text type="secondary">{t("prefix", { prefix: apiKey.key_prefix })}</Text>
        </>
      ) : null}
    </Modal>
  );
}
