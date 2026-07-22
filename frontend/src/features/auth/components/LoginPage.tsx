import type { AxiosError } from "axios";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "@/stores/authStore";

interface AuthErrorPayload {
  error_code?: string;
  message?: string;
}

function resolveRedirectCandidate(locationState: unknown): string | null {
  if (typeof locationState !== "object" || locationState === null || !("from" in locationState)) {
    return null;
  }
  const from = (locationState as { from?: unknown }).from;
  return typeof from === "string" && from.trim().length > 0 ? from : null;
}

function resolveAuthError(error: unknown, fallback: string): string {
  const response = (error as AxiosError<AuthErrorPayload> | undefined)?.response;
  if (typeof response?.data?.message === "string" && response.data.message.trim().length > 0) {
    return response.data.message;
  }
  return fallback;
}

function authCardStyle(): CSSProperties {
  return {
    width: "min(480px, 100%)",
    borderRadius: 24,
    boxShadow: "0 24px 60px rgba(15, 23, 42, 0.12)",
    border: "1px solid rgba(148, 163, 184, 0.2)"
  };
}

function authShellStyle(): CSSProperties {
  return {
    minHeight: "100vh",
    display: "grid",
    placeItems: "center",
    padding: "32px 20px",
    background:
      "radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 32%), radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.12), transparent 28%), linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%)"
  };
}

export default function LoginPage() {
  const { t } = useTranslation("auth");
  const navigate = useNavigate();
  const location = useLocation();
  const [form] = Form.useForm<{ email: string; password: string }>();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const status = useAuthStore((state) => state.status);
  const currentUser = useAuthStore((state) => state.currentUser);
  const isSubmitting = useAuthStore((state) => state.isSubmitting);
  const isHydrating = useAuthStore((state) => state.isHydrating);
  const login = useAuthStore((state) => state.login);
  const hydrateSession = useAuthStore((state) => state.hydrateSession);
  const consumeIntendedRoute = useAuthStore((state) => state.consumeIntendedRoute);

  const routeStateTarget = useMemo(() => resolveRedirectCandidate(location.state), [location.state]);

  useEffect(() => {
    if (status === "unknown" && !isHydrating) {
      void hydrateSession();
    }
  }, [hydrateSession, isHydrating, status]);

  useEffect(() => {
    if (status === "authenticated" && currentUser) {
      const target = consumeIntendedRoute(routeStateTarget ?? "/");
      navigate(target, { replace: true });
    }
  }, [consumeIntendedRoute, currentUser, navigate, routeStateTarget, status]);

  return (
    <main data-testid="login-page" style={authShellStyle()}>
      <Card style={authCardStyle()}>
        <Space direction="vertical" size={20} style={{ width: "100%" }}>
          <div>
            <Typography.Text type="secondary">{t("sharedWorkspace")}</Typography.Text>
            <Typography.Title level={2} style={{ margin: "8px 0 4px" }}>
              {t("login")}
            </Typography.Title>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {t("loginDescription")}
            </Typography.Paragraph>
          </div>

          {submitError ? <Alert message={submitError} showIcon type="error" /> : null}

          <Form
            data-testid="login-form"
            form={form}
            layout="vertical"
            onFinish={async (values) => {
              setSubmitError(null);
              try {
                await login(values);
              } catch (error) {
                setSubmitError(resolveAuthError(error, t("loginFailed")));
              }
            }}
          >
            <Form.Item label={t("email")} name="email" rules={[{ required: true, message: t("enterEmail") }]}>
              <Input autoComplete="email" data-testid="login-email" placeholder="alice@example.com" />
            </Form.Item>
            <Form.Item label={t("password")} name="password" rules={[{ required: true, message: t("enterPassword") }]}>
              <Input.Password autoComplete="current-password" data-testid="login-password" placeholder={t("passwordPlaceholder")} />
            </Form.Item>
            <Button block data-testid="login-submit" htmlType="submit" loading={isSubmitting} type="primary">
              {t("login")}
            </Button>
          </Form>

          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">{t("noAccount")}</Typography.Text>
            <Button
              data-testid="go-register"
              onClick={() => navigate("/register", { replace: true, state: location.state })}
              type="link"
            >
              {t("goRegister")}
            </Button>
          </Space>
        </Space>
      </Card>
    </main>
  );
}
