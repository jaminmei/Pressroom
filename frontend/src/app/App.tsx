import { App as AntApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import zhTW from "antd/locale/zh_TW";
import { RouterProvider } from "react-router-dom";

import { APP_THEME } from "@/app/theme";
import { router } from "@/app/routes";
import { useLanguage } from "@/i18n/useLanguage";

export default function App() {
  const { language } = useLanguage();

  return (
    <ConfigProvider locale={language === "zh-TW" ? zhTW : enUS} theme={APP_THEME}>
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>
    </ConfigProvider>
  );
}
