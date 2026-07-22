import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Collapse, Form, Input, Modal, Select, message } from "antd";

import type { ApiStyle, Provider } from "@/types/provider";
import { createProvider, updateProvider } from "@/services/providerApi";
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
  defaultProviderType?: 'openai_compatible' | 'engine_service'; // pre-fill provider_type in create mode
}

interface FormValues {
  name: string;
  auth_type?: string;
  base_url?: string;
  api_style?: ApiStyle;
  api_version?: string;
  api_key?: string;
  health_url?: string;
}

export default function AddProviderDialog({
  open,
  provider,
  onCancel,
  onSuccess,
  defaultCategory,
  defaultProviderType,
}: AddProviderDialogProps) {
  const { t } = useTranslation(["common", "settings"]);
  const [form] = Form.useForm<FormValues>();
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [paramEntries, setParamEntries] = useState<ParamEntry[]>([]);
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

  // Determine provider_type: from existing provider (edit) or default (create)
  const providerType = provider?.provider_type ?? defaultProviderType ?? "openai_compatible";
  const isEngineService = providerType === "engine_service";

  // Watch auth_type for conditional rendering
  const authType = Form.useWatch("auth_type", form);
  const apiStyle = Form.useWatch("api_style", form);

  // Reset form values when the dialog opens or provider changes
  useEffect(() => {
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
      const protocolPayload: Record<string, unknown> = isEngineService
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

        message.success(t("settings:providerUpdated"));
      } else {
        const created = await createProvider({
          name: values.name,
          provider_type: defaultProviderType ?? "openai_compatible",
          engine_category: defaultCategory ?? "vlm",
          base_url: baseUrl,
          ...(isEngineService ? { health_url: values.health_url?.trim() || null } : {}),
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
        initialValues={{
          auth_type: "api_key",
          api_style: "openai",
        }}
      >
        <Form.Item
          name="name"
          label={t("common:name")}
          rules={[{ required: true, message: t("settings:enterProviderName") }]}
        >
          <Input placeholder={t("settings:providerNamePlaceholder")} />
        </Form.Item>

        {!isEngineService && (
          <Form.Item
            name="api_style"
            label={t("settings:apiStyle")}
            rules={[{ required: true, message: t("settings:selectApiStyle") }]}
          >
            <Select options={apiStyleOptions} />
          </Form.Item>
        )}

        {!isEngineService && apiStyle === "azure_openai" && (
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
      </Form>
    </Modal>
  );
}
