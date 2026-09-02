# QA Report

## Session Metadata

| Field | Value |
|-------|-------|
| Session ID | QA-pi-agent-chatbox-v1-20260817-01 |
| Tester | QA Tester (app-local account) + Sisyphus agent (browser/API automation) |
| Date | 2026-08-17 |
| Build / Commit | `bfbbd8941f` (standard Compose profile, backend image verified identical to source) |
| Change | pi-agent-chatbox-v1 |
| Risk Level | HIGH (THOROUGH depth) |

## Charter

Verify the workspace chatbot works end-to-end through the secured boundary — llm_api Provider config + readiness gate → chatbox conversation with streaming/tool rendering → reconnect — with no credential/path leakage to the browser.

## Human Test Case Results

| # | Scenario | Expected | Actual | Status | Evidence |
|---|----------|----------|--------|--------|----------|
| 1 | App boots (standard profile) | All healthy, UI+API reachable | Backend `0.2.13` healthy, UI 200, 0 log errors | PASS | smoke section |
| 2 | Create llm_api Provider (UI) | Form reachable; saved; token never echoed | **Form unreachable (BUG-001)**; API create 201 OK, `has_api_key: true`, token never echoed; **missing token → 500 (BUG-002)**; blank-token edit preserves credential | FAIL | screenshots + API log |
| 3 | Readiness test gate | 6 steps; no shortcut marks ready | Failure path: sanitized step detail, `chatbot_ready:false`; Success path: 4 pass + 2 documented skips, `chatbot_ready:true`; shortcut rejection unit-verified (20 contract tests) | PASS | readiness1/2.json |
| 4 | Chatbox conversation | Streaming blocks, tool cards, settle on `agent_settled` | **BLOCKED: BUG-003 (WS unreachable) + BUG-004 (no Node/pi_runtime in backend image)**; panel opens, session created via REST | BLOCKED | console log, Dockerfile.backend |
| 5 | Abort + reconnect | Settle cleanly; authoritative history reloaded | REST reconnect GET 200 with authoritative state PASS; live WS abort/reconnect blocked by BUG-003/004 | PARTIAL | reconnect.json |
| 6 | Projection leak check | No tokens/bodies/absolute paths in WS frames | Live frame capture blocked (no WS possible); projection logic verified by 30+ passing unit/contract tests (incl. token strip, display:false drop, path containment) | BLOCKED (logic covered) | test suites |
| 7 | Unique default invariant | Prior default cleared | Second default → first cleared (P1 false / P2 true) | PASS | API log |
| 8 | Legacy provider regression | openai_compatible unchanged | Create 201 (`api_style: openai`), GET 200, model discovery 200; 79-test provider regression suite green | PASS | legacy.json/disc2.json |

## Smoke Test Results

| Check | Status | Notes |
|-------|--------|-------|
| Build succeeds | PASS | frontend image built via derived Dockerfile + BuildKit secret (corporate npm mirror; token never in a layer/repo); backend/engines built by compose |
| App starts | PASS | after killing stale host uvicorn on :8000 and one clean `down`/`up` (container DNS hiccup) |
| No crash on load | PASS | backend logs 0 errors; console errors benign (401 unauth, pre-existing favicon 403) |

## Type-Specific Walkthrough

### qa-ui
- Launcher visibility gating: absent unauthenticated ✅, absent without chatbot-ready provider ✅, appears once ready default exists ✅
- Settings sections render; Add Provider dialog opens per-section ✅; **llm_api branch unreachable (BUG-001)**
- Chatbox panel: opens, Idle header, empty state, Send/Stop present ✅; live conversation blocked (BUG-003/004)
- Screenshot: `qa-bug001-llm-api-dialog-unreachable.png`

### qa-api
- llm_api CRUD via API: create 201 ✅, GET fields correct ✅, PUT blank-token preserves credential ✅, bad URL 422 ✅, missing token **500 (BUG-002)**
- Readiness endpoint: structured, sanitized, correct skip semantics ✅
- Unique-default invariant ✅; legacy discover ✅

### qa-backend
- WS boundary: `app/api/chatbox.py` auth+workspace resolution verified working in-process; rejection traced to Pi runtime startup failure (**BUG-004**)
- SSRF policy engages (endpoint rejected by network policy) ✅
- Provider store stable (v8, unique default enforced) ✅

### qa-exploratory (findings above; also: PATCH vs PUT verb mismatch vs tasks.md 1.4 wording — doc-level note only)

## Exploratory Findings

| # | Finding | Severity | Category | Evidence | Bug Filed? |
|---|---------|----------|----------|----------|------------|
| 1 | llm_api form unreachable | blocker | UI integration | engine_registry.py:34 + AddProviderDialog.tsx:72 | Yes (BUG-001) |
| 2 | 500 on missing api_key | major | error handling | providers.py:386, trace tr-73c16965 | Yes (BUG-002) |
| 3 | Chatbox WS unreachable (URL + nginx) | blocker | deployment | useChatboxSession.ts:30, nginx.conf | Yes (BUG-003) |
| 4 | Backend image lacks node/pi_runtime | blocker | deployment | Dockerfile.backend; close(1011)→403 | Yes (BUG-004) |
| 5 | favicon 403 via nginx (pre-existing) | minor | infra | console log | No |

## Bug Reports

### BUG-001: llm_api Provider form unreachable in UI — blocker
- **Steps**: Settings → VLM/LLM → Add Provider → dialog offers only OpenAI-compatible/Azure fields
- **Expected**: llm_api fields (protocol, model id, default checkbox)
- **Actual**: no `ENGINE_TYPES` entry advertises `default_provider_type="llm_api"`; create dialog has no type switcher — branch dead code in production
- **Evidence**: screenshot; `app/providers/engine_registry.py:34`

### BUG-002: llm_api create without token returns 500 — major
- **Steps**: POST /api/providers (llm_api, no api_key)
- **Expected**: 422 validation rejection (spec: "Create requires token")
- **Actual**: 500 INTERNAL_ERROR — `ModelProviderCreate` ValidationError unhandled at `app/api/providers.py:386`
- **Evidence**: trace `tr-73c16965`, backend traceback

### BUG-003: Chatbox WebSocket unreachable through frontend — blocker
- **Steps**: open chatbox → console floods `WebSocket ... /chatbox/sessions/{id} failed: Unexpected response code: 200`
- **Expected**: WS upgrade to backend `/api/chatbox/sessions/{id}`
- **Actual**: (a) `useChatboxSession.ts:30` omits the `/api` prefix → nginx SPA fallback 200; (b) even at the right path nginx's `/api/` location forces `Connection ""` (no upgrade support); only `/ws/` upgrades
- **Evidence**: console log; frontend/nginx.conf

### BUG-004: Backend image cannot start the Pi runtime — blocker
- **Steps**: any WS connect to chatbox session → HTTP 403 (close 1011)
- **Expected**: runtime starts, events stream
- **Actual**: `Dockerfile.backend` installs no Node.js and copies no `pi_runtime/` → `start_session` raises `PiRuntimeError` → session dead. Tests use FakeLauncher, so no test caught the deployment gap
- **Evidence**: `docker exec … which node` empty; instrumented scope/ctx logging (auth OK, context OK, then 1011)

## QA Conclusion

| Field | Value |
|-------|-------|
| Status | **FAILED** |
| Blocking Bugs | 3 (BUG-001, BUG-003, BUG-004) + 1 major (BUG-002) |
| Archive Recommendation | **HOLD — fix cycle then re-QA** |
| Notes | Core backend capabilities that are testable in deployment (CRUD, readiness gate, invariant, SSRF, legacy path, projection logic via suites) all PASS; the failures are integration/deployment seams the mocked test suite structurally cannot see |

## Evidence Inventory

| # | Type | Path / URL | Referenced In |
|---|------|-----------|---------------|
| 1 | screenshot | `qa-bug001-llm-api-dialog-unreachable.png` | BUG-001 |
| 2 | API log | `/tmp/opencode/{create-ok,readiness1,readiness2,patch,put,legacy,disc2,reconnect}.json` | Cases 2/3/7/8 |
| 3 | console log | `.playwright-mcp/console-*.log` | BUG-003 |
| 4 | backend log | `docker logs doc-conv-backend-1` (traces tr-73c16965, tr-420f…) | BUG-002 |
| 5 | live mock | container `qa-llm-mock` on `doc-conv_doc-conv-network` (`/tmp/opencode/qa-llm-mock.py`) | Cases 3/8 |
| 6 | smoke log | `/tmp/opencode/compose-up*.log`, `fe-build*.log` | Smoke |
