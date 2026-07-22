import { LockOutlined } from "@ant-design/icons";
import { Button, Result } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

interface Props {
  workflowId: string;
}

export default function ApiAccessLockedState({ workflowId }: Props) {
  const { t } = useTranslation("apiAccess");
  const navigate = useNavigate();

  return (
    <Result
      data-testid="api-access-locked-state"
      icon={<LockOutlined />}
      status="info"
      title={t("publishRequired")}
      subTitle={t("publishRequiredDescription")}
      extra={
        <Button type="primary" onClick={() => navigate(`/workflows/${workflowId}`)}>
          {t("openEditor")}
        </Button>
      }
    />
  );
}
