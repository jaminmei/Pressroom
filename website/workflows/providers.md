---
title: Model Providers
description: Configure workspace-scoped OpenAI-compatible or Azure OpenAI Providers, manage models, and apply the network security policy.
---

# Model Providers

Model Providers connect PressRoom workflows to OpenAI-compatible vision services. They are workspace-scoped, encrypted, and invoked through the local VLM adapter. Built-in engine services appear separately in **Settings** and do not require you to copy credentials into a workflow.

## Prerequisites

- An active workspace
- `Owner` or `Admin` role to manage Providers
- A Provider base URL reachable from the backend and VLM adapter
- A secret stored outside source control
- For Azure OpenAI, the API version and deployment name supplied by your Azure resource

## 1. Open Provider settings

Open the workspace switcher, choose **Workspace Settings**, then select **Providers**. The direct application route is `/settings/workspace/providers`.

The page separates:

- **Workspace Providers**, which authorized workspace members can manage;
- **System Providers**, which are environment-managed and read-only in this view.

![Workspace Provider configuration form](/images/guides/provider-configuration.webp)

## 2. Add an OpenAI-compatible Provider

1. Select **Add Provider**.
2. Enter a clear **Name**.
3. Set **API Style** to **OpenAI-compatible**.
4. Select the required **Auth Type**—normally **API Key**, or **None** only for an intentionally unauthenticated service.
5. Enter the explicit **Base URL** for that service.
6. Enter the API key at creation time.
7. Select **Create**.

PressRoom does not substitute a deployment-wide upstream URL. Each Provider record has an explicit base URL.

In the current UI, expand **Show Models**, choose **Add Model**, and enter the exact upstream model ID. Enable only models intended for workflows, then test the model and Provider connection.

## 3. Add an Azure OpenAI Provider

1. Select **Add Provider**.
2. Set **API Style** to **Azure OpenAI**.
3. Enter the Azure endpoint as **Base URL**.
4. Enter the required **Azure API Version**.
5. Select **API Key** and provide the credential.
6. Create the Provider.
7. Select **Add Model** and enter each Azure deployment name manually.

Azure OpenAI deployments are not discovered from `/models`; the deployment name is the model identifier PressRoom sends through the adapter.

## 4. Test and enable models

Use **Test Connection** on the Provider card. Expand **Show Models** to:

- add or remove a model;
- enable or disable it;
- run a model-level test;
- review per-model health.

Set a Provider as **Default** when it should be the preferred Provider for its engine category. If exactly one enabled model is available, a new workflow can select it automatically. Otherwise choose the Provider and model in the Model node.

## 5. Use the Provider in a workflow

1. Apply **Custom Workflow** or add a Model node.
2. Select the Model node.
3. In **Node Configuration**, select the Provider.
4. Select an enabled vision-capable model.
5. Review the prompt and structured output schema.
6. Run validation, then execute with a non-sensitive test document.

Credentials are resolved for the invocation. The workflow definition contains Provider/model references and node parameters, not the decrypted secret.

## Private-network policy

`PROVIDER_ALLOW_PRIVATE_HOSTS=true` permits Provider destinations on private or loopback networks, which is useful for local services. It is an operator-controlled trust decision.

Even when private hosts are allowed, PressRoom blocks link-local and cloud metadata destinations, reserved and multicast addresses, unspecified destinations, and DNS rebinding attempts.

For an untrusted multi-tenant deployment, set:

```dotenv
PROVIDER_ALLOW_PRIVATE_HOSTS=false
```

Do not disable TLS certificate verification unless the deployment's trust model explicitly requires it and you have reviewed the consequences.

## Rotate a credential

1. Create or obtain the replacement credential from the Provider.
2. Edit the PressRoom Provider.
3. Enter the new key; leaving the field blank preserves the existing encrypted key.
4. Save and test the Provider and a model.
5. Revoke the old upstream credential.

Never paste credentials into node prompts, workflow JSON, screenshots, issue reports, or browser code.

## Verify success

- The Provider card is under **Workspace Providers**.
- **Test Connection** reports healthy or shows successful model results.
- At least one intended model is enabled.
- A Model node can select the Provider and model.
- A test run completes without exposing the credential in configuration or result views.

## Troubleshooting

### An added model cannot be tested

The current UI registers model IDs manually. For Azure OpenAI, enter the deployment name. For another compatible service, confirm the exact model ID, base URL, and credential scope before running the model-level or Provider connection test.

### Connection test fails

Check backend/VLM-adapter reachability, base URL shape, DNS, TLS trust, auth type, and key scope. Do not post the complete private base URL or authorization header in a public issue.

### Private or loopback destination is blocked

Verify the operator intentionally set `PROVIDER_ALLOW_PRIVATE_HOSTS=true` for this deployment. Link-local and metadata destinations remain blocked and must not be bypassed.

### The Provider exists but is absent from a Model node

Confirm the Provider is in the active workspace, its model is enabled, and your role has `provider.use`. Reload the workflow after switching workspaces.

### Existing key disappears while editing

This is intentional. PressRoom never rehydrates a stored secret into the form. Leave the key field blank to retain it or enter a replacement.

## Next steps

- [Build and configure Model nodes](/workflows/editor-and-nodes)
- [Run and compare outputs](/workflows/run-and-results)
- [Review the security baseline](/administration/security-and-troubleshooting)
