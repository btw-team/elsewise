import { GUI_URL, guiIsAvailable } from "../gui";
import { localizeDocument, message as translateMessage } from "../i18n";
import { initializeTheme } from "../theme";
import "./styles.css";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing side panel element: ${id}`);
  return found as T;
}

const status = element<HTMLElement>("server-status");
const messageElement = element<HTMLParagraphElement>("server-message");
const retry = element<HTMLButtonElement>("retry");
const gui = element<HTMLIFrameElement>("gui");

localizeDocument();
void initializeTheme();

function showUnavailable(): void {
  gui.hidden = true;
  gui.removeAttribute("src");
  status.hidden = false;
  messageElement.textContent = translateMessage("startServer");
  retry.hidden = false;
}

async function loadGui(): Promise<void> {
  status.hidden = false;
  messageElement.textContent = translateMessage("connectingServer");
  retry.hidden = true;
  if (!(await guiIsAvailable())) {
    showUnavailable();
    return;
  }
  gui.src = GUI_URL;
  gui.hidden = false;
  status.hidden = true;
}

retry.addEventListener("click", () => void loadGui());
gui.addEventListener("error", showUnavailable);

void loadGui();
