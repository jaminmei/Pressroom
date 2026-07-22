import type { ThemeConfig } from "antd";

export const APP_THEME: ThemeConfig = {
  token: {
    colorPrimary: "#7132f5",
    colorBgContainer: "#ffffff",
    colorBgLayout: "#f6f6fb",
    colorBorder: "#ececf3",
    colorBorderSecondary: "#dedee8",
    colorText: "#101114",
    colorTextSecondary: "#202230",
    colorTextTertiary: "#777b90",
    colorSuccess: "#149e61",
    colorWarning: "#c98208",
    colorError: "#d4493f",
    borderRadius: 12,
    borderRadiusLG: 16,
    borderRadiusSM: 8,
    fontFamily: '"Inter", "IBM Plex Sans", "Segoe UI", "Microsoft JhengHei", "PingFang TC", Arial, sans-serif',
    controlHeight: 40,
    boxShadow: "0 6px 18px rgba(20,17,35,0.06)",
    boxShadowSecondary: "0 16px 40px rgba(20,17,35,0.08)"
  },
  components: {
    Button: { borderRadius: 12, controlHeight: 40, fontWeight: 700 },
    Table: {
      borderRadius: 16,
      headerBg: "#fbfbfe",
      rowHoverBg: "rgba(113,50,245,0.04)",
      headerColor: "#777b90"
    },
    Card: { borderRadius: 16 },
    Modal: { borderRadius: 20 },
    Tag: { borderRadius: 8 }
  }
};
