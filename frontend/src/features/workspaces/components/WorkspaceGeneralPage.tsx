import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, LogoutOutlined, SwapOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";
import {
  deleteWorkspace,
  getWorkspaceDeletionImpact,
  listWorkspaceMembers,
  transferWorkspaceOwner,
} from "@/services/workspaceApi";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { UpdateWorkspaceRequest, WorkspaceMember } from "@/types/workspace";
import type { WorkspaceDeletionImpact } from "@/services/workspaceApi";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function WorkspaceGeneralPage() {
  const { t } = useTranslation(["common", "workspaces"]);
  const navigate = useNavigate();
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const refreshWorkspaces = useWorkspaceStore((state) => state.refreshWorkspaces);
  const resetWorkspaceState = useWorkspaceStore((state) => state.resetWorkspaceState);
  const [form] = Form.useForm<UpdateWorkspaceRequest>();
  const { can } = usePermission();
  const canUpdate = can("workspace.update");
  const canTransfer = can("workspace.transfer_owner");
  const canDelete = can("workspace.delete");

  const workspaceId = currentWorkspace?.id;
  const workspaceName = currentWorkspace?.name;
  const workspaceDescription = currentWorkspace?.description;
  const deletionImpactRequestIdRef = useRef(0);
  const memberRequestIdRef = useRef(0);

  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [deletionImpact, setDeletionImpact] = useState<WorkspaceDeletionImpact | null>(null);
  const [deletionImpactError, setDeletionImpactError] = useState<string | null>(null);
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersError, setMembersError] = useState<string | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferTarget, setTransferTarget] = useState<string>();
  const [transferSubmitting, setTransferSubmitting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);

  const loadMembers = useCallback(async () => {
    if (!workspaceId) return;

    const requestId = ++memberRequestIdRef.current;
    setMembersLoading(true);
    setMembersError(null);
    try {
      const response = await listWorkspaceMembers(workspaceId);
      if (requestId !== memberRequestIdRef.current) return;
      setMembers(response.items);
    } catch (error: unknown) {
      if (requestId !== memberRequestIdRef.current) return;
      setMembersError(getErrorMessage(error, t("workspaces:couldNotLoadMembers")));
    } finally {
      if (requestId === memberRequestIdRef.current) {
        setMembersLoading(false);
      }
    }
  }, [t, workspaceId]);

  useEffect(() => {
    if (workspaceName === undefined) return;
    form.setFieldsValue({
      name: workspaceName,
      description: workspaceDescription,
    });
  }, [form, workspaceDescription, workspaceName]);

  useEffect(() => {
    if (!workspaceId) return;
    memberRequestIdRef.current += 1;
    setMembers([]);
    setDeletionImpact(null);
    setDeletionImpactError(null);
    setTransferTarget(undefined);
    setDeleteConfirmation("");
    void loadMembers();

    return () => {
      memberRequestIdRef.current += 1;
    };
  }, [loadMembers, workspaceId]);

  const loadDeletionImpact = useCallback(async () => {
    if (!workspaceId) return;
    const requestId = ++deletionImpactRequestIdRef.current;
    setDeletionImpact(null);
    setDeletionImpactError(null);
    try {
      const impact = await getWorkspaceDeletionImpact(workspaceId);
      if (requestId === deletionImpactRequestIdRef.current) setDeletionImpact(impact);
    } catch (error: unknown) {
      if (requestId === deletionImpactRequestIdRef.current) {
        setDeletionImpactError(getErrorMessage(error, t("workspaces:deletionUnknown")));
      }
    }
  }, [t, workspaceId]);

  useEffect(() => {
    void loadDeletionImpact();
    return () => {
      deletionImpactRequestIdRef.current += 1;
    };
  }, [loadDeletionImpact]);

  const eligibleTransferMembers = useMemo(
    () =>
      members.filter(
        (member) => member.status === "active" && member.role !== "owner",
      ),
    [members],
  );

  const handleUpdate = async (values: UpdateWorkspaceRequest) => {
    if (!currentWorkspace) return;
    try {
      const updatedWorkspace = await useWorkspaceStore
        .getState()
        .updateWorkspace(currentWorkspace.id, {
          ...values,
          name: values.name?.trim(),
        });
      form.setFieldsValue({
        name: updatedWorkspace.name,
        description: updatedWorkspace.description,
      });
      message.success(t("workspaces:workspaceUpdated"));
    } catch (error: unknown) {
      message.error(getErrorMessage(error, t("workspaces:updateFailed")));
    }
  };

  const handleTransfer = async () => {
    if (!workspaceId || !transferTarget) return;

    setTransferSubmitting(true);
    try {
      await transferWorkspaceOwner(workspaceId, { newOwnerUserId: transferTarget });
      try {
        await refreshWorkspaces();
      } catch (error: unknown) {
        setTransferOpen(false);
        setTransferTarget(undefined);
        message.warning(
          t("workspaces:transferRefreshFailed", {
            error: getErrorMessage(error, t("workspaces:reloadToContinue"))
          }),
        );
        return;
      }
      await loadMembers();
      setTransferOpen(false);
      setTransferTarget(undefined);
      message.success(t("workspaces:ownershipTransferred"));
    } catch (error: unknown) {
      message.error(getErrorMessage(error, t("workspaces:roleChangeFailed")));
    } finally {
      setTransferSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!currentWorkspace || deleteConfirmation !== currentWorkspace.name) return;

    setDeleteSubmitting(true);
    try {
      try {
        await deleteWorkspace(currentWorkspace.id);
      } catch (error: unknown) {
        await loadDeletionImpact();
        message.error(getErrorMessage(error, t("workspaces:deleteFailed")));
        return;
      }

      setDeleteOpen(false);
      setDeleteConfirmation("");
      try {
        await refreshWorkspaces();
        message.success(t("workspaces:workspaceDeleted"));
      } catch (error: unknown) {
        resetWorkspaceState();
        message.warning(
          t("workspaces:deleteRefreshFailed", {
            error: getErrorMessage(error, t("workspaces:reloadToContinue"))
          }),
        );
      }
      navigate("/", { replace: true });
    } finally {
      setDeleteSubmitting(false);
    }
  };

  if (!currentWorkspace) return null;

  const deleteDisabledReason = deletionImpactError
    ? t("workspaces:deletionUnknown")
    : deletionImpact === null
      ? t("workspaces:checkingDeletion")
      : !deletionImpact.canDelete
        ? t("workspaces:deletionHasResources")
        : null;
  const deleteNameMatches = deleteConfirmation === currentWorkspace.name;

  return (
    <div className="workspace-general-page" data-testid="workspace-general-page">
      <Card className="workspace-settings-panel" title={t("workspaces:generalDetails")}>
        <Form
          className="workspace-general-form"
          form={form}
          layout="vertical"
          onFinish={handleUpdate}
        >
          <Form.Item
            name="name"
            label={t("workspaces:workspaceName")}
            rules={[{ required: true, message: t("workspaces:nameRequired") }]}
          >
            <Input disabled={!canUpdate} maxLength={100} />
          </Form.Item>

          <Form.Item name="description" label={t("common:description")}>
            <Input.TextArea rows={3} disabled={!canUpdate} />
          </Form.Item>

          {canUpdate ? (
            <div className="workspace-general-form-actions">
              <Button type="primary" htmlType="submit">
                {t("workspaces:saveChanges")}
              </Button>
            </div>
          ) : (
            <Alert
              type="info"
              message={t("workspaces:editRequiresAdmin")}
              showIcon
            />
          )}
        </Form>
      </Card>

      <Card
        className="workspace-settings-panel workspace-danger-panel"
        title={t("workspaces:dangerZone")}
      >
        <div className="workspace-danger-list">
          <div className="workspace-danger-row">
            <div className="workspace-danger-copy">
              <Typography.Text strong>{t("workspaces:leaveWorkspace")}</Typography.Text>
              <Typography.Text type="secondary">
                {t("workspaces:leaveDescription")}
              </Typography.Text>
            </div>
            <div className="workspace-danger-action">
              <Button danger disabled icon={<LogoutOutlined />}>
                {t("workspaces:leaveWorkspace")}
              </Button>
              <Typography.Text className="workspace-action-reason" type="secondary">
                {t("workspaces:leaveUnsupported")}
              </Typography.Text>
            </div>
          </div>

          <div className="workspace-danger-row">
            <div className="workspace-danger-copy">
              <Typography.Text strong>{t("workspaces:transferOwnership")}</Typography.Text>
              <Typography.Text type="secondary">
                {t("workspaces:transferDescription")}
              </Typography.Text>
            </div>
            <div className="workspace-danger-action">
              {canTransfer ? (
                <Button icon={<SwapOutlined />} onClick={() => setTransferOpen(true)}>
                  {t("workspaces:transfer")}
                </Button>
              ) : (
                <PermissionButton
                  capability="workspace.transfer_owner"
                  icon={<SwapOutlined />}
                >
                  {t("workspaces:transfer")}
                </PermissionButton>
              )}
            </div>
          </div>

          <div className="workspace-danger-row is-destructive">
            <div className="workspace-danger-copy">
              <Typography.Text strong>{t("workspaces:deleteWorkspace")}</Typography.Text>
              <Typography.Text type="secondary">
                {t("workspaces:deleteDescription")}
              </Typography.Text>
            </div>
            <div className="workspace-danger-action">
              {canDelete ? (
                <Button
                  danger
                  type="primary"
                  disabled={deleteDisabledReason !== null}
                  icon={<DeleteOutlined />}
                  onClick={() => setDeleteOpen(true)}
                >
                  {t("workspaces:deleteWorkspace")}
                </Button>
              ) : (
                <PermissionButton
                  capability="workspace.delete"
                  type="primary"
                  danger
                  icon={<DeleteOutlined />}
                >
                  {t("workspaces:deleteWorkspace")}
                </PermissionButton>
              )}
              {canDelete && deleteDisabledReason ? (
                <div className="workspace-action-feedback">
                  <Typography.Text className="workspace-action-reason" type="secondary">
                    {deleteDisabledReason}
                  </Typography.Text>
                  {deletionImpactError ? (
                    <Button type="link" size="small" onClick={() => void loadDeletionImpact()}>
                      {t("workspaces:retryDeletionCheck")}
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </Card>

      <Modal
        title={t("workspaces:transferOwnershipTitle")}
        open={transferOpen}
        okText={t("workspaces:transferOwnership")}
        okButtonProps={{ disabled: !transferTarget || eligibleTransferMembers.length === 0 }}
        confirmLoading={transferSubmitting}
        onOk={() => void handleTransfer()}
        onCancel={() => {
          setTransferOpen(false);
          setTransferTarget(undefined);
        }}
        destroyOnHidden
      >
        <div className="workspace-dialog-content">
          <Typography.Paragraph type="secondary">
            {t("workspaces:transferDialogDescription")}
          </Typography.Paragraph>
          {membersError ? (
            <Alert
              type="warning"
              showIcon
              message={t("workspaces:couldNotLoadEligible")}
              description={membersError}
              action={<Button onClick={() => void loadMembers()}>{t("common:retry")}</Button>}
            />
          ) : (
            <Select
              aria-label={t("workspaces:newOwner")}
              placeholder={membersLoading ? t("workspaces:loadingMembersShort") : t("workspaces:selectActiveMember")}
              loading={membersLoading}
              value={transferTarget}
              onChange={setTransferTarget}
              options={eligibleTransferMembers.map((member) => ({
                value: member.userId,
                label: `${member.name || member.email} — ${member.email}`,
              }))}
              style={{ width: "100%" }}
              notFoundContent={membersLoading ? null : t("workspaces:noEligibleMembers")}
            />
          )}
        </div>
      </Modal>

      <Modal
        title={t("workspaces:deleteWorkspaceTitle")}
        open={deleteOpen}
        okText={t("workspaces:deleteWorkspace")}
        okButtonProps={{ danger: true, disabled: !deleteNameMatches || deleteDisabledReason !== null }}
        confirmLoading={deleteSubmitting}
        onOk={() => void handleDelete()}
        onCancel={() => {
          setDeleteOpen(false);
          setDeleteConfirmation("");
        }}
        destroyOnHidden
      >
        <div className="workspace-dialog-content">
          <Alert
            type="error"
            showIcon
            message={t("workspaces:actionCannotUndo")}
            description={t("workspaces:deletionNoCascade")}
          />
          <Typography.Text>
            {t("workspaces:typeToConfirm", { name: currentWorkspace.name })}
          </Typography.Text>
          <Input
            aria-label={t("workspaces:nameConfirmation")}
            autoComplete="off"
            placeholder={currentWorkspace.name}
            value={deleteConfirmation}
            onChange={(event) => setDeleteConfirmation(event.target.value)}
          />
        </div>
      </Modal>
    </div>
  );
}
