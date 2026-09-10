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
