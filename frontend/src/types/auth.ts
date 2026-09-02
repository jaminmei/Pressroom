export interface AuthUser {
  id: string;
  email: string;
  name?: string | null;
  created_at?: string | null;
}

export interface AuthSession {
  expires_at: string;
}

export interface AuthCredential {
  kind: "session" | "agent_session_token";
  id: string;
  expires_at: string;
}

export interface AuthEnvelope {
  success: boolean;
  data: {
    user: AuthUser;
    session: AuthSession;
    credential?: AuthCredential;
  };
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest extends LoginRequest {
  name?: string;
}
