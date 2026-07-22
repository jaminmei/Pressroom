import { lazy } from "react";
import { createBrowserRouter, redirect, type RouteObject } from "react-router-dom";

import { renderLazyRoute } from "@/app/lazyRoute";
import AppLayout from "@/components/Layout/AppLayout";
import LoginPage from "@/features/auth/components/LoginPage";
import ProtectedRoute from "@/features/auth/components/ProtectedRoute";
import RegisterPage from "@/features/auth/components/RegisterPage";
import WorkflowEditor from "@/features/workflow-editor/components/WorkflowEditor";

const WorkflowStudioPage = lazy(() => import("@/features/workflow-studio/components/WorkflowStudioPage"));
const PersistedWorkflowEditorPage = lazy(
  () => import("@/features/workflow-studio/components/PersistedWorkflowEditorPage")
);
const WorkflowApiAccessPage = lazy(
  () => import("@/features/api-access/components/WorkflowApiAccessPage")
);
const TemplateCenterPage = lazy(() => import("@/features/template-center/components/TemplateCenterPage"));
const SettingsPage = lazy(() => import("@/features/settings/components/SettingsPage"));

const WorkspaceSettingsPage = lazy(() => import("@/features/workspaces/components/WorkspaceSettingsPage"));
const WorkspaceOverviewPage = lazy(() => import("@/features/workspaces/components/WorkspaceOverviewPage"));
const WorkspaceMembersPage = lazy(() => import("@/features/workspaces/components/WorkspaceMembersPage"));
const WorkspaceProvidersPage = lazy(() => import("@/features/workspaces/components/WorkspaceProvidersPage"));
const WorkspaceAuditPage = lazy(() => import("@/features/workspaces/components/WorkspaceAuditPage"));
const WorkspaceGeneralPage = lazy(() => import("@/features/workspaces/components/WorkspaceGeneralPage"));

const ResultPage = lazy(() => import("@/features/result/components/ResultPage"));

const ProjectsListPage = lazy(() => import("@/features/projects/components/ProjectsListPage"));
const ProjectWorkspacePage = lazy(() => import("@/features/projects/components/ProjectWorkspacePage"));
const RunWorkflowPage = lazy(() => import("@/features/projects/components/RunWorkflowPage"));

export const appRoutes: RouteObject[] = [
  {
    path: "/login",
    element: <LoginPage />
  },
  {
    path: "/register",
    element: <RegisterPage />
  },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        index: true,
        element: <WorkflowEditor />
      },
      {
        path: "studio",
        element: renderLazyRoute(WorkflowStudioPage)
      },
      {
        path: "workflows/:workflowId",
        element: renderLazyRoute(PersistedWorkflowEditorPage)
      },
      {
        path: "workflows/:workflowId/api-access",
        element: renderLazyRoute(WorkflowApiAccessPage)
      },
      {
        path: "legacy/upload",
        loader: () => redirect("/")
      },
      {
        path: "legacy/results/:taskId",
        loader: ({ params }) => redirect(`/tasks/${params.taskId}/results`)
      },
      {
        path: "tasks/:taskId/results",
        element: renderLazyRoute(ResultPage)
      },
      {
        path: "templates",
        element: renderLazyRoute(TemplateCenterPage)
      },
      {
        path: "settings",
        element: renderLazyRoute(SettingsPage)
      },
      {
        path: "settings/workspace",
        element: renderLazyRoute(WorkspaceSettingsPage),
        children: [
          { index: true, element: renderLazyRoute(WorkspaceOverviewPage) },
          { path: "members", element: renderLazyRoute(WorkspaceMembersPage) },
          { path: "providers", element: renderLazyRoute(WorkspaceProvidersPage) },
          { path: "audit", element: renderLazyRoute(WorkspaceAuditPage) },
          { path: "general", element: renderLazyRoute(WorkspaceGeneralPage) }
        ]
      },
      {
        path: "settings/engines",
        loader: () => redirect("/settings")
      },
      {
        path: "settings/providers",
        loader: () => redirect("/settings")
      },
      {
        path: "projects",
        loader: () => redirect("/database")
      },
      {
        path: "projects/:projectId",
        loader: ({ params }) => redirect(`/database/${params.projectId}`)
      },
      {
        path: "database",
        element: renderLazyRoute(ProjectsListPage)
      },
      {
        path: "database/:projectId",
        element: renderLazyRoute(ProjectWorkspacePage)
      },
      {
        path: "database/:projectId/run",
        element: renderLazyRoute(RunWorkflowPage)
      }
    ]
  },
  {
    path: "/projects/:projectId/run",
    loader: ({ params }) => redirect(`/database/${params.projectId}/run`)
  }
];

export const router = createBrowserRouter(appRoutes);
