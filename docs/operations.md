# Эксплуатация

Команды выполняются от root в `/opt/kinosfera`.

## Диагностика

```bash
docker compose ps
docker compose exec -T edge nginx -t
docker compose exec -T balancer haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
timedatectl show -p NTPSynchronized
systemctl status kinosfera-network.service --no-pager
docker compose logs --tail=60 app1 app2 postgres edge balancer
```

Приложение может выводить конфигурацию с паролем: удаляйте секреты перед
пересылкой логов. Правьте исходный `config/nginx.conf`, а не генерируемый
`.state/nginx.conf`.

## Проверки

Подставьте свои LAN-IP и домен. Нагрузочные проверки запускайте последовательно.

```bash
python3 scripts/verify_project.py 192.168.1.50 --domain bingo.example.com --ca certs/server.crt --smoke
python3 scripts/verify_project.py 192.168.1.50 --domain bingo.example.com --ca certs/server.crt
```

Первая команда проверяет API, HTTP/HTTPS и мониторинг, вторая также нагрузку
и кеш. API-проверка создаёт и удаляет собственную сессию. Отчёты сохраняются
в `reports/acceptance`.

Проверка отказов намеренно завершает процессы и внедряет HTTP 500:

```bash
python3 scripts/verify_project.py 192.168.1.50 --domain bingo.example.com --ca certs/server.crt --faults
```

Реальный HTTP/3, с uv и отдельной зависимостью клиента:

```bash
uv run --with aioquic scripts/verify_http3.py 192.168.1.50 --server-name bingo.example.com --ca certs/server.crt --output reports/http3.json
```

Для внешней проверки запустите клиент в другой сети, заменив адрес подключения
белым IP. Наличие Alt-Svc не подтверждает передачу по QUIC.

## Данные и сертификаты

Пароли находятся в `.env`, данные — в именованных Docker volumes. Маркеры
`.state/prepared` и `.state/indexes` предотвращают повторную подготовку БД.
Если таблицы существуют без маркера, проверьте завершённость инициализации.
Не создавайте маркер вручную и не удаляйте volume для обхода ошибки.

Не выполняйте `docker compose down -v`: команда удаляет БД и мониторинг.
Перед переустановкой ОС сохраните согласованный дамп PostgreSQL, `.env`,
сертификат и ключ вне сервера либо экспорт выключенной ВМ.

Для своей цепочки и ключа положите `server.crt` и `server.key` в
`/opt/kinosfera/certs`, задайте `kinosfera_tls_cert_mode: provided` в inventory.
Проверяются имя, срок и соответствие ключа. Продление выполняет владелец.

При изменении домена старый сертификат не заменяется автоматически.
Сохраните оба TLS-файла в приватную копию. В режиме selfsigned уберите прежнюю
пару из `certs/`, повторите playbook с новым доменом и обновите публичный
сертификат на проверяющих клиентах.

Служба `kinosfera-network` поддерживает правило быстрого отклонения исходящего
TCP-запроса приложения к `8.8.8.8:80` при старте. Правило ограничено Docker-сетью
проекта и не подменяет ответ сервиса.
