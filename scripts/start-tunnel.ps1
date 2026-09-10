# Start HTTPS tunnel to local admin (:8080) for Telegram Mini App.
# Prefer localtunnel (works when Cloudflare edge is blocked).
# After URL prints: put it into .env ADMIN_BASE_URL / MINIAPP_BASE_URL=/app
# then: docker compose up -d --force-recreate bot
# Do NOT restart admin while the tunnel is running (it drops port 8080 and kills the tunnel).

$ErrorActionPreference = "Stop"
Write-Host "Tunnel -> http://127.0.0.1:8080 (keep this window open)"
Write-Host "Copy https://....loca.lt into .env, then recreate bot only."
npx --yes localtunnel --port 8080
