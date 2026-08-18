#!/bin/bash
# Hysteria2 server installer
# Usage: bash install-hysteria.sh <OBFS_PASSWORD>
# Ставит hysteria, получает сертификат Let's Encrypt через sslip.io,
# поднимает сервис. Пользователей раскатывает бот (hy2.py), не этот скрипт.

set -e

PORT=31000
OBFS="$1"

if [ "$EUID" -ne 0 ]; then
    echo "Запускать от root: sudo bash install-hysteria.sh <OBFS_PASSWORD>"
    exit 1
fi

if [ -z "$OBFS" ]; then
    echo "Нужен пароль обфускации - он должен быть ОДИНАКОВЫМ на всех серверах."
    echo "Сгенерировать: openssl rand -base64 24 | tr -d '/+=' | head -c 24"
    echo ""
    echo "Использование: bash install-hysteria.sh <OBFS_PASSWORD>"
    exit 1
fi

# Публичный IP и домен из него. sslip.io резолвит IP-в-домен без регистрации,
# домен нужен только чтобы Let's Encrypt выдал сертификат.
PUB_IP=$(curl -4 -s --max-time 10 https://ifconfig.me)
if [ -z "$PUB_IP" ]; then
    echo "Не удалось определить внешний IP"
    exit 1
fi
# Точечная форма, НЕ дефисная (1.2.3.4.sslip.io, а не 1-2-3-4.sslip.io):
# мобильные клиенты на ядре Xray разбирают дефис в адресе как диапазон
# портов и отказываются подключаться.
DOMAIN="${PUB_IP}.sslip.io"

echo "=== Hysteria2 Installer ==="
echo "IP:     $PUB_IP"
echo "Домен:  $DOMAIN"
echo "Порт:   $PORT/udp"
echo ""

if ! command -v hysteria &> /dev/null; then
    echo "Ставлю hysteria..."
    bash <(curl -fsSL https://get.hy2.sh/) > /tmp/hy-install.log 2>&1
fi
echo "Версия: $(hysteria version 2>/dev/null | grep -i '^version' | head -1)"

# ACME пишет сертификаты сюда, сервис работает от пользователя hysteria
mkdir -p /etc/hysteria/acme
chown -R hysteria:hysteria /etc/hysteria/acme
chmod 700 /etc/hysteria/acme

echo ""
echo "Пишу конфиг..."
cat > /etc/hysteria/config.yaml << YAML
listen: :$PORT

acme:
  domains:
    - $DOMAIN
  dir: /etc/hysteria/acme

obfs:
  type: salamander
  salamander:
    password: $OBFS

auth:
  type: userpass
  userpass:
    "_none": "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)"

masquerade:
  type: proxy
  proxy:
    url: https://www.bing.com/
    rewriteHost: true

quic:
  initStreamReceiveWindow: 8388608
  maxStreamReceiveWindow: 8388608
  initConnReceiveWindow: 20971520
  maxConnReceiveWindow: 20971520
YAML

# Порт 80 нужен ACME для проверки домена
echo ""
echo "Запускаю..."
systemctl enable hysteria-server > /dev/null 2>&1
systemctl restart hysteria-server

echo "Жду сертификат Let's Encrypt..."
for i in $(seq 1 20); do
    sleep 3
    if systemctl is-active --quiet hysteria-server && ss -ulnp 2>/dev/null | grep -q ":$PORT"; then
        break
    fi
done

echo ""
echo "=== Проверка ==="
echo "Сервис:  $(systemctl is-active hysteria-server)"
echo "Автозапуск: $(systemctl is-enabled hysteria-server 2>/dev/null)"
echo "Слушает: $(ss -ulnp 2>/dev/null | grep ":$PORT" | head -1 || echo 'НЕТ - смотри journalctl -u hysteria-server')"
CERT=$(find /etc/hysteria/acme -name "${DOMAIN}.crt" 2>/dev/null | head -1)
if [ -n "$CERT" ]; then
    echo "Сертификат: $(openssl x509 -in "$CERT" -noout -enddate 2>/dev/null | cut -d= -f2)"
else
    echo "Сертификат: НЕ ПОЛУЧЕН - смотри journalctl -u hysteria-server"
fi
echo ""
echo "=== ГОТОВО ==="
echo ""
echo "Домен для .env бота: $DOMAIN"
echo "Пользователей раскатает бот: python3 -c 'import hy2; hy2.sync()'"
