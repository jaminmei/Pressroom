import { Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { CreateWorkspaceRequest } from "@/types/workspace";

export interface NewWorkspaceDialogProps {
  open: boolean;
  submitting?: boolean;
  onCancel: () => void;
  onSubmit: (payload: CreateWorkspaceRequest) => void | Promise<void>;
}

export function NewWorkspaceDialog({
  open,
  submitting,
  onCancel,
  onSubmit,
}: NewWorkspaceDialogProps) {
  const { t } = useTranslation(["common", "workspaces"]);
  const [form] = Form.useForm<CreateWorkspaceRequest>();

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await onSubmit({
        ...values,
        name: values.name.trim(),
        description: values.description?.trim() || null,
      });
    } catch (errorObj: unknown) {
      if (typeof errorObj === "object" && errorObj !== null && "errorFields" in errorObj) {
        return;
      }
      throw errorObj;
    }
  };

  const handleCancel = () => {
    form.resetFields();
    onCancel();
  };

  return (
    <Modal
      title={t("workspaces:createWorkspace")}
      open={open}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={t("workspaces:createWorkspace")}
      destroyOnHidden
      data-testid="new-workspace-dialog"
    >
      <Form form={form} layout="vertical" name="create-workspace">
        <Form.Item
          name="name"
          label={t("workspaces:workspaceName")}
          rules={[
            { required: true, message: t("workspaces:enterName") },
            {
              validator: (_, value: string | undefined) =>
                value?.trim() ? Promise.resolve() : Promise.reject(new Error(t("workspaces:enterName"))),
            },
          ]}
        >
          <Input maxLength={100} placeholder={t("workspaces:workspaceNamePlaceholder")} data-testid="new-workspace-name-input" />
        </Form.Item>

        <Form.Item name="description" label={t("common:description")}>
          <Input.TextArea placeholder={t("workspaces:optionalDescription")} rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
