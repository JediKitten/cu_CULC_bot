#!/usr/bin/env bash
# HTTPS-туннель к dev-серверу Mini App, с автоматическим переподключением.
#
# Telegram не принимает localhost и http, поэтому в разработке приложение должно
# светиться наружу по HTTPS. Скрипт поднимает туннель и записывает адрес в .env.
#
# Править BotFather при этом не нужно: бот следит за .env и сам переставляет
# кнопку меню через Telegram API (см. watch_miniapp_url в app/bot.py).
# Достаточно, чтобы бот был запущен.
#
# Использование:  scripts/tunnel.sh              (Ctrl+C — остановить)
#                 TUNNEL=pinggy scripts/tunnel.sh
#
# Почему localhost.run по умолчанию — из двух других вариантов, проверенных на
# этой машине:
#   * cloudflared не поднимается вовсе: сеть режет исходящий 7844 и по UDP,
#     и по TCP, туннель остаётся без связи с краем сети и отдаёт 530;
#   * pinggy работает, но бесплатный тариф показывает браузерам страницу
#     «Enter site». Webview Telegram — тоже браузер, и вместо приложения
#     человек видит эту заглушку. Оставлен запасным вариантом.
# localhost.run ходит по обычному SSH и отдаёт приложение сразу.

set -uo pipefail

PORT="${PORT:-5183}"
TUNNEL="${TUNNEL:-lhr}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TUNNEL_PID=""
cleanup() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
  echo
  echo "Туннель остановлен."
  exit 0
}
trap cleanup INT TERM

start_tunnel() {
  if [ "$TUNNEL" = "pinggy" ]; then
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=30 -p 443 -R0:localhost:"$PORT" a.pinggy.io > "$1" 2>&1 &
  else
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=30 -R 80:localhost:"$PORT" nokey@localhost.run > "$1" 2>&1 &
  fi
  TUNNEL_PID=$!
}

url_pattern() {
  if [ "$TUNNEL" = "pinggy" ]; then
    echo 'https://[a-z0-9-]+\.free\.pinggy\.net'
  else
    echo 'https://[a-z0-9-]+\.lhr\.life'
  fi
}

attempt=0
while true; do
  attempt=$((attempt + 1))
  LOG="$(mktemp -t litclub-tunnel)"
  start_tunnel "$LOG"

  URL=""
  for _ in $(seq 1 45); do
    URL=$(grep -oE "$(url_pattern)" "$LOG" | head -1)
    [ -n "$URL" ] && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || break
    sleep 1
  done

  if [ -z "$URL" ]; then
    echo "Попытка $attempt: адрес получить не удалось, повтор через 10 с." >&2
    tail -3 "$LOG" >&2
    kill "$TUNNEL_PID" 2>/dev/null
    rm -f "$LOG"
    sleep 10
    continue
  fi

  if [ -f "$ROOT/.env" ]; then
    sed -i '' "s|^MINIAPP_URL=.*|MINIAPP_URL=$URL|" "$ROOT/.env"
  fi

  cat <<INFO

  Адрес Mini App: $URL

  Записан в .env. Бот подхватит его в течение нескольких секунд и сам
  переставит кнопку меню — BotFather трогать не нужно.

INFO

  # Ждём падения туннеля и поднимаем заново: адрес сменится, но бот снова его
  # подхватит. Перезапускать вручную — верный способ забыть.
  wait "$TUNNEL_PID"
  rm -f "$LOG"
  echo "Туннель отвалился, переподключаемся…"
  sleep 3
done
