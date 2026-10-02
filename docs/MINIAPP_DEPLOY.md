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

The `caddy` service proxies the whole admin process: Mini App (`/app`, `/api/miniapp`) and
the staff UI (`/`, `/login`, …). Unauthenticated visitors only see the login page. Staff
enter a Telegram username or id; the bot sends a 6-digit code to that user's private chat.
The code lasts 5 minutes, allows 5 attempts, and a new one can be requested once a minute.
The user must have opened the bot at least once (`/start`), otherwise Telegram will not
deliver the message. `ADMIN_PASSWORD` remains an emergency login. The LAN port
`ADMIN_HOST_PORT` still works.

```env
COMPOSE_PROFILES=amnezia,https
PUBLIC_DOMAIN=your-name.duckdns.org
CERTS_DIR=./certs
HTTPS_HOST_PORT=8443
MINIAPP_ENABLED=true
MINIAPP_BASE_URL=https://your-name.duckdns.org/app
```

Set `ADMIN_BASE_URL` to the URL you actually open. An `https://` value marks session cookies
Secure, so the same browser session will not log in over plain `http://` on the LAN. For the
public admin that is:

```env
ADMIN_BASE_URL=https://lab21.microelectronics.dev
MINIAPP_BASE_URL=https://lab21.microelectronics.dev/app
```

### Certificate (DuckDNS DNS-01)

Some ISPs time out Let's Encrypt inbound validators even when port forwarding looks
correct. Issue the cert from a machine that can reach DuckDNS (your PC is fine):

```powershell
$env:DUCKDNS_TOKEN="your-token"
docker run --rm -e DUCKDNS_TOKEN -v "${PWD}/certs:/certs" goacme/lego:v4.22.2 `
  --email you@example.com --dns duckdns --path /certs `
  --domains your-name.duckdns.org --accept-tos run
```

Copy `certs/certificates/*.crt` and `*.key` (renamed to `your-name.duckdns.org.crt/.key`)
into `CERTS_DIR` on the NAS. Renew the same way before expiry (~60 days).

Router: forward public **443 → `HTTPS_HOST_PORT`** on the NAS so Telegram can open `/app`.
Port 80 stays closed. UGOS keeps its own nginx on host 80/443 (redirect to 9999/9443),
which is why Caddy publishes on `HTTPS_HOST_PORT` instead.

DDNS keeps the name pointed at the router's WAN address. UGOS does this in Control Panel →
Device Connection → Remote Access; DuckDNS can also be updated by hand:

```bash
curl "https://www.duckdns.org/update?domains=<name>&token=<token>&ip=<wan-ip>"
```

Beware of updating DuckDNS from a machine behind a VPN: with `ip=` empty the record picks up the
VPN exit address instead of the router's.

### Cloudflare named tunnel (recommended when inbound HTTPS is blocked)

Named tunnels are **free** (Cloudflare Zero Trust Free). You need a domain on Cloudflare
DNS (DuckDNS alone is not enough). Quick `*.trycloudflare.com` tunnels are flaky here;
use a named tunnel instead.

1. Add the domain to Cloudflare (Free plan) and switch nameservers.
2. Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared → name e.g. `lab21-nas`.
3. Copy the **tunnel token**.
4. Public Hostname:
   - Subdomain / Domain: e.g. `lab21` + `your-domain.example`
   - Type: HTTP
   - URL: `http://127.0.0.1:8082`
5. On the NAS `.env`:

```env
COMPOSE_PROFILES=amnezia,https,tunnel
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
MINIAPP_ENABLED=true
MINIAPP_BASE_URL=https://lab21.your-domain.example/app
```

`8082` is Caddy's loopback-only HTTP listener. It proxies Mini App and admin to the
`admin` container. With the public hostname `lab21.microelectronics.dev`, the staff UI
is `https://lab21.microelectronics.dev/login`.

6. `docker compose up -d` and set BotFather Menu Button to the same `/app` URL.

### Cloudflare quick tunnel (dev only; unreliable on this NAS)

Add the `tunnel` profile was previously used with `cloudflared tunnel --url …` and
`*.trycloudflare.com`. Prefer the named tunnel above: the URL is stable and Error 1033
showed up repeatedly with quick tunnels on this ISP.

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
