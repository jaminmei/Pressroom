import { Form, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { WorkspaceMember, WorkspaceRole } from "@/types/workspace";
import { WORKSPACE_ROLES } from "@/types/workspace";
import { RoleSelector } from "@/components/Permissions/RoleSelector";

export interface ChangeWorkspaceRoleDialogProps {
  open: boolean;
  member: WorkspaceMember | null;
  submitting?: boolean;
  onCancel: () => void;
  onSubmit: (role: WorkspaceRole) => void | Promise<void>;
}

export function ChangeWorkspaceRoleDialog({
  open,
  member,
  submitting,
  onCancel,
  onSubmit,
}: ChangeWorkspaceRoleDialogProps) {
  const { t } = useTranslation("workspaces");
  const [form] = Form.useForm<{ role: WorkspaceRole }>();

  const handleOk = () => {
    form.validateFields().then((values) => {
      onSubmit(values.role);
    });
  };

  const handleCancel = () => {
    form.resetFields();
    onCancel();
  };

  return (
    <Modal
      title={t("changeMemberRole")}
      open={open}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={handleCancel}
      destroyOnHidden
      rootClassName="workspace-dialog"
    >
      <div style={{ marginBottom: 16 }}>
        {t("changingRoleFor")} <strong>{member?.email || member?.name}</strong>
      </div>
      <Form
        form={form}
        initialValues={{ role: member?.role ?? "viewer" }}
        layout="vertical"
        preserve={false}
      >
        <Form.Item
          name="role"
          label={t("newRole")}
          rules={[{ required: true, message: t("selectRole") }]}
        >
          <RoleSelector roles={WORKSPACE_ROLES.filter((role) => role.role !== "owner")} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
