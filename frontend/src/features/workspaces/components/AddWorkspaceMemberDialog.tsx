import { Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { InviteWorkspaceMemberRequest } from "@/types/workspace";
import { WORKSPACE_ROLES } from "@/types/workspace";
import { RoleSelector } from "@/components/Permissions/RoleSelector";

export interface AddWorkspaceMemberDialogProps {
  open: boolean;
  submitting?: boolean;
  onCancel: () => void;
  onSubmit: (payload: InviteWorkspaceMemberRequest) => void | Promise<void>;
}

export function AddWorkspaceMemberDialog({
  open,
  submitting,
  onCancel,
  onSubmit,
}: AddWorkspaceMemberDialogProps) {
  const { t } = useTranslation("workspaces");
  const [form] = Form.useForm<InviteWorkspaceMemberRequest>();

  const handleOk = () => {
    form.validateFields().then((values) => {
      onSubmit(values);
    });
  };

  const handleCancel = () => {
    form.resetFields();
    onCancel();
  };

  return (
    <Modal
      title={t("addExistingMember")}
      open={open}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={handleCancel}
      destroyOnHidden
      rootClassName="workspace-dialog"
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ role: "viewer" }}
        preserve={false}
      >
        <Form.Item
          name="email"
          label={t("emailAddress")}
          rules={[
            { required: true, message: t("enterEmail") },
            { type: "email", message: t("validEmail") },
          ]}
        >
          <Input placeholder="registered-user@example.com" data-testid="invite-email-input" />
        </Form.Item>

        <Form.Item
          name="role"
          label={t("role")}
          rules={[{ required: true, message: t("selectRole") }]}
        >
          <RoleSelector roles={WORKSPACE_ROLES.filter((role) => role.role !== "owner")} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
