import assert from "node:assert/strict";
import test from "node:test";

import {
  createPressroomExtension,
  PRESSROOM_TOOL_NAMES,
} from "../src/pressroom_extension.mjs";
import toolCatalog from "../src/pressroom_tool_catalog.generated.json" with { type: "json" };

const EXPECTED_OPERATIONS = [
  "workflow.validate", "workflow.list", "workflow.get", "workflow.create",
  "workflow.update", "workflow.version.list", "workflow.version.get",
  "workflow.execute", "workflow.publish", "workflow.delete",
  "workflow.version.restore", "workflow.draft-run", "workflow.node-run",
  "run.list", "run.get", "run.wait", "run.results", "run.cancel", "run.retry",
  "run.node.get", "file.list", "file.get", "test-set.list", "test-set.get",
  "test-set.document.list", "test-set.document.get", "ground-truth.get",
  "ground-truth.version.list", "ground-truth.version.get", "evaluation.list",
  "evaluation.get", "evaluation.wait", "evaluation.results", "evaluation.result",
  "evaluation.create", "evaluation.cancel", "evaluation.comparison.get",
  "provider.list", "provider.get", "provider.model.list", "node-type.list",
];

const EXCLUDED_OPERATIONS = [
  "file.upload", "file.download", "file.delete", "workflow.export",
  "workflow.import", "run.download", "run.node.image",
  "test-set.document.download", "test-set.document.thumbnail",
  "test-set.document.upload", "test-set.document.delete", "ground-truth.upload",
  "evaluation.comparison.refresh", "provider.test", "provider.health",
  "provider.model.test", "engine.health", "test-set.create", "test-set.update",
  "test-set.delete", "engine.list", "engine.get", "run.reset", "run.node.retry",
  "run.node.rerun",
];

test("built-in extension registers exactly the 41 reviewed PressRoom tools", () => {
  const registered = [];
  createPressroomExtension({
    gatewayUrl: "http://127.0.0.1/internal/agent-tools/execute",
    gatewayGrant: "opaque-grant",
    catalogVersion: "0.1",
  })({ registerTool: (tool) => registered.push(tool) });

  assert.deepEqual(toolCatalog.tools.map((tool) => tool.operation), EXPECTED_OPERATIONS);
  assert.equal(registered.length, 41);
  assert.deepEqual(
    registered.map((tool) => tool.name),
    EXPECTED_OPERATIONS.map((operation) => operation.replaceAll(/[.-]/g, "_")),
  );
  assert.deepEqual([...PRESSROOM_TOOL_NAMES], registered.map((tool) => tool.name));
  assert.deepEqual(
    registered.map((tool) => tool.name),
    toolCatalog.tools.map((tool) => tool.name),
  );
  assert.ok(registered.every((tool) => tool.executionMode === "sequential"));
  assert.ok(registered.every((tool) => tool.name !== "bash"));
  assert.ok(
    EXCLUDED_OPERATIONS.every(
      (operation) => !toolCatalog.tools.some((tool) => tool.operation === operation),
    ),
  );
  assert.ok(
    toolCatalog.tools
      .filter((tool) => tool.exposure === "agent-confirmation")
      .every((tool) => tool.requires_platform_approval === true),
  );
});

test("extension rejects incomplete managed configuration", () => {
  assert.throws(() => createPressroomExtension({}), /configuration is incomplete/);
  assert.throws(
    () => createPressroomExtension({
      gatewayUrl: "http://127.0.0.1/internal/agent-tools/execute",
      gatewayGrant: "opaque-grant",
      catalogVersion: "stale",
    }),
    /catalog version/,
  );
});

test("registered tool sends only structured catalog arguments to the gateway", async (t) => {
  const registered = [];
  createPressroomExtension({
    gatewayUrl: "http://127.0.0.1/internal/agent-tools/execute",
    gatewayGrant: "opaque-grant",
    catalogVersion: "0.1",
  })({ registerTool: (tool) => registered.push(tool) });
  let captured;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    captured = { url, init };
    return new Response(JSON.stringify({
      schema_version: "pressroom-envelope.v1",
      ok: true,
      data: { items: [] },
      error: null,
      request_id: "request-1",
    }), { status: 200 });
  });

  const tool = registered.find((item) => item.name === "workflow_list");
  const result = await tool.execute(
    "tool-call-1",
    { page: 1, limit: 20 },
    new AbortController().signal,
  );

  assert.equal(captured.url, "http://127.0.0.1/internal/agent-tools/execute");
  assert.equal(captured.init.headers["X-DocConv-Tool-Grant"], "opaque-grant");
  assert.deepEqual(JSON.parse(captured.init.body), {
    catalog_version: "0.1",
    operation: "workflow.list",
    args: { page: 1, limit: 20 },
    tool_call_id: "tool-call-1",
  });
  assert.equal(result.isError, false);
  assert.equal(result.details.ok, true);
});
