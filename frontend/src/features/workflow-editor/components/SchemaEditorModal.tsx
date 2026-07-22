import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const { Text } = Typography;
const { TextArea } = Input;

const DEFAULT_SCHEMA = `{
  "name": "Schema",
  "description": "A description of the schema",
  "schema": {
    "type": "object",
    "properties": {}
  },
  "strict": false
}`;

interface SchemaEditorModalProps {
  open: boolean;
  initialValue?: string;
  onSave: (schema: string) => void;
  onCancel: () => void;
}

export default function SchemaEditorModal({
  open,
  initialValue,
  onSave,
  onCancel
}: SchemaEditorModalProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const [schema, setSchema] = useState(initialValue ?? DEFAULT_SCHEMA);
  const [error, setError] = useState<string | null>(null);

  const validateAndSave = () => {
    if (!schema.trim()) {
      onSave("");
      return;
    }

    try {
      JSON.parse(schema);
      setError(null);
      onSave(schema);
    } catch (e) {
      setError(t("editorText.invalidJson", { error: e instanceof Error ? e.message : String(e) }));
    }
  };

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setSchema(initialValue ?? DEFAULT_SCHEMA);
      setError(null);
    }
  }, [open, initialValue]);

  return (
    <Modal
      title={t("editorText.editOutputSchema")}
      open={open}
      onCancel={onCancel}
      width={700}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common:cancel")}
        </Button>,
        <Button key="save" type="primary" onClick={validateAndSave}>
          {t("common:save")}
        </Button>
      ]}
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <div>
          <Text strong>{t("editorText.jsonSchema")}</Text>
          <TextArea
            value={schema}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
              setSchema(e.target.value);
              setError(null);
            }}
            rows={20}
            style={{
              fontFamily: "monospace",
              marginTop: 4,
              ...(error ? { borderColor: "#ff4d4f" } : {})
            }}
            placeholder='{"name": "Schema", "description": "...", "schema": {"type": "object", "properties": {...}}, "strict": false}'
          />
        </div>

        {error && (
          <Alert
            message={t("editorText.schemaError")}
            description={error}
            type="error"
            showIcon
          />
        )}

        <Alert
          message={t("editorText.schemaGuide")}
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              <li><strong>name</strong>: {t("editorText.schemaNameHelp")}</li>
              <li><strong>description</strong>: {t("editorText.schemaDescriptionHelp")}</li>
              <li><strong>schema.properties</strong>: {t("editorText.schemaPropertiesHelp")}</li>
              <li><strong>strict</strong>: {t("editorText.schemaStrictHelp")}</li>
              <li><strong>{t("editorText.schemaPropertyPrefix")}</strong>: searchTerm, alias, description</li>
            </ul>
          }
          type="info"
        />
      </Space>
    </Modal>
  );
}
