import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useUIStore } from "@/stores/uiStore";

export function useDomainShortcuts() {
  const navigate = useNavigate();
  const location = useLocation();
  const lastWorkflowsRoute = useUIStore((s) => s.lastWorkflowsRoute);
  const lastDatabaseRoute = useUIStore((s) => s.lastDatabaseRoute);
  const setLastWorkflowsRoute = useUIStore((s) => s.setLastWorkflowsRoute);
  const setLastDatabaseRoute = useUIStore((s) => s.setLastDatabaseRoute);

  useEffect(() => {
    if (location.pathname.startsWith("/projects") || location.pathname.startsWith("/database")) {
      setLastDatabaseRoute(location.pathname.replace(/^\/projects/, "/database"));
    } else if (location.pathname !== "/login" && location.pathname !== "/register") {
      setLastWorkflowsRoute(location.pathname);
    }
  }, [location.pathname, setLastWorkflowsRoute, setLastDatabaseRoute]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
        return;
      }
      if (e.ctrlKey && e.key === "1") {
        e.preventDefault();
        navigate(lastWorkflowsRoute);
      } else if (e.ctrlKey && e.key === "2") {
        e.preventDefault();
        navigate(lastDatabaseRoute);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate, lastWorkflowsRoute, lastDatabaseRoute]);
}
