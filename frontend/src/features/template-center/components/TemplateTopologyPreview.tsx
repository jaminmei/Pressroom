export type TemplateTopologyVariant = "quick-convert" | "custom-workflow" | "multi-engine-compare";

interface TemplateTopologyPreviewProps {
  variant: TemplateTopologyVariant;
}

function renderQuickConvert() {
  return (
    <>
      <line className="template-topology-line" x1="44" x2="104" y1="44" y2="44" />
      <line className="template-topology-line" x1="136" x2="196" y1="44" y2="44" />
      <rect className="template-topology-node is-input" height="24" rx="6" width="30" x="14" y="32" />
      <circle className="template-topology-node is-engine" cx="120" cy="44" r="14" />
      <rect className="template-topology-node is-output" height="24" rx="6" width="30" x="196" y="32" />
    </>
  );
}

function renderCustomWorkflow() {
  return (
    <>
      <line className="template-topology-line" x1="34" x2="90" y1="44" y2="44" />
      <line className="template-topology-line" x1="120" x2="168" y1="44" y2="24" />
      <line className="template-topology-line" x1="198" x2="224" y1="24" y2="24" />
      <rect className="template-topology-node is-input" height="24" rx="6" width="24" x="10" y="32" />
      <circle className="template-topology-node is-engine" cx="106" cy="44" r="14" />
      <rect className="template-topology-node is-transform" height="20" rx="5" width="30" x="168" y="14" />
      <rect className="template-topology-node is-output" height="24" rx="6" width="24" x="224" y="12" />
    </>
  );
}

function renderMultiEngineCompare() {
  return (
    <>
      <line className="template-topology-line" x1="34" x2="90" y1="44" y2="28" />
      <line className="template-topology-line" x1="34" x2="90" y1="44" y2="60" />
      <line className="template-topology-line" x1="120" x2="180" y1="28" y2="28" />
      <line className="template-topology-line" x1="120" x2="180" y1="60" y2="60" />
      <rect className="template-topology-node is-input" height="24" rx="6" width="24" x="10" y="32" />
      <circle className="template-topology-node is-engine" cx="106" cy="28" r="12" />
      <circle className="template-topology-node is-engine" cx="106" cy="60" r="12" />
      <rect className="template-topology-node is-output" height="18" rx="5" width="24" x="180" y="19" />
      <rect className="template-topology-node is-output" height="18" rx="5" width="24" x="180" y="51" />
    </>
  );
}

export default function TemplateTopologyPreview({ variant }: TemplateTopologyPreviewProps) {
  const title =
    variant === "quick-convert"
      ? "Quick Convert topology"
      : variant === "custom-workflow"
        ? "Custom Workflow topology"
        : "Multi-Engine Compare topology";

  return (
    <svg
      aria-label={title}
      className="template-topology-svg"
      data-testid={`template-topology-${variant}`}
      role="img"
      viewBox="0 0 240 88"
    >
      <rect className="template-topology-bg" height="88" rx="10" width="240" x="0" y="0" />
      {variant === "quick-convert" ? renderQuickConvert() : null}
      {variant === "custom-workflow" ? renderCustomWorkflow() : null}
      {variant === "multi-engine-compare" ? renderMultiEngineCompare() : null}
    </svg>
  );
}
