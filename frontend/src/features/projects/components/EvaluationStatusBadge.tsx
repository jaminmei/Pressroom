import { Tag } from "antd";
import { useTranslation } from "react-i18next";

import { getEvaluationStatusDescriptor } from "@/features/projects/evaluationStatusLabels";

export interface EvaluationStatusBadgeProps {
  readonly status: string;
}

export function EvaluationStatusBadge({ status }: EvaluationStatusBadgeProps) {
  const { t } = useTranslation("common");
  const { color, label } = getEvaluationStatusDescriptor(status);
  return <Tag color={color}>{t(`statuses.${status}`, { defaultValue: label })}</Tag>;
}
