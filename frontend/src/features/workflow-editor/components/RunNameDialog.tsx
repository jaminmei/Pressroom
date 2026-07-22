import { Input, Modal, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface RunNameDialogProps {
  open: boolean;
  onConfirm: (name: string) => void;
  onCancel: () => void;
}

export default function RunNameDialog({ open, onConfirm, onCancel }: RunNameDialogProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const [name, setName] = useState("");

  const handleOk = () => {
    onConfirm(name.trim() || "");
  };

  const handleCancel = () => {
    setName("");
    onCancel();
  };

  return (
    <Modal
      open={open}
      title={t("editorText.nameRun")}
      okText={t("editorText.execute")}
      cancelText={t("common:cancel")}
      onOk={handleOk}
      onCancel={handleCancel}
      destroyOnHidden
      data-testid="run-name-dialog"
    >
      <div className="run-name-dialog-body">
        <Typography.Text type="secondary">
          {t("editorText.runNameDescription")}
        </Typography.Text>
        <Input
          placeholder={t("editorText.runNamePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onPressEnter={handleOk}
          autoFocus
          maxLength={100}
          showCount
          data-testid="run-name-input"
          style={{ marginTop: 12 }}
        />
      </div>
    </Modal>
  );
}
