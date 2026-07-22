import { Button } from "antd";
import { useTranslation } from "react-i18next";

interface ImportExportBarProps {
  onImport: (file: File) => void;
  onClearRecent: () => void;
}

export default function ImportExportBar({ onImport, onClearRecent }: ImportExportBarProps) {
  const { t } = useTranslation("templates");
  return (
    <div className="template-import-export-bar">
      <label className="template-import-label">
        <span className="template-import-label-copy">
          <span className="template-import-label-title">{t("importJson")}</span>
          <span className="template-import-label-subtitle">{t("importSubtitle")}</span>
        </span>
        <input
          accept="application/json,.json"
          data-testid="import-json-input"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              onImport(file);
            }
            event.target.value = "";
          }}
          type="file"
        />
      </label>
      <Button className="template-import-clear-btn" onClick={onClearRecent}>
        {t("clearRecent")}
      </Button>
    </div>
  );
}
