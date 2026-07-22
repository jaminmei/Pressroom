import { UploadOutlined } from "@ant-design/icons";
import { message, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listDocuments, uploadGroundTruth } from "@/services/projectApi";
import type { GTVersion, ProjectDocument, RunResult } from "@/types/project";
import { formatRelativeTime } from "@/utils/dateFormat";
import { PermissionButton } from "@/components/Permissions/PermissionButton";
import { usePermission } from "@/hooks/usePermission";

interface GroundTruthViewProps {
  projectId: string;
  runResults?: RunResult[];
}

const GT_DOC_STATUS_CONFIG: Record<string, { color: string; labelKey: string }> = {
  approved: { color: "green", labelKey: "approved" },
  pending: { color: "gold", labelKey: "pending" },
  none: { color: "default", labelKey: "missing" },
};

export default function GroundTruthView({
  projectId,
  runResults,
}: GroundTruthViewProps) {
  const { t } = useTranslation("projects");
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const { can } = usePermission();
  const requestIdRef = useRef(0);
  const gtFileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    void (async () => {
      try {
        const docs = await listDocuments(projectId);
        if (requestId !== requestIdRef.current) return;
        setDocuments(docs);
      } catch {
        if (requestId !== requestIdRef.current) return;
        setDocuments([]);
      }
    })();
  }, [projectId]);

  const acceptedDocIds = useMemo(
    () =>
      new Set(
        (runResults ?? [])
          .filter((r) => r.acceptedAsGT)
          .map((r) => r.documentId),
      ),
    [runResults],
  );

  const effectiveDocs = useMemo(
    () =>
      documents.map((d) =>
        acceptedDocIds.has(d.id) ? { ...d, gtStatus: "approved" as const } : d,
      ),
    [documents, acceptedDocIds],
  );

  const gtVersions: GTVersion[] = useMemo(() => {
    const docsWithGT = effectiveDocs.filter((d) => d.gtStatus === "approved");
    if (docsWithGT.length === 0) return [];
    return [
      {
        id: "gt-current",
        projectId,
        version: 1,
        createdAt: new Date().toISOString(),
        documentCount: docsWithGT.length,
        source: "accepted_run" as const,
      },
    ];
  }, [effectiveDocs, projectId]);

  const displayVersion = gtVersions[0] ?? null;

  const approved = useMemo(
    () => effectiveDocs.filter((d) => d.gtStatus === "approved").length,
    [effectiveDocs],
  );
  const pending = useMemo(
    () => effectiveDocs.filter((d) => d.gtStatus === "pending").length,
    [effectiveDocs],
  );
  const missing = useMemo(
    () => effectiveDocs.filter((d) => d.gtStatus === "none").length,
    [effectiveDocs],
  );

  const handleUploadGT = useCallback(() => {
    if (!can("ground_truth.edit") || !selectedDocId) {
      void message.warning(t("selectDocumentFirst"));
      return;
    }
    gtFileInputRef.current?.click();
  }, [can, selectedDocId, t]);

  const handleGTFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !selectedDocId) return;
      try {
        const content = await file.text();
        await uploadGroundTruth(projectId, selectedDocId, content);
        void message.success(t("gtUploaded"));
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : t("gtUploadFailed");
        void message.error(errorMsg);
      } finally {
        e.target.value = "";
      }
    },
    [projectId, selectedDocId, t],
  );

  const docColumns: TableColumnsType<ProjectDocument> = [
    {
      title: t("documents"),
      dataIndex: "filename",
      key: "filename",
      render: (name: string) => (
        <Typography.Text strong>{name}</Typography.Text>
      ),
    },
    {
      title: t("gtStatus"),
      dataIndex: "gtStatus",
      key: "gtStatus",
      width: 140,
      render: (status: string) => {
        const cfg =
          GT_DOC_STATUS_CONFIG[status] ?? GT_DOC_STATUS_CONFIG.none;
        return <Tag color={cfg.color}>{t(cfg.labelKey)}</Tag>;
      },
    },
  ];

  return (
    <div className="gt-view" data-testid="gt-view">
      <input
        ref={gtFileInputRef}
        type="file"
        accept=".json"
        style={{ display: "none" }}
        onChange={handleGTFileChange}
        data-testid="gt-file-input"
      />
      <div className="gt-view-header" data-testid="gt-view-header">
        <Typography.Title level={4} style={{ margin: 0 }}>
          {t("groundTruth")}
        </Typography.Title>
        <PermissionButton
          capability="ground_truth.edit"
          data-testid="btn-upload-gt"
          icon={<UploadOutlined />}
          onClick={handleUploadGT}
          type="primary"
        >
          {t("uploadGt")}
        </PermissionButton>
      </div>

      {displayVersion && (
        <div className="gt-view-current" data-testid="gt-view-current">
          <Typography.Text strong>
            {t("currentVersion", { version: displayVersion.version })}
          </Typography.Text>
          <Typography.Text
            type="secondary"
            style={{ display: "block", marginTop: 4 }}
          >
            {t("versionSummary", {
              time: formatRelativeTime(displayVersion.createdAt),
              documents: t("documentCount", { count: displayVersion.documentCount }),
              source: displayVersion.source === "manual" ? t("manualUpload") : t("acceptedFromRun")
            })}
          </Typography.Text>
        </div>
      )}

      <div className="gt-view-stats" data-testid="gt-view-stats">
        <div className="gt-view-stat">
          <span className="gt-view-stat-value gt-view-stat-value--approved">
            {approved}
          </span>
          <span className="gt-view-stat-label">{t("approved")}</span>
        </div>
        <div className="gt-view-stat">
          <span className="gt-view-stat-value gt-view-stat-value--pending">
            {pending}
          </span>
          <span className="gt-view-stat-label">{t("pending")}</span>
        </div>
        <div className="gt-view-stat">
          <span className="gt-view-stat-value gt-view-stat-value--missing">
            {missing}
          </span>
          <span className="gt-view-stat-label">{t("missing")}</span>
        </div>
      </div>

      <Typography.Text strong style={{ display: "block", marginBottom: 8 }}>
        {t("perDocumentGt")}
      </Typography.Text>
      <Table
        className="gt-view-doc-table"
        columns={docColumns}
        data-testid="gt-document-table"
        dataSource={effectiveDocs}
        pagination={false}
        onRow={(record) => ({ onClick: () => setSelectedDocId(record.id) })}
        rowKey="id"
        rowSelection={{
          type: "radio",
          selectedRowKeys: selectedDocId ? [selectedDocId] : [],
          onChange: (keys) => setSelectedDocId(keys[0] ? String(keys[0]) : null),
        }}
        size="small"
      />

      {gtVersions.length > 0 && (
        <>
          <Typography.Text
            strong
            style={{ display: "block", marginTop: 24, marginBottom: 8 }}
          >
            {t("versionTimeline")}
          </Typography.Text>
          <div className="gt-view-timeline" data-testid="gt-view-timeline">
            {gtVersions.map((ver, idx) => (
              <div className="gt-timeline-item" data-testid={`gt-version-${ver.version}`} key={ver.id}>
                <div className="gt-timeline-marker">
                  <div
                    className={`gt-timeline-dot ${idx === 0 ? "gt-timeline-dot--current" : ""}`}
                  />
                  {idx < gtVersions.length - 1 && (
                    <div className="gt-timeline-line" />
                  )}
                </div>
                <div className="gt-timeline-content">
                  <Typography.Text strong>
                    v{ver.version}
                    {idx === 0 ? ` (${t("current")})` : ""}
                  </Typography.Text>
                  <Typography.Text
                    type="secondary"
                    style={{ display: "block" }}
                  >
                    {t("versionSummary", {
                      time: formatRelativeTime(ver.createdAt),
                      documents: t("documentCount", { count: ver.documentCount }),
                      source: ver.source === "manual" ? t("manual") : t("acceptedRun")
                    })}
                  </Typography.Text>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
