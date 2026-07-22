import { Input, message, Modal, Typography } from "antd";
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";
import { deleteDatabase, updateDatabaseSettings } from "@/services/projectApi";
import { isAxiosError } from "axios";

interface SettingsViewProps {
  projectName: string;
  projectDescription?: string;
  projectId: string;
}

function settingsErrorMessage(error: unknown, fallback: string, denied: string, inUse: string): string {
  if (!isAxiosError<{ message?: string }>(error)) return error instanceof Error ? error.message : fallback;
  if (error.response?.status === 403) return denied;
  if (error.response?.status === 409) return error.response.data?.message ?? inUse;
  return error.message || fallback;
}

export default function SettingsView({
  projectName,
  projectDescription = "",
  projectId,
}: SettingsViewProps) {
  const { t } = useTranslation(["common", "projects"]);
  const navigate = useNavigate();
  const { can } = usePermission();

  const [name, setName] = useState(projectName);
  const [description, setDescription] = useState(projectDescription);
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await updateDatabaseSettings(projectId, {
        name: name.trim(),
        description: description.trim(),
      });
      setName(updated.name);
      setDescription(updated.description ?? "");
      void message.success(t("projects:settingsSaved"));
    } catch (error) {
      if (!(error instanceof Error)) {
        void message.error(t("projects:saveSettingsFailed"));
        return;
      }
      void message.error(settingsErrorMessage(
        error,
        t("projects:saveSettingsFailed"),
        t("projects:settingsDenied"),
        t("projects:databaseInUse")
      ));
    } finally {
      setSaving(false);
    }
  }, [description, name, projectId, t]);

  const handleDelete = useCallback(() => {
    Modal.confirm({
      title: t("projects:deleteQuestion"),
      content: t("projects:deleteWarning"),
      okButtonProps: { danger: true },
      okText: t("common:delete"),
      onOk: async () => {
        try {
          await deleteDatabase(projectId);
          navigate("/database", { replace: true });
        } catch (error) {
          if (!(error instanceof Error)) {
            void message.error(t("projects:deleteFailed"));
            throw error;
          }
          void message.error(settingsErrorMessage(
            error,
            t("projects:deleteFailed"),
            t("projects:settingsDenied"),
            t("projects:databaseInUse")
          ));
          throw error;
        }
      },
    });
  }, [navigate, projectId, t]);

  return (
    <div className="settings-view" data-testid="settings-view">
      <Typography.Title data-testid="settings-title" level={4}>
        {t("projects:projectSettings")}
      </Typography.Title>

      <div className="settings-field" data-testid="settings-field-name">
        <Typography.Text strong>{t("projects:projectName")}</Typography.Text>
        <Input
          data-testid="input-project-name"
          disabled={!can("database.update")}
          onChange={(e) => setName(e.target.value)}
          style={{ marginTop: 4 }}
          value={name}
        />
      </div>

      <div
        className="settings-field"
        data-testid="settings-field-description"
        style={{ marginTop: 16 }}
      >
        <Typography.Text strong>{t("common:description")}</Typography.Text>
        <Input.TextArea
          data-testid="input-project-description"
          disabled={!can("database.update")}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          style={{ marginTop: 4 }}
          value={description}
        />
      </div>

      <div className="settings-actions" data-testid="settings-actions">
        <PermissionButton
          capability="database.update"
          data-testid="btn-save-settings"
          loading={saving}
          onClick={() => void handleSave()}
          type="primary"
        >
          {t("projects:saveChanges")}
        </PermissionButton>
      </div>

      <div
        className="settings-danger"
        data-testid="settings-danger"
        style={{ marginTop: 32 }}
      >
        <Typography.Title level={5} style={{ color: "var(--danger)" }}>
          {t("projects:dangerZone")}
        </Typography.Title>
        <Typography.Text type="secondary">
          {t("projects:permanentDelete")}
        </Typography.Text>
        <PermissionButton
          capability="database.delete"
          danger
          data-testid="btn-delete-project"
          onClick={handleDelete}
          style={{ display: "block", marginTop: 8 }}
          type="primary"
        >
          {t("projects:deleteDatabase")}
        </PermissionButton>
      </div>
    </div>
  );
}
