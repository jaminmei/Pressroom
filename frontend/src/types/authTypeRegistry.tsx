import type { FormInstance } from "antd";
import type { Provider } from "./provider";

export interface AuthConfigExtractionContext {
  isEditMode: boolean;
  provider: Provider | null;
}

export interface AuthTypeEntry {
  id: string;
  label: string;
  FormComponent: React.ComponentType<{ form: FormInstance; isEditMode: boolean }> | null;
  DisplayComponent: React.ComponentType<{ provider: Provider }> | null;
  /** Map public provider auth fields into this plugin's form field names. */
  hydrateFormValues?: (provider: Provider) => Record<string, unknown>;
  /**
   * Return only fields supplied by the form. In edit mode omitted secret fields
   * are preserved by the backend's partial auth-config merge.
   */
  extractAuthConfig?: (
    values: Record<string, unknown>,
    context: AuthConfigExtractionContext,
  ) => Record<string, unknown> | null | undefined;
}

class AuthTypeRegistry {
  private entries = new Map<string, AuthTypeEntry>();

  register(entry: AuthTypeEntry): void {
    if (this.entries.has(entry.id)) {
      throw new Error(`Auth type "${entry.id}" is already registered`);
    }
    this.entries.set(entry.id, entry);
  }

  unregister(typeId: string): boolean {
    return this.entries.delete(typeId);
  }

  getEntry(typeId: string): AuthTypeEntry | undefined {
    return this.entries.get(typeId);
  }

  getFormComponent(
    typeId: string,
  ): React.ComponentType<{ form: FormInstance; isEditMode: boolean }> | null {
    return this.entries.get(typeId)?.FormComponent ?? null;
  }

  getDisplayComponent(typeId: string): React.ComponentType<{ provider: Provider }> | null {
    return this.entries.get(typeId)?.DisplayComponent ?? null;
  }

  getAllOptions(): Array<{ value: string; label: string }> {
    return Array.from(this.entries.values()).map((e) => ({
      value: e.id,
      label: e.label,
    }));
  }
}

export const authTypeRegistry = new AuthTypeRegistry();

// Register built-in auth types
authTypeRegistry.register({
  id: "none",
  label: "None",
  FormComponent: null,
  DisplayComponent: null,
});
authTypeRegistry.register({
  id: "api_key",
  label: "API Key",
  FormComponent: null,
  DisplayComponent: null,
});
