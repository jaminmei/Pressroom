import { DownloadOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useTranslation } from "react-i18next";

interface DownloadButtonProps {
  content: string;
  filename: string;
}

export default function DownloadButton({ content, filename }: DownloadButtonProps) {
  const { t } = useTranslation("workflows");
  const handleDownload = () => {
    const fileBlob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const objectUrl = URL.createObjectURL(fileBlob);

    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(objectUrl);
  };

  return (
    <Button icon={<DownloadOutlined />} onClick={handleDownload}>
      {t("resultText.downloadMarkdown")}
    </Button>
  );
}
