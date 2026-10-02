import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installTelegramRoute } from "./telegramHash";

installTelegramRoute();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
