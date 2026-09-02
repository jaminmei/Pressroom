# QA Test Cases — pi-agent-chatbox-v1

Session: QA-pi-agent-chatbox-v1-20260817-01 · Risk: HIGH · Depth: THOROUGH
Model endpoint: real llm_api Provider (user-supplied token during session)
Atom sequence: qa-smoke → qa-ui → qa-api → qa-backend → qa-exploratory

| # | Scenario | Input / Action | Expected Output | Assigned Atom | Priority |
|---|----------|----------------|-----------------|---------------|----------|
| 1 | App boots (standard profile) | `docker compose --profile standard up -d --build` | All services healthy, UI at :5173, `/api/health` OK | qa-smoke | P1 |
| 2 | Create llm_api Provider | Settings → Model Providers → new Provider (display name, protocol, Base URL, token, Model ID, default checkbox) | Saved; `has_credential` true; token never echoed back | qa-ui | P1 |
| 3 | Readiness test gate | Run readiness test on the Provider; also confirm no shortcut path | 6 steps pass → `chatbot_ready`, selectable as chatbot default; a `GET /models` or health-200 shortcut never marks ready | qa-api | P1 |
| 4 | Chatbox conversation | Open bottom-right launcher, send prompt requiring a tool (e.g., "list files in the workspace"), observe streaming + tool cards | Blocks in content order, thinking toggle, tool result collapsed by default, only `agent_settled` clears the working indicator | qa-ui | P1 |
| 5 | Abort + reconnect | Abort mid-turn; reload the page; reopen the chatbox | Session settles cleanly; authoritative history reloaded first, stale transient progress discarded | qa-ui | P1 |
| 6 | Projection leak check | Browser DevTools → WebSocket frames during a tool-using turn | No API tokens, authorization headers, upstream bodies, absolute host paths, or `display:false` custom messages in any outbound frame | qa-backend | P1 |
| 7 | Unique default invariant | Create second llm_api Provider, mark it chatbot default | Previous default's flag cleared automatically | qa-api | P2 |
| 8 | Legacy provider regression | Configure/use an existing openai_compatible (or Azure) Provider in a workflow | Existing Provider flows unchanged (list, model discovery, workflow run) | qa-backend | P2 |
