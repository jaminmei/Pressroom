import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Checkbox, Collapse, Form, Input, InputNumber, Modal, Select, Space, Tag, Typography, message } from "antd";

import type { ApiProtocol, ApiStyle, Provider, ProviderType, ReadinessStepResult } from "@/types/provider";
import { createProvider, runReadinessTest, updateProvider } from "@/services/providerApi";
import { updateParameterSchema } from "@/services/enginesApi";
import { authTypeRegistry } from "@/types/authTypeRegistry";
import { usePermission } from "@/hooks/usePermission";
import ParameterSchemaBuilder, {
  type ParamEntry,
  buildSchemaFromEntries,
  parseSchemaToEntries,
} from "./ParameterSchemaBuilder";

interface AddProviderDialogProps {
  open: boolean;
  provider: Provider | null; // null = create mode, non-null = edit mode
  onCancel: () => void;
  onSuccess: () => void; // callback to refresh provider list
  defaultCategory?: string; // pre-fill engine_category in create mode
  defaultProviderType?: ProviderType; // pre-fill provider_type in create mode
  defaultChatbotDefault?: boolean; // pre-select chatbot default in the dedicated Agent LLM flow
}

interface FormValues {
  name: string;
  provider_type?: ProviderType;
  auth_type?: string;
  base_url?: string;
  api_style?: ApiStyle;
  api_version?: string;
  api_protocol?: ApiProtocol;
  api_key?: string;
  model_id?: string;
  model_display_name?: string;
  model_context_window?: number;
  model_max_tokens?: number;
  model_reasoning?: boolean;
  is_chatbot_default?: boolean;
  health_url?: string;
}

const readinessStatusColors: Record<ReadinessStepResult["status"], string> = {
  pass: "green",
  fail: "red",
  skipped: "default",
};
const DEFAULT_MODEL_CONTEXT_WINDOW = 128_000;
const DEFAULT_MODEL_MAX_TOKENS = 4_096;
const MAX_MODEL_TOKEN_LIMIT = Number.MAX_SAFE_INTEGER;

function buildLlmApiPayload(values: FormValues): Record<string, unknown> {
  return {
    api_protocol: values.api_protocol,
    model_id: values.model_id?.trim(),
    model_display_name: values.model_display_name?.trim() || null,
    model_context_window: values.model_context_window,
    model_max_tokens: values.model_max_tokens,
    model_reasoning: values.model_reasoning ?? false,
    is_chatbot_default: values.is_chatbot_default ?? false,
  };
}

export default function AddProviderDialog({
  open,
  provider,
  onCancel,
  onSuccess,
  defaultCategory,
  defaultProviderType,
  defaultChatbotDefault = false,
}: AddProviderDialogProps) {
  const { t } = useTranslation(["common", "settings"]);
  const [form] = Form.useForm<FormValues>();
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [paramEntries, setParamEntries] = useState<ParamEntry[]>([]);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessSteps, setReadinessSteps] = useState<ReadinessStepResult[] | null>(null);
  const [readinessVerdict, setReadinessVerdict] = useState<boolean | null>(null);
  const readinessRequestGeneration = useRef(0);
  const readinessFormDirty = useRef(false);
  const { can } = usePermission();

  const isEditMode = provider !== null;
  const title = isEditMode ? t("settings:editProvider") : t("settings:addProvider");
  const authTypeOptions = authTypeRegistry.getAllOptions().map((option) => ({
    ...option,
    label: option.value === "none"
      ? t("common:none")
      : option.value === "api_key"
        ? t("settings:apiKey")
        : option.label
  }));
  const apiStyleOptions = [
    { value: "openai", label: t("settings:apiStyleOpenAI") },
    { value: "azure_openai", label: t("settings:apiStyleAzureOpenAI") },
  ] satisfies Array<{ value: ApiStyle; label: string }>;

  // Watch auth_type for conditional rendering
  const authType = Form.useWatch("auth_type", form);
  const apiStyle = Form.useWatch("api_style", form);
  const chosenProviderType = Form.useWatch("provider_type", form);
  const modelContextWindow = Form.useWatch("model_context_window", form);

  // Determine provider_type: explicit choice (create), existing provider (edit), or section default
  const providerType =
    provider?.provider_type ?? chosenProviderType ?? defaultProviderType ?? "openai_compatible";
  const isEngineService = providerType === "engine_service";
  const isLlmApi = providerType === "llm_api";
  // Model sections can host both VLM and llm_api chatbot providers; only those offer the choice.
  const canSelectProviderType = provider === null && (defaultCategory ?? "vlm") === "vlm";

  // Reset form values when the dialog opens or provider changes
  useEffect(() => {
    readinessRequestGeneration.current += 1;
    setReadinessLoading(false);
    setReadinessSteps(null);
    setReadinessVerdict(null);
    readinessFormDirty.current = false;
    if (!open) return;

    // Clear fields from the previously selected provider/plugin before
    // hydrating the current edit target.
    form.resetFields();

    if (provider) {
      const entry = authTypeRegistry.getEntry(provider.auth_type);
      const pluginValues = {
        ...(provider.auth_config_public ?? {}),
        ...(entry?.hydrateFormValues?.(provider) ?? {}),
      };
      const baseValues: Partial<FormValues> & Record<string, unknown> = {
        name: provider.name,
        auth_type: provider.auth_type,
        base_url: provider.base_url,
        api_key: undefined, // never pre-fill the API key
        api_style: provider.api_style ?? "openai",
        api_version: provider.api_version ?? undefined,
        api_protocol: provider.api_protocol ?? undefined,
        model_id: provider.model_id ?? undefined,
        model_display_name: provider.model_display_name ?? undefined,
        model_context_window: provider.model_context_window ?? DEFAULT_MODEL_CONTEXT_WINDOW,
        model_max_tokens: provider.model_max_tokens ?? DEFAULT_MODEL_MAX_TOKENS,
        model_reasoning: provider.model_reasoning ?? false,
        is_chatbot_default: provider.is_chatbot_default,
        ...pluginValues,
      };

      // Pre-fill health_url only for engine_service providers
      if (provider.provider_type === "engine_service") {
        baseValues.health_url = provider.health_url || undefined;
      }

      form.setFieldsValue(baseValues);
    } else {
      setParamEntries([]);
    }

    // Parse existing parameter schema for edit mode
    if (provider?.config_schema) {
      setParamEntries(parseSchemaToEntries(provider.config_schema));
    } else if (!provider) {
      setParamEntries([]);
    }
  }, [open, provider, form]);

  const handleFormValuesChange = () => {
    if (!isEditMode || !isLlmApi) return;
    readinessFormDirty.current = true;
    readinessRequestGeneration.current += 1;
    setReadinessLoading(false);
    setReadinessSteps(null);
    setReadinessVerdict(null);
  };

  const handleReadinessTest = async () => {
    if (!provider) return;
    if (readinessFormDirty.current) {
      message.warning(t("settings:saveBeforeReadinessTest"));
      return;
    }
    const generation = ++readinessRequestGeneration.current;
    setReadinessLoading(true);
    try {
      const result = await runReadinessTest(provider.id);
      if (readinessRequestGeneration.current !== generation) return;
      setReadinessSteps(result.steps);
      setReadinessVerdict(result.chatbot_ready);
      if (result.chatbot_ready) {
        message.success(t("settings:readinessTestPassed"));
      } else {
        const failed = result.steps.find((s) => s.status === "fail");
        message.error(failed
          ? t("settings:readinessTestFailedAt", { step: failed.name })
          : t("settings:readinessTestFailed"));
      }
    } catch {
      if (readinessRequestGeneration.current !== generation) return;
      message.error(t("settings:readinessTestUnavailable"));
    } finally {
      if (readinessRequestGeneration.current === generation) setReadinessLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!can("provider.manage")) return;
    try {
      const values = await form.validateFields();
      setConfirmLoading(true);
      const baseUrl = values.base_url?.trim();
      if (!baseUrl) {
        throw new Error(t("settings:enterBaseUrl"));
      }

      // Build auth-related payload based on auth_type
      const authPayload: Record<string, unknown> = {
        auth_type: values.auth_type,
      };
      const protocolPayload: Record<string, unknown> = isEngineService || isLlmApi
        ? { api_style: null, api_version: null }
        : {
            api_style: values.api_style ?? "openai",
            api_version:
              values.api_style === "azure_openai"
                ? values.api_version?.trim() || null
                : null,
          };

      if (values.auth_type === "none") {
        // No credential fields.
      } else if (values.auth_type === "api_key") {
        if (values.api_key && values.api_key.trim() !== "") {
          authPayload.api_key = values.api_key;
        }
      } else {
        const entry = authTypeRegistry.getEntry(values.auth_type!);
        if (entry?.extractAuthConfig) {
          const config = entry.extractAuthConfig(
            values as unknown as Record<string, unknown>,
            { isEditMode, provider },
          );
          if (config && Object.keys(config).length > 0) {
            authPayload.auth_config = config;
          }
        }
      }

      if (isEditMode) {
        const updateData: Record<string, unknown> = {};
        if (values.name !== undefined) updateData.name = values.name;
        updateData.base_url = baseUrl;
        if (isEngineService) {
          updateData.health_url = values.health_url?.trim() || null;
        }
        if (isLlmApi) {
          Object.assign(updateData, buildLlmApiPayload(values));
        }
        Object.assign(updateData, authPayload, protocolPayload);

        await updateProvider(provider.id, updateData);

        // Update parameter schema if provider is engine_service
        if (isEngineService) {
          const schema = buildSchemaFromEntries(paramEntries);
          // Only update if there are entries or if clearing an existing schema
          if (schema || provider.config_schema) {
            await updateParameterSchema(provider.id, schema ?? { type: "object", properties: {}, required: [] });
          }
        }

        readinessFormDirty.current = false;
        message.success(t("settings:providerUpdated"));
      } else {
        const created = await createProvider({
          name: values.name,
          provider_type: providerType,
          engine_category: isLlmApi ? "llm" : (defaultCategory ?? "vlm"),
          base_url: baseUrl,
          ...(isEngineService ? { health_url: values.health_url?.trim() || null } : {}),
          ...(isLlmApi ? buildLlmApiPayload(values) : {}),
          ...authPayload,
          ...protocolPayload,
        });

        // Save parameter schema for newly created engine_service provider
        if (isEngineService && paramEntries.length > 0) {
          const schema = buildSchemaFromEntries(paramEntries);
          if (schema) {
            await updateParameterSchema(created.id, schema);
          }
        }

        message.success(t("settings:providerCreated"));
      }

      onSuccess();
    } catch (error: unknown) {
      // Form validation errors are handled by Ant Design; only handle API errors.
      if (error && typeof error === "object" && "response" in error) {
        const resp = (error as { response?: { data?: { detail?: string } } }).response;
        message.error(resp?.data?.detail || t("settings:anErrorOccurred"));
      } else if (error instanceof Error) {
        message.error(error.message);
      }
    } finally {
      setConfirmLoading(false);
    }
  };

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={handleSubmit}
      confirmLoading={confirmLoading}
      okText={isEditMode ? t("common:save") : t("common:create")}
      width={820}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onValuesChange={handleFormValuesChange}
        initialValues={{
          auth_type: "api_key",
          api_style: "openai",
          provider_type: defaultProviderType ?? "openai_compatible",
          is_chatbot_default: defaultChatbotDefault,
          model_context_window: DEFAULT_MODEL_CONTEXT_WINDOW,
          model_max_tokens: DEFAULT_MODEL_MAX_TOKENS,
          model_reasoning: false,
        }}
      >
        <Form.Item
          name="name"
          label={t("common:name")}
          rules={[{ required: true, message: t("settings:enterProviderName") }]}
        >
          <Input placeholder={t("settings:providerNamePlaceholder")} />
        </Form.Item>

        {canSelectProviderType && (
          <Form.Item name="provider_type" label={t("settings:providerType")}>
            <Select
              options={[
                { value: "openai_compatible", label: t("settings:apiStyleOpenAI") },
                { value: "llm_api", label: t("settings:llmApiChatbot") },
              ] satisfies Array<{ value: ProviderType; label: string }>}
              onChange={(nextProviderType: ProviderType) => {
                form.resetFields([
                  "base_url",
                  "api_key",
                  "api_style",
                  "api_version",
                  "api_protocol",
                  "model_id",
                  "model_display_name",
                  "model_context_window",
                  "model_max_tokens",
                  "model_reasoning",
                  "is_chatbot_default",
                ]);
                form.setFieldsValue({
                  api_style: "openai",
                  is_chatbot_default: nextProviderType === "llm_api"
                    ? defaultChatbotDefault
                    : false,
                  model_context_window: DEFAULT_MODEL_CONTEXT_WINDOW,
                  model_max_tokens: DEFAULT_MODEL_MAX_TOKENS,
                  model_reasoning: false,
                });
              }}
            />
          </Form.Item>
        )}

        {!isEngineService && !isLlmApi && (
          <Form.Item
            name="api_style"
            label={t("settings:apiStyle")}
            rules={[{ required: true, message: t("settings:selectApiStyle") }]}
          >
            <Select options={apiStyleOptions} />
          </Form.Item>
        )}

        {!isEngineService && !isLlmApi && apiStyle === "azure_openai" && (
          <Form.Item
            name="api_version"
            label={t("settings:apiVersion")}
            extra={t("settings:apiVersionHelp")}
            preserve={false}
            rules={[
              { required: true, whitespace: true, message: t("settings:enterApiVersion") },
            ]}
          >
            <Input placeholder={t("settings:apiVersionPlaceholder")} />
          </Form.Item>
        )}

        <Form.Item
          name="auth_type"
          label={t("settings:authType")}
          rules={[{ required: true, message: t("settings:selectAuthType") }]}
        >
          <Select options={authTypeOptions} />
        </Form.Item>

        {isLlmApi && (
          <>
            <Form.Item name="api_protocol" label={t("settings:apiProtocol")} rules={[{ required: true, message: t("settings:selectApiProtocol") }]}>
              <Select options={[
                { value: "openai_chat_completions", label: "OpenAI Chat Completions" },
                { value: "openai_responses", label: "OpenAI Responses" },
                { value: "anthropic_messages", label: "Anthropic Messages" },
              ] satisfies Array<{ value: ApiProtocol; label: string }>} />
            </Form.Item>
            <Form.Item name="model_id" label={t("settings:modelId")} rules={[{ required: true, whitespace: true, message: t("settings:enterModelId") }]}>
              <Input />
            </Form.Item>
            <Form.Item name="model_display_name" label={t("settings:modelDisplayName")}>
              <Input />
            </Form.Item>
            <Space align="start" wrap>
              <Form.Item
                name="model_context_window"
                label={t("settings:modelContextWindow")}
                rules={[{ required: true, message: t("settings:enterModelContextWindow") }]}
              >
                <InputNumber min={1} max={MAX_MODEL_TOKEN_LIMIT} precision={0} />
              </Form.Item>
              <Form.Item
                name="model_max_tokens"
                label={t("settings:modelMaxTokens")}
                dependencies={["model_context_window"]}
                rules={[
                  { required: true, message: t("settings:enterModelMaxTokens") },
                  {
                    validator: async (_, value: number | undefined) => {
                      const contextWindow = form.getFieldValue("model_context_window");
                      if (
                        value !== undefined
                        && contextWindow !== undefined
                        && value > contextWindow
                      ) {
                        throw new Error(t("settings:modelMaxTokensExceedsContext"));
                      }
                    },
                  },
                ]}
              >
                <InputNumber
                  min={1}
                  max={modelContextWindow ?? MAX_MODEL_TOKEN_LIMIT}
                  precision={0}
                />
              </Form.Item>
            </Space>
            <Form.Item name="model_reasoning" valuePropName="checked">
              <Checkbox>{t("settings:modelSupportsReasoning")}</Checkbox>
            </Form.Item>
            <Typography.Paragraph type="secondary">
              {t("settings:modelCapabilityHelp")}
            </Typography.Paragraph>
            <Form.Item name="is_chatbot_default" valuePropName="checked">
              <Checkbox>{t("settings:makeWorkspaceChatbotDefault")}</Checkbox>
            </Form.Item>
          </>
        )}

        <Form.Item
          name="base_url"
          label={t("settings:baseUrl")}
          extra={t("settings:baseUrlHelp")}
          rules={[{ required: true, whitespace: true, message: t("settings:enterBaseUrl") }]}
        >
          <Input placeholder={t("settings:baseUrlPlaceholder")} />
        </Form.Item>

        {isEngineService && (
          <Form.Item
            name="health_url"
            label={t("settings:healthUrl")}
            extra={t("settings:healthUrlHelp")}
          >
            <Input placeholder={t("settings:healthUrlPlaceholder")} />
          </Form.Item>
        )}

        {authType === "api_key" && (
          <Form.Item
            name="api_key"
            label={t("settings:apiKey")}
            extra={isEditMode ? t("settings:leaveBlankKey") : undefined}
            rules={isLlmApi && !isEditMode ? [{ required: true, whitespace: true, message: t("settings:enterApiToken") }] : undefined}
          >
            <Input.Password placeholder={isEditMode ? t("settings:leaveBlankExisting") : t("settings:enterApiKey")} />
          </Form.Item>
        )}

        {(() => {
          const FC = authType ? authTypeRegistry.getFormComponent(authType) : null;
          return FC ? <FC form={form} isEditMode={isEditMode} /> : null;
        })()}

        {isEngineService && (
          <Collapse
            ghost
            items={[
              {
                key: "params",
                label: t("settings:parameterSchema"),
                children: (
                  <ParameterSchemaBuilder
                    value={paramEntries}
                    onChange={setParamEntries}
                  />
                ),
              },
            ]}
            style={{ marginBottom: 16 }}
          />
        )}

        {isLlmApi && isEditMode && (
          <>
            <Space style={{ marginBottom: 16 }}>
              <Button loading={readinessLoading} onClick={handleReadinessTest}>
                {t("settings:runReadinessTest")}
              </Button>
              {readinessVerdict !== null && (
                <Tag color={readinessVerdict ? "green" : "red"}>
                  {t(readinessVerdict ? "settings:readinessReady" : "settings:readinessNotReady")}
                </Tag>
              )}
            </Space>
            {readinessSteps && (
              <Space className="provider-readiness-steps" direction="vertical">
                {readinessSteps.map((step) => (
                  <Space key={step.name} size={4} wrap>
                    <Tag
                      color={readinessStatusColors[step.status]}
                    >
                      {t(`settings:readinessStepStatus.${step.status}`)}
                    </Tag>
                    <span>{step.name}</span>
                    {step.detail && (
                      <Typography.Text type="secondary">{step.detail}</Typography.Text>
                    )}
                  </Space>
                ))}
              </Space>
            )}
          </>
        )}
      </Form>
    </Modal>
  );
}
