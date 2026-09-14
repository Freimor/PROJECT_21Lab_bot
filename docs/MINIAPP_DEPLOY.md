# Mini App deployment

Telegram Mini App requires **HTTPS**. Local `http://localhost` works only for limited testing.

For NAS Telegram outbound proxy / remote SSH editing see [NAS_OPS.md](NAS_OPS.md).

## Production checklist

1. Put reverse proxy (Caddy or nginx) in front of `admin:8080`.
2. Set in `.env`:
   - `ADMIN_BASE_URL=https://your-domain.example`
   - `MINIAPP_BASE_URL=https://your-domain.example/app`
   - `MINIAPP_ENABLED=true`
3. In [@BotFather](https://t.me/BotFather):
   - Bot Settings → Menu Button → configure URL `https://your-domain.example/app`
   - Optional: set domain for Web App
4. Rebuild Docker image (webapp is built in multi-stage Dockerfile).

## NAS behind a home router (Compose profile `https`)

The `caddy` service publishes **only** the Mini App paths (`/app`, `/api/miniapp`, `/uploads`)
and answers 404 elsewhere, so the admin UI is never exposed to the internet — reach it on the
LAN at `ADMIN_HOST_PORT`.

```env
COMPOSE_PROFILES=amnezia,https
PUBLIC_DOMAIN=your-name.duckdns.org
DUCKDNS_TOKEN=your-duckdns-token
HTTPS_HOST_PORT=8443
MINIAPP_ENABLED=true
MINIAPP_BASE_URL=https://your-name.duckdns.org/app
```

Keep `ADMIN_BASE_URL` on the LAN address (`http://192.168.x.x:8081`): an `https://` value marks
session cookies Secure, and the admin UI then refuses to log in over plain http.

Router: forward public **443 → `HTTPS_HOST_PORT`** on the NAS so Telegram can open `/app`.
Port 80 stays closed. The certificate is issued via **DuckDNS DNS-01** (no inbound ACME
needed). UGOS keeps its own nginx on host 80/443 (redirect to 9999/9443), which is why
Caddy publishes on `HTTPS_HOST_PORT` instead.

DDNS keeps the name pointed at the router's WAN address. UGOS does this in Control Panel →
Device Connection → Remote Access; DuckDNS can also be updated by hand:

```bash
curl "https://www.duckdns.org/update?domains=<name>&token=<token>&ip=<wan-ip>"
```

Beware of updating DuckDNS from a machine behind a VPN: with `ip=` empty the record picks up the
VPN exit address instead of the router's.

## Development with tunnel

Telegram Mini App needs a public **HTTPS** URL. You do not need a bought domain.

### localtunnel (works on this machine)

```powershell
npx --yes localtunnel --port 8080
```

Copy the printed `https://….loca.lt` URL into `.env`:

```env
ADMIN_BASE_URL=https://….loca.lt
MINIAPP_BASE_URL=https://….loca.lt/app
```

Then recreate bot + admin:

```powershell
docker compose up -d --force-recreate admin bot
```

In [@BotFather](https://t.me/BotFather): Bot Settings → Menu Button → `https://….loca.lt/app`.

Keep the `npx localtunnel` window open. The URL changes every restart.

loca.lt sometimes shows a one-time “click to continue” page in the browser; in Telegram WebView try again or open the same URL once in a browser.

### Cloudflare quick tunnel

```powershell
.\scripts\start-tunnel.ps1
```

Uses `scripts/bin/cloudflared.exe` with `--protocol http2`. If QUIC/TLS to Cloudflare edge is blocked (VPN/firewall), prefer localtunnel.

## Architecture

- SPA: `/app/*` (React, hash router)
- API: `/api/miniapp/*` (initData auth)
- Admin HTML UI unchanged at `/`, `/shop`, etc.

## Manual E2E checklist

- [ ] `/start` shows «Открыть Lab21» and «FAQ» WebApp buttons
- [ ] Mini App opens inside Telegram, loads profile via initData
- [ ] Join application flow for new user
- [ ] Shop purchase debits balance and notifies staff
- [ ] Service order appears in jobs board
- [ ] Staff section visible only for staff roles
- [ ] Notification deeplink opens correct screen in app
