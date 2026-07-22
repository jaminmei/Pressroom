import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { WorkspaceMember } from "@/types/workspace";

export interface RemoveWorkspaceMemberDialogProps {
  open: boolean;
  member: WorkspaceMember | null;
  submitting?: boolean;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
}

export function RemoveWorkspaceMemberDialog({
  open,
  member,
  submitting,
  onCancel,
  onConfirm,
}: RemoveWorkspaceMemberDialogProps) {
  const { t } = useTranslation(["common", "workspaces"]);
  const memberLabel = member?.email || member?.name || "";
  return (
    <Modal
      title={t("workspaces:removeMemberTitle")}
      open={open}
      confirmLoading={submitting}
      onOk={onConfirm}
      onCancel={onCancel}
      okButtonProps={{ danger: true }}
      okText={t("common:remove")}
      destroyOnHidden
      rootClassName="workspace-dialog"
    >
      <p>{t("workspaces:removeMemberConfirm", { member: memberLabel })}</p>
      <p>{t("workspaces:removeMemberWarning")}</p>
    </Modal>
  );
}
