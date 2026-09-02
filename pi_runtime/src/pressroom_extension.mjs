// Built-in PressRoom Pi Extension. This factory is loaded explicitly while
// ambient extension discovery remains disabled.

import toolCatalog from "./pressroom_tool_catalog.generated.json" with { type: "json" };

const MAX_EXECUTOR_RESULT_BYTES = 1024 * 1024;

const TOOL_SPECS = Object.freeze(toolCatalog.tools);

async function executeTool(config, spec, toolCallId, args, signal) {
  const response = await fetch(config.gatewayUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-DocConv-Tool-Grant": config.gatewayGrant,
    },
    body: JSON.stringify({
      catalog_version: config.catalogVersion,
      operation: spec.operation,
      args,
      tool_call_id: toolCallId,
    }),
    signal,
  });
  const raw = await response.text();
  if (Buffer.byteLength(raw) > MAX_EXECUTOR_RESULT_BYTES) {
    throw new Error("PressRoom tool result exceeded the extension limit");
  }
  let envelope;
  try {
    envelope = JSON.parse(raw);
  } catch {
    throw new Error("PressRoom Agent Tool Gateway returned invalid JSON");
  }
  const ok = response.ok && envelope?.ok === true;
  const safeText = JSON.stringify(envelope);
  return {
    content: [{ type: "text", text: safeText }],
    details: envelope,
    isError: !ok,
  };
}

export function createPressroomExtension(config) {
  if (
    typeof config?.gatewayUrl !== "string"
    || typeof config?.gatewayGrant !== "string"
    || typeof config?.catalogVersion !== "string"
  ) {
    throw new TypeError("PressRoom extension configuration is incomplete");
  }
  if (config.catalogVersion !== toolCatalog.catalog_version) {
    throw new TypeError("PressRoom extension catalog version does not match its artifact");
  }
  return (pi) => {
    for (const spec of TOOL_SPECS) {
      pi.registerTool({
        name: spec.name,
        label: spec.label,
        description: spec.description,
        promptSnippet: spec.description,
        parameters: spec.parameters,
        executionMode: "sequential",
        execute: (toolCallId, args, signal) =>
          executeTool(config, spec, toolCallId, args, signal),
      });
    }
  };
}

export const PRESSROOM_TOOL_NAMES = Object.freeze(TOOL_SPECS.map((tool) => tool.name));
