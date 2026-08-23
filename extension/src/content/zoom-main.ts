import { installZoomSpeakerBridge } from "./zoom-speaker-bridge";

if (location.hostname === "app.zoom.us") {
  installZoomSpeakerBridge(document);
}
