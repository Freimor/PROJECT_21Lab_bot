/** Route hidden inside a Telegram WebApp launch hash, or null if the hash is ours. */
export function landingRoute(hash: string): string | null {
  const raw = hash.replace(/^#/, "");
  if (!/tgWebApp/i.test(raw)) return null;
  const cut = raw.search(/[?&]tgWebApp/i);
  const path = (cut >= 0 ? raw.slice(0, cut) : "").trim();
  if (path.startsWith("/")) return path || "/";
  return "/";
}

function applyTelegramRoute(): void {
  const route = landingRoute(window.location.hash);
  if (route === null) return;
  const next = `#${route}`;
  if (window.location.hash === next) return;
  const url = `${window.location.pathname}${window.location.search}${next}`;
  window.history.replaceState(window.history.state, "", url);
}

/** Telegram puts tgWebAppData into location.hash and that hides the home route. */
export function installTelegramRoute(): void {
  applyTelegramRoute();
  window.addEventListener("hashchange", applyTelegramRoute);
}
