#!/usr/bin/env node

import { access } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import { errorKind } from "./runtime_utils.mjs";

const checks = [
  ["runtime server", () => access(new URL("./server.mjs", import.meta.url))],
  ["runtime entry", () => access(new URL("./main.mjs", import.meta.url))],
  ["dependency directory", () => access(new URL("../node_modules", import.meta.url))],
  ["Pi coding agent import", () => import("@earendil-works/pi-coding-agent")],
  ["Pi OpenAI Completions API import", () => import("@earendil-works/pi-ai/api/openai-completions.lazy")],
  ["Pi OpenAI Responses API import", () => import("@earendil-works/pi-ai/api/openai-responses.lazy")],
  ["Pi Anthropic Messages API import", () => import("@earendil-works/pi-ai/api/anthropic-messages.lazy")],
];

export async function runImageSelfChecks(
  selectedChecks,
  { stdout = process.stdout, stderr = process.stderr } = {},
) {
  let failed = false;
  for (const [label, check] of selectedChecks) {
    try {
      await check();
      stdout.write(`pi-runtime image check passed: ${label}\n`);
    } catch (error) {
      failed = true;
      // Error messages can contain local paths or credentials. Preserve a
      // useful classification without reflecting exception text into CI logs.
      stderr.write(`pi-runtime image check failed: ${label} (${errorKind(error)})\n`);
    }
  }
  return !failed;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!(await runImageSelfChecks(checks))) process.exitCode = 1;
}
