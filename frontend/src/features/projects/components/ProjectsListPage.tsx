import {
  AppstoreOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  FolderOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import { Alert, Button, Dropdown, Empty, Input, Modal, Spin, Typography } from "antd";
import { createElement, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { ProjectsIcon } from "@/components/Icons";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { useProjectsList } from "@/features/projects/hooks/useProjectsList";
import { getDatabaseBasePath } from "@/features/projects/utils/databaseBasePath";
import { usePermission } from "@/hooks/usePermission";
import { formatDateTime } from "@/i18n/format";
import { useLanguage } from "@/i18n/useLanguage";

const { Title, Text, Paragraph } = Typography;

interface CreateForm {
  name: string;
  description: string;
}

interface RenameForm {
  id: string;
  name: string;
}

export default function ProjectsListPage() {
  const { t } = useTranslation(["common", "projects"]);
  const { language } = useLanguage();
  const { can } = usePermission();
  const navigate = useNavigate();
  const location = useLocation();
  const basePath = getDatabaseBasePath(location.pathname);
  const {
    items,
    loading,
    error,
    query,
    setQuery,
    clearQuery,
    refresh,
    viewMode,
    setViewMode,
    createProject,
    deleteProject,
    renameProject,
    duplicateProject,
  } = useProjectsList();

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>({ name: "", description: "" });
  const [creating, setCreating] = useState(false);

  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [renameForm, setRenameForm] = useState<RenameForm>({ id: "", name: "" });
  const [renaming, setRenaming] = useState(false);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  const openCreateModal = useCallback(() => {
    setCreateForm({ name: "", description: "" });
    setCreateModalOpen(true);
  }, []);

  const closeCreateModal = useCallback(() => {
    if (creating) return;
    setCreateModalOpen(false);
    setCreateForm({ name: "", description: "" });
  }, [creating]);

  useEffect(() => {
    const handler = () => openCreateModal();
    window.addEventListener("project:create-request", handler);
    return () => window.removeEventListener("project:create-request", handler);
  }, [openCreateModal]);

  const submitCreate = useCallback(async () => {
    const normalizedName = createForm.name.trim();
    if (!normalizedName) return;

    setCreating(true);
    try {
      const project = await createProject(normalizedName, createForm.description.trim() || undefined);
      setCreateModalOpen(false);
      setCreateForm({ name: "", description: "" });
      navigate(`${basePath}/${project.id}`);
    } finally {
      setCreating(false);
    }
  }, [basePath, createForm, createProject, navigate]);

  const handleCardClick = useCallback(
    (id: string) => {
      navigate(`${basePath}/${id}`);
    },
    [navigate, basePath],
  );

  const openRenameModal = useCallback(
    (id: string, currentName: string) => {
      setRenameForm({ id, name: currentName });
      setRenameModalOpen(true);
    },
    [],
  );

  const closeRenameModal = useCallback(() => {
    if (renaming) return;
    setRenameModalOpen(false);
    setRenameForm({ id: "", name: "" });
  }, [renaming]);

  const submitRename = useCallback(async () => {
    const normalizedName = renameForm.name.trim();
    if (!normalizedName || !renameForm.id) return;

    setRenaming(true);
    try {
      await renameProject(renameForm.id, normalizedName);
      setRenameModalOpen(false);
      setRenameForm({ id: "", name: "" });
    } finally {
      setRenaming(false);
    }
  }, [renameForm, renameProject]);

  const handleDuplicate = useCallback(
    async (id: string) => {
      await duplicateProject(id);
    },
    [duplicateProject],
  );

  const handleDelete = useCallback(
    (id: string, name: string) => {
      Modal.confirm({
        title: t("projects:deleteDatabase"),
        content: t("projects:deleteNamedConfirm", { name }),
        okText: t("common:delete"),
        cancelText: t("common:cancel"),
        okButtonProps: { danger: true, autoInsertSpace: false },
        cancelButtonProps: { autoInsertSpace: false },
        onOk: async () => {
          await deleteProject(id);
        },
      });
    },
    [deleteProject, t],
  );

  const buildContextMenu = useCallback(
    (id: string, name: string): MenuProps["items"] => [
      {
        key: "rename",
        label: t("projects:rename"),
        icon: <EditOutlined />,
        disabled: !can("database.update"),
        onClick: () => openRenameModal(id, name),
      },
      {
        key: "duplicate",
        label: t("projects:duplicate"),
        icon: <FileAddOutlined />,
        disabled: !can("database.create"),
        onClick: () => handleDuplicate(id),
      },
      {
        key: "archive",
        label: t("projects:archive"),
        icon: <FolderOutlined />,
      },
      { type: "divider" },
      {
        key: "delete",
        label: t("common:delete"),
        icon: <DeleteOutlined />,
        danger: true,
        disabled: !can("database.delete"),
        onClick: () => handleDelete(id, name),
      },
    ],
    [can, openRenameModal, handleDuplicate, handleDelete, t],
  );

  const isInitialLoading = loading && items.length === 0;
  const noResults = !loading && query.trim() && items.length === 0;
  const isEmpty = !loading && !query.trim() && items.length === 0;
  const hasProjects = items.length > 0;

  if (!can("database.view")) {
    return <Alert data-testid="projects-list-forbidden" message={t("projects:viewDenied")} showIcon type="warning" />;
  }

  return (
    <section className="projects-list-page" data-testid="projects-list-page">
      <header className="projects-list-welcome" data-testid="projects-list-welcome">
        <div className="projects-list-welcome-content">
          <Title level={2} style={{ margin: 0 }}>
            {t("projects:databases")}
          </Title>
          <Paragraph className="projects-list-welcome-desc" style={{ margin: 0 }}>
            {t("projects:databasesDescription")}
          </Paragraph>
        </div>
        <PermissionButton
          capability="database.create"
          data-testid="projects-list-create-button"
          icon={<PlusOutlined />}
          onClick={openCreateModal}
          size="large"
          type="primary"
        >
          {t("projects:createDatabase")}
        </PermissionButton>
      </header>

      {!isInitialLoading && !isEmpty && !error && (
        <div className="projects-list-toolbar" data-testid="projects-list-toolbar">
          <Input
            allowClear
            data-testid="projects-list-search"
            onChange={(e) => setQuery(e.target.value)}
            onClear={clearQuery}
            placeholder={t("projects:searchDatabases")}
            prefix={<SearchOutlined />}
            value={query}
          />
          <div className="projects-list-view-toggle">
            <Button
              data-testid="projects-list-view-grid"
              icon={<AppstoreOutlined />}
              onClick={() => setViewMode("grid")}
              type={viewMode === "grid" ? "primary" : "default"}
            />
            <Button
              data-testid="projects-list-view-list"
              icon={<UnorderedListOutlined />}
              onClick={() => setViewMode("list")}
              type={viewMode === "list" ? "primary" : "default"}
            />
          </div>
        </div>
      )}

      {error && (
        <Alert
          action={
            <Button
              data-testid="projects-list-retry"
              onClick={() => {
                void refresh();
              }}
              size="small"
            >
              {t("common:retry")}
            </Button>
          }
          data-testid="projects-list-error"
          message={error}
          showIcon
          type="error"
        />
      )}

      {isInitialLoading && (
        <div className="projects-list-loading" data-testid="projects-list-loading">
          <Spin size="large" />
        </div>
      )}

      {noResults && (
        <div className="projects-list-empty" data-testid="projects-list-empty-search">
          <Empty description={t("projects:noDatabaseMatch", { query })} />
          <Button data-testid="projects-list-clear-search" onClick={clearQuery} type="link">
            {t("projects:clearSearch")}
          </Button>
        </div>
      )}

      {isEmpty && (
        <div className="projects-list-empty" data-testid="projects-list-empty">
          <Empty description={t("projects:noDatabasesCreate")} />
        </div>
      )}

      {hasProjects && (
        <div
          className={`projects-list-grid ${viewMode === "list" ? "projects-list-grid--list" : ""}`}
          data-testid="projects-list-grid"
        >
          {items.map((project) => {
            const contextMenuItems = buildContextMenu(project.id, project.name);
            const isHovered = hoveredId === project.id;
            const isMenuActive = menuOpenId === project.id;

            return (
              <div
                className={`projects-list-item ${isHovered || isMenuActive ? "projects-list-item--hovered" : ""}`}
                data-testid={`projects-list-item-${project.id}`}
                key={project.id}
                onClick={() => handleCardClick(project.id)}
                onMouseEnter={() => setHoveredId(project.id)}
                onMouseLeave={() => setHoveredId(null)}
                role="button"
                tabIndex={0}
              >
                <div className="projects-list-item-icon">{createElement(ProjectsIcon, { size: 24 })}</div>

                <div className="projects-list-item-body">
                  <Text className="projects-list-item-name" strong>
                    {project.name}
                  </Text>
                  <Text className="projects-list-item-meta" type="secondary">
                    {t("projects:documentCount", { count: project.documentCount })}
                  </Text>
                  {viewMode === "list" && project.description && (
                    <Text className="projects-list-item-desc" type="secondary" ellipsis>
                      {project.description}
                    </Text>
                  )}
                </div>

                {viewMode === "list" && (
                  <Text className="projects-list-item-updated" type="secondary">
                    {formatDateTime(project.lastUpdated, language, { dateStyle: "medium" })}
                  </Text>
                )}

                <div
                  className={`projects-list-item-menu ${isHovered || isMenuActive ? "projects-list-item-menu--visible" : ""}`}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <Dropdown
                    menu={{ items: contextMenuItems }}
                    onOpenChange={(open) => setMenuOpenId(open ? project.id : null)}
                    placement="bottomRight"
                    trigger={["click"]}
                  >
                    <Button
                      aria-label={t("projects:actionsFor", { name: project.name })}
                      data-testid={`projects-list-menu-${project.id}`}
                      icon={<MoreOutlined />}
                      size="small"
                      type="text"
                    />
                  </Dropdown>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Modal
        cancelText={t("common:cancel")}
        confirmLoading={creating}
        data-testid="projects-list-create-modal"
        destroyOnHidden
        okButtonProps={{ autoInsertSpace: false, disabled: createForm.name.trim().length === 0 }}
        okText={t("common:create")}
        onCancel={closeCreateModal}
        onOk={() => {
          void submitCreate();
        }}
        open={createModalOpen}
        title={t("projects:createDatabase")}
      >
        <div style={{ display: "grid", gap: 12 }}>
          <label>
            <div style={{ marginBottom: 4 }}>{t("common:name")} *</div>
            <Input
              autoFocus
              data-testid="projects-list-create-name"
              maxLength={120}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, name: e.target.value }))}
              onPressEnter={() => {
                void submitCreate();
              }}
              placeholder={t("projects:enterDatabaseName")}
              value={createForm.name}
            />
          </label>
          <label>
            <div style={{ marginBottom: 4 }}>{t("common:description")} ({t("common:optional")})</div>
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 5 }}
              data-testid="projects-list-create-description"
              maxLength={300}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder={t("projects:databaseDescriptionPlaceholder")}
              value={createForm.description}
            />
          </label>
        </div>
      </Modal>

      <Modal
        cancelText={t("common:cancel")}
        confirmLoading={renaming}
        data-testid="projects-list-rename-modal"
        destroyOnHidden
        okButtonProps={{ autoInsertSpace: false, disabled: renameForm.name.trim().length === 0 }}
        okText={t("common:save")}
        onCancel={closeRenameModal}
        onOk={() => {
          void submitRename();
        }}
        open={renameModalOpen}
        title={t("projects:renameDatabase")}
      >
        <label>
          <div style={{ marginBottom: 4 }}>{t("projects:databaseName")}</div>
          <Input
            autoFocus
            data-testid="projects-list-rename-name"
            maxLength={120}
            onChange={(e) => setRenameForm((prev) => ({ ...prev, name: e.target.value }))}
            onPressEnter={() => {
              void submitRename();
            }}
            placeholder={t("projects:enterDatabaseName")}
            value={renameForm.name}
          />
        </label>
      </Modal>
    </section>
  );
}
