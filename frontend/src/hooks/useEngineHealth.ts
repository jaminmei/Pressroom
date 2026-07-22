import { useEffect } from "react";

import { apiClient } from "@/services/api";
import { useUIStore } from "@/stores/uiStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";

interface EngineHealthInfo {
  status: "healthy" | "unavailable" | "degraded" | string;
  latency_ms?: number;
}

interface EngineHealthArrayItem {
  name: string;
  status: string;
  latency_ms?: number;
}

interface HealthResponse {
  status: string;
  engines?: EngineHealthArrayItem[] | Record<string, EngineHealthInfo | string>;
  components?: {
    engines?: Record<string, EngineHealthInfo | string>;
  };
}

function normalizeEngineHealthInfo(info: EngineHealthInfo | string): EngineHealthInfo {
  if (typeof info === "string") {
    return { status: info };
  }
  return info;
}

function extractEngines(response: HealthResponse): Record<string, EngineHealthInfo> {
  const raw = response.engines;

  // Backend /health returns engines as an array: [{name, status, latency_ms}, ...]
  // Convert to a name-keyed dict before processing.
  let rawEngines: Record<string, EngineHealthInfo | string>;
  if (Array.isArray(raw)) {
    rawEngines = Object.fromEntries(
      raw.map(({ name, ...rest }) => [name, rest as EngineHealthInfo])
    );
  } else {
    rawEngines = raw ?? response.components?.engines ?? {};
  }

  return Object.fromEntries(
    Object.entries(rawEngines).map(([engineName, info]) => [engineName, normalizeEngineHealthInfo(info)])
  );
}

export function useEngineHealth(): void {
  const setEngineStatuses = useUIStore((state) => state.setEngineStatuses);
  const contextGeneration = useWorkspaceStore((state) => state.contextGeneration);

  useEffect(() => {
    let isMounted = true;
    setEngineStatuses({});

    async function fetchHealth() {
      try {
        const response = await apiClient.get<HealthResponse>("/health");
        if (!isMounted) {
          return;
        }

        const extracted = extractEngines(response.data);
        setEngineStatuses(
          Object.fromEntries(Object.entries(extracted).map(([name, info]) => [name, info.status]))
        );
      } catch {
        if (!isMounted) {
          return;
        }

        setEngineStatuses({});
      }
    }

    void fetchHealth();
    const timer = window.setInterval(() => {
      void fetchHealth();
    }, 30000);

    return () => {
      isMounted = false;
      window.clearInterval(timer);
      setEngineStatuses({});
    };
  }, [contextGeneration, setEngineStatuses]);
}
