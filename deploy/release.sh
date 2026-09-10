#!/usr/bin/env bash
# Выкладка: заливка кода и пересборка контейнеров одной командой.
#
#   deploy/release.sh kir@СЕРВЕР
#
# Почему одна команда, а не две: шаг с пересборкой легко потерять, и тогда
# сервер продолжает отдавать старый образ — по коду на диске это незаметно,
# видно только по хешу бандла в браузере. Так уже случалось.
#
# Запускать должен человек: docker на сервере требует sudo с паролем, поэтому
# ssh идёт с -t (выделенный терминал), чтобы приглашение на ввод было видно.

set -euo pipefail

TARGET="${1:-}"
APP_DIR="${APP_DIR:-lit-club}"

if [ -z "$TARGET" ]; then
  echo "Укажите сервер: $0 kir@адрес" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Заливаю код"
"$ROOT/deploy/sync.sh" "$TARGET"

echo
echo "→ Пересобираю контейнеры (sudo спросит пароль)"
ssh -t "$TARGET" "cd ~/$APP_DIR && sudo docker compose -f docker-compose.prod.yml up -d --build"

echo
echo "→ Проверяю, что поднялось"
for attempt in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 https://culc-bot.cu3rd.ru/health || true)
  if [ "$code" = "200" ]; then
    bundle=$(curl -s --max-time 15 https://culc-bot.cu3rd.ru/ | grep -oE '/assets/index-[^"]+\.js' | head -1)
    echo "Готово: https://culc-bot.cu3rd.ru отвечает, бандл $bundle"
    exit 0
  fi
  sleep 5
done

echo "Сайт всё ещё не отвечает (последний код: ${code:-нет}). Смотрите логи:" >&2
echo "  ssh -t $TARGET 'cd ~/$APP_DIR && sudo docker compose -f docker-compose.prod.yml logs --tail=40 api'" >&2
exit 1
