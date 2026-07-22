import { Alert, Button, Empty, Flex, Spin } from "antd";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { NewWorkspaceDialog } from "@/features/workspaces/components/NewWorkspaceDialog";
import { canAuthenticatedGlobal } from "@/services/workspaceApi";
import { useAuthStore } from "@/stores/authStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { CreateWorkspaceRequest } from "@/types/workspace";

interface ProtectedRouteProps {
  children?: ReactNode;
}

function buildCurrentRoute(pathname: string, search: string, hash: string): string {
  return `${pathname}${search}${hash}`;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { t } = useTranslation(["auth", "common", "workspaces"]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const location = useLocation();
  const status = useAuthStore((state) => state.status);
  const isHydrating = useAuthStore((state) => state.isHydrating);
  const shouldRememberRedirect = useAuthStore((state) => state.shouldRememberRedirect);
  const hydrateSession = useAuthStore((state) => state.hydrateSession);
  const rememberIntendedRoute = useAuthStore((state) => state.rememberIntendedRoute);
  const allowRedirectCapture = useAuthStore((state) => state.allowRedirectCapture);
  const workspaceStatus = useWorkspaceStore((state) => state.status);
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const workspaceError = useWorkspaceStore((state) => state.error);
  const hydrateWorkspaceSession = useWorkspaceStore((state) => state.hydrateWorkspaceSession);
  const createWorkspace = useWorkspaceStore((state) => state.createWorkspace);

  useEffect(() => {
    if (status === "unknown" && !isHydrating) {
      void hydrateSession();
    }
  }, [hydrateSession, isHydrating, status]);

  useEffect(() => {
    if (status === "authenticated" && workspaceStatus === "idle") {
      void hydrateWorkspaceSession();
    }
  }, [hydrateWorkspaceSession, status, workspaceStatus]);

  if (status === "unknown" || isHydrating) {
    return (
      <Flex align="center" data-testid="protected-route-loading" gap={12} justify="center" style={{ minHeight: 320 }} vertical>
        <Spin size="large" />
        <span>{t("auth:authenticating")}</span>
      </Flex>
    );
  }

  if (status !== "authenticated") {
    const target = buildCurrentRoute(location.pathname, location.search, location.hash);
    if (shouldRememberRedirect) {
      rememberIntendedRoute(target);
    } else {
      allowRedirectCapture();
    }

    return <Navigate replace state={{ from: target }} to="/login" />;
  }

  if (workspaceStatus === "idle" || workspaceStatus === "loading") {
    return (
      <Flex
        align="center"
        data-testid="workspace-bootstrap-loading"
        gap={12}
        justify="center"
        style={{ minHeight: 320 }}
        vertical
      >
        <Spin size="large" />
        <span>{t("workspaces:loadingWorkspace")}</span>
      </Flex>
    );
  }

  if (workspaceStatus === "error") {
    return (
      <Flex align="center" justify="center" style={{ minHeight: 320 }}>
        <Alert
          action={
            <Button
              data-testid="workspace-bootstrap-retry"
              onClick={() => void hydrateWorkspaceSession()}
              type="primary"
            >
              {t("common:retry")}
            </Button>
          }
          data-testid="workspace-bootstrap-error"
          description={workspaceError}
          message={t("workspaces:loadFailed")}
          showIcon
          type="error"
        />
      </Flex>
    );
  }

  if (currentWorkspace === null) {
    const canCreateWorkspace = canAuthenticatedGlobal("workspace.create");
    const handleCreateWorkspace = async (payload: CreateWorkspaceRequest) => {
      setCreatingWorkspace(true);
      try {
        await createWorkspace(payload);
        setCreateDialogOpen(false);
      } finally {
        setCreatingWorkspace(false);
      }
    };

    return (
      <>
        <Flex align="center" data-testid="workspace-no-workspace" justify="center" style={{ minHeight: 320 }}>
          <Empty
            description={t("workspaces:noAvailableWorkspace")}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            {canCreateWorkspace ? (
              <Button onClick={() => setCreateDialogOpen(true)} type="primary">
                {t("workspaces:createWorkspace")}
              </Button>
            ) : null}
          </Empty>
        </Flex>
        {createDialogOpen ? (
          <NewWorkspaceDialog
            onCancel={() => setCreateDialogOpen(false)}
            onSubmit={handleCreateWorkspace}
            open
            submitting={creatingWorkspace}
          />
        ) : null}
      </>
    );
  }

  return children ? <>{children}</> : <Outlet />;
}
