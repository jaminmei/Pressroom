import { MessageOutlined } from "@ant-design/icons";
import { FloatButton } from "antd";

interface ChatboxLauncherProps { readonly onOpen: () => void }

export function ChatboxLauncher({ onOpen }: ChatboxLauncherProps) {
  return <FloatButton aria-label="Open chatbox" className="chatbox-launcher" data-testid="chatbox-launcher" icon={<MessageOutlined />} onClick={onOpen} type="primary" />;
}
