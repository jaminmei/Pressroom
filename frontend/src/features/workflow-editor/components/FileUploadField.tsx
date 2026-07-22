import { DeleteOutlined, InboxOutlined } from "@ant-design/icons";
import { Button, Space, Typography, Upload, message } from "antd";
import type { UploadProps } from "antd";
import type { RcFile } from "antd/es/upload";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { validateUploadFile } from "@/features/workflow-editor/components/fileUploadValidation";

export interface FileUploadFieldProps {
  accept?: string[];
  maxSizeMb?: number;
  file: File | null;
  onFileChange: (file: File | null) => void;
}

export default function FileUploadField({
  accept = [],
  maxSizeMb = 50,
  file,
  onFileChange
}: FileUploadFieldProps) {
  const { t } = useTranslation(["workflows", "common"]);
  const [displayFile, setDisplayFile] = useState<File | null>(file);

  useEffect(() => {
    setDisplayFile(file);
  }, [file]);

  const uploadProps: UploadProps = {
    accept: accept.join(","),
    multiple: false,
    showUploadList: false,
    beforeUpload: (candidate: RcFile) => {
      const validationError = validateUploadFile(candidate as File, accept, maxSizeMb, t);
      if (validationError) {
        message.error(validationError);
        return Upload.LIST_IGNORE;
      }

      setDisplayFile(candidate as File);
      onFileChange(candidate as File);
      return Upload.LIST_IGNORE;
    }
  };

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Upload.Dragger {...uploadProps} data-testid="file-upload-field">
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <Typography.Text>{t("editorText.uploadDrop")}</Typography.Text>
      </Upload.Dragger>

      {displayFile ? (
        <Space align="center" style={{ justifyContent: "space-between", width: "100%" }}>
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{displayFile.name}</Typography.Text>
            <Typography.Text type="secondary">{(displayFile.size / (1024 * 1024)).toFixed(2)} MB</Typography.Text>
          </Space>
          <Button
            aria-label={t("editorText.removeFile")}
            icon={<DeleteOutlined />}
            onClick={() => {
              setDisplayFile(null);
              onFileChange(null);
            }}
            size="small"
          >
            {t("common:remove")}
          </Button>
        </Space>
      ) : null}

      <Typography.Text type="secondary">{t("editorText.uploadStaged")}</Typography.Text>
    </Space>
  );
}
