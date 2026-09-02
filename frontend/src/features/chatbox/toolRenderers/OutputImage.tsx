import { payloadImage, type ToolExecutionView } from "@/features/chatbox/toolRenderers/types";

export function OutputImage({ exec }: { readonly exec: ToolExecutionView }) {
  const image = payloadImage(exec.result) ?? payloadImage(exec.partial);
  if (image === null) return null;
  return (
    <img
      alt=""
      className="chatbox-tool-image"
      src={`data:${image.mimeType};base64,${image.data}`}
    />
  );
}
