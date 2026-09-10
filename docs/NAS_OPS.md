# NAS ops: Telegram proxy failover + remote editing

## 1. Telegram API via Amnezia (failover)

Direct access from many RU networks to `api.telegram.org` fails. The bot does **not** need a full-NAS VPN — only SOCKS exits.

### Setup

1. Export **two** AmneziaWG client `.conf` files (ideally different servers/endpoints).
2. Put them here (any filename ending in `.conf`, not `wg0.conf` if using random mode):

```text
secrets/amnezia-a/server1.conf
secrets/amnezia-b/server2.conf
```

3. In `.env`:

```env
COMPOSE_PROFILES=ollama,amnezia
TELEGRAM_PROXIES=socks5://amnezia-a:1080,socks5://amnezia-b:1080
```

4. Start:

```powershell
docker compose up -d --build
```

### How failover works

- On start, bot/admin probe proxies in order (`getMe`) and remember the first that works.
- HTTP calls to Telegram (notify, admin actions, profile sync) retry the next proxy on transport/timeout errors.
- Long-lived aiogram polling uses the selected proxy; if that exit dies, restart the bot container (or add a second conf under the same bridge with `AMNEZIA_ENABLE_RANDOM=1`).

`ENABLE_RANDOM=1` on each bridge picks a random `.conf` from that folder on (re)start — useful as a second layer inside one exit.

## 2. White IP + Mini App

White IP is for **inbound HTTPS** (Mini App / BotFather URL). See [MINIAPP_DEPLOY.md](MINIAPP_DEPLOY.md).

Outbound Telegram still uses `TELEGRAM_PROXIES` unless your ISP reaches `api.telegram.org` without help.

## 3. Remote access so Cursor can edit the bot on NAS

Goal: agent/IDE reaches the repo on the NAS without exposing the whole LAN.

### Recommended: Tailscale (or Headscale)

1. Install Tailscale on the NAS and on your PC.
2. Enable SSH on the NAS (key auth only).
3. In Cursor: **Remote - SSH** → `user@100.x.x.x` (Tailscale IP) → open the project folder.
4. Chat/agent then edits files on the NAS over that SSH session.

Pros: no public SSH, works behind CGNAT, stable for agents.

### Alternative: Cloudflare Tunnel for SSH

Expose only SSH through a named tunnel (Access policy / short-lived certs). Heavier than Tailscale for day-to-day Cursor use.

### Fallback: GitHub as the source of truth

If the NAS is offline for editing:

1. Develop/push from PC (or Cursor Cloud Agent against GitHub).
2. On NAS: `git pull` + `docker compose up -d --build` (or existing watchdog).

Do **not** open NAS SSH (`22`) to the raw white IP without keys + fail2ban/allowlist. Prefer Tailscale overlay.

### Checklist before you leave the NAS at the white-IP site

- [ ] Tailscale up on NAS; you can SSH from home/PC
- [ ] Repo path known; Cursor Remote SSH works once
- [ ] `secrets/amnezia-*/*.conf` present; `TELEGRAM_PROXIES` set
- [ ] `docker compose ps` shows bot + amnezia-a/b healthy
- [ ] Bot answers `/start` in Telegram
- [ ] (Later) HTTPS + `MINIAPP_BASE_URL` for Mini App
