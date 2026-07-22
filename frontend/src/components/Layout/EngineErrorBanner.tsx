import { Alert } from "antd";

import { useUIStore } from "@/stores/uiStore";

export default function EngineErrorBanner() {
  const engineStatuses = useUIStore((state) => state.engineStatuses);
  const errorEntries = Object.entries(engineStatuses).filter(
    ([, status]) => status !== "healthy"
  );

  if (errorEntries.length === 0) {
    return null;
  }

  const names = errorEntries.map(([name]) => name).join(", ");
  return (
    <Alert
      banner
      message={`Engine issues: ${names}`}
      showIcon
      type="error"
    />
  );
}
