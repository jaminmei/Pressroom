import { create } from "zustand";

import {
  getCurrentSession,
  loginWithPassword,
  logoutCurrentSession,
  registerWithPassword
} from "@/services/authApi";
import { setUnauthorizedHandler } from "@/services/api";
import { activateWorkspaceUser, clearWorkspaceUser } from "@/services/workspaceTransport";
import { resetWorkspaceScopedState } from "@/stores/workspaceReset";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { AuthEnvelope, AuthUser, LoginRequest, RegisterRequest } from "@/types/auth";

export type AuthStatus = "unknown" | "authenticated" | "anonymous";
export type UnauthorizedReason = "required" | "expired";

interface AuthState {
  status: AuthStatus;
  currentUser: AuthUser | null;
  sessionExpiresAt: string | null;
  intendedRoute: string | null;
  isHydrating: boolean;
  isSubmitting: boolean;
  shouldRememberRedirect: boolean;
  hydrateSession: () => Promise<void>;
  login: (payload: LoginRequest) => Promise<AuthUser>;
  register: (payload: RegisterRequest) => Promise<AuthUser>;
  logout: () => Promise<void>;
  rememberIntendedRoute: (route: string | null) => void;
  consumeIntendedRoute: (fallback?: string) => string;
  allowRedirectCapture: () => void;
  handleUnauthorized: (reason: UnauthorizedReason) => void;
}

export const initialAuthState: Pick<
  AuthState,
  | "status"
  | "currentUser"
  | "sessionExpiresAt"
  | "intendedRoute"
  | "isHydrating"
  | "isSubmitting"
  | "shouldRememberRedirect"
> = {
  status: "unknown",
  currentUser: null,
  sessionExpiresAt: null,
  intendedRoute: null,
  isHydrating: false,
  isSubmitting: false,
  shouldRememberRedirect: true
};

let hydrationRequest: Promise<void> | null = null;

function applyAuthenticatedEnvelope(
  set: (partial: Partial<AuthState>) => void,
  currentUser: AuthUser | null,
  envelope: AuthEnvelope
): AuthUser {
  const nextUser = envelope.data.user;
  if (currentUser !== null && currentUser.id !== nextUser.id) clearWorkspaceUser(currentUser.id);
  activateWorkspaceUser(nextUser.id);
  set({
    status: "authenticated",
    currentUser: nextUser,
    sessionExpiresAt: envelope.data.session.expires_at,
    isHydrating: false,
    isSubmitting: false,
    shouldRememberRedirect: true
  });
  return nextUser;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  ...initialAuthState,
  hydrateSession: async () => {
    if (get().status === "authenticated") {
      return;
    }
    if (hydrationRequest) {
      return hydrationRequest;
    }

    set({ isHydrating: true });
    hydrationRequest = (async () => {
      try {
        const envelope = await getCurrentSession();
        applyAuthenticatedEnvelope(set, get().currentUser, envelope);
      } catch {
        set({
          status: "anonymous",
          currentUser: null,
          sessionExpiresAt: null,
          isHydrating: false,
          isSubmitting: false
        });
      } finally {
        hydrationRequest = null;
      }
    })();

    return hydrationRequest;
  },
  login: async (payload) => {
    set({ isSubmitting: true });
    try {
      const envelope = await loginWithPassword(payload);
      return applyAuthenticatedEnvelope(set, get().currentUser, envelope);
    } catch (error: unknown) {
      set({ isSubmitting: false });
      throw error;
    }
  },
  register: async (payload) => {
    set({ isSubmitting: true });
    try {
      const envelope = await registerWithPassword(payload);
      return applyAuthenticatedEnvelope(set, get().currentUser, envelope);
    } catch (error: unknown) {
      set({ isSubmitting: false });
      throw error;
    }
  },
  logout: async () => {
    const userId = get().currentUser?.id;
    set({ isSubmitting: true });
    try {
      await logoutCurrentSession();
    } finally {
      if (userId !== undefined) clearWorkspaceUser(userId);
      resetWorkspaceScopedState();
      useWorkspaceStore.getState().resetWorkspaceState();
      set({
        status: "anonymous",
        currentUser: null,
        sessionExpiresAt: null,
        intendedRoute: null,
        isHydrating: false,
        isSubmitting: false,
        shouldRememberRedirect: false
      });
    }
  },
  rememberIntendedRoute: (route) => {
    if (!route || route === "/login" || route === "/register") {
      return;
    }
    if (!get().shouldRememberRedirect) {
      return;
    }
    if (get().intendedRoute === route) {
      return;
    }
    set({ intendedRoute: route });
  },
  consumeIntendedRoute: (fallback = "/") => {
    const remembered = get().intendedRoute;
    const nextRoute = remembered && remembered !== "/login" && remembered !== "/register" ? remembered : fallback;
    set({ intendedRoute: null, shouldRememberRedirect: true });
    return nextRoute;
  },
  allowRedirectCapture: () => {
    if (get().shouldRememberRedirect) {
      return;
    }
    set({ shouldRememberRedirect: true });
  },
  handleUnauthorized: () => {
    const userId = get().currentUser?.id;
    if (userId !== undefined) clearWorkspaceUser(userId);
    resetWorkspaceScopedState();
    useWorkspaceStore.getState().resetWorkspaceState();
    set({
      status: "anonymous",
      currentUser: null,
      sessionExpiresAt: null,
      isHydrating: false,
      isSubmitting: false,
      shouldRememberRedirect: true
    });
  }
}));

setUnauthorizedHandler((code) => {
  useAuthStore.getState().handleUnauthorized(code === "AUTH_SESSION_EXPIRED" ? "expired" : "required");
});
