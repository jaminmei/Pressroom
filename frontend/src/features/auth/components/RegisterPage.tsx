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
    width: "min(520px, 100%)",
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
      "radial-gradient(circle at top left, rgba(20, 184, 166, 0.12), transparent 32%), radial-gradient(circle at bottom right, rgba(249, 115, 22, 0.12), transparent 28%), linear-gradient(180deg, #f8fafc 0%, #eff6ff 100%)"
  };
}

export default function RegisterPage() {
  const { t } = useTranslation("auth");
  const navigate = useNavigate();
  const location = useLocation();
  const [form] = Form.useForm<{ name?: string; email: string; password: string; confirmPassword: string }>();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const status = useAuthStore((state) => state.status);
  const currentUser = useAuthStore((state) => state.currentUser);
  const isSubmitting = useAuthStore((state) => state.isSubmitting);
  const isHydrating = useAuthStore((state) => state.isHydrating);
  const register = useAuthStore((state) => state.register);
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
    <main data-testid="register-page" style={authShellStyle()}>
      <Card style={authCardStyle()}>
        <Space direction="vertical" size={20} style={{ width: "100%" }}>
          <div>
            <Typography.Text type="secondary">{t("createAccount")}</Typography.Text>
            <Typography.Title level={2} style={{ margin: "8px 0 4px" }}>
              {t("register")}
            </Typography.Title>
            <Typography.Paragraph style={{ marginBottom: 0 }}>
              {t("registerDescription")}
            </Typography.Paragraph>
          </div>

          {submitError ? <Alert message={submitError} showIcon type="error" /> : null}

          <Form
            data-testid="register-form"
            form={form}
            layout="vertical"
            onFinish={async (values) => {
              setSubmitError(null);
              try {
                await register({
                  name: values.name,
                  email: values.email,
                  password: values.password
                });
              } catch (error) {
                setSubmitError(resolveAuthError(error, t("registerFailed")));
              }
            }}
          >
            <Form.Item label={t("common:name", { ns: "common" })} name="name">
              <Input data-testid="register-name" placeholder="Alice" />
            </Form.Item>
            <Form.Item label={t("email")} name="email" rules={[{ required: true, message: t("enterEmail") }]}>
              <Input autoComplete="email" data-testid="register-email" placeholder="alice@example.com" />
            </Form.Item>
            <Form.Item label={t("password")} name="password" rules={[{ required: true, message: t("enterPassword") }]}>
              <Input.Password autoComplete="new-password" data-testid="register-password" placeholder={t("enterPasswordMin")} />
            </Form.Item>
            <Form.Item
              dependencies={["password"]}
              label={t("confirmPassword")}
              name="confirmPassword"
              rules={[
                { required: true, message: t("confirmPasswordRequired") },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue("password") === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error(t("passwordMismatch")));
                  }
                })
              ]}
            >
              <Input.Password data-testid="register-confirm-password" placeholder={t("enterPasswordAgain")} />
            </Form.Item>
            <Button block data-testid="register-submit" htmlType="submit" loading={isSubmitting} type="primary">
              {t("register")}
            </Button>
          </Form>

          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">{t("haveAccount")}</Typography.Text>
            <Button
              data-testid="go-login"
              onClick={() => navigate("/login", { replace: true, state: location.state })}
              type="link"
            >
              {t("backToLogin")}
            </Button>
          </Space>
        </Space>
      </Card>
    </main>
  );
}
