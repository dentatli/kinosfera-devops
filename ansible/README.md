# Ansible с отдельного контроллера

Основная [инструкция](../README.md) использует локальный запуск на Ubuntu.
Для управления по SSH нужен Linux-контроллер с Python 3.12 и исходниками.

```bash
cd /path/to/kinosfera-devops
python3.12 -m venv .state/ansible-venv
.state/ansible-venv/bin/pip install -r ansible/requirements.txt
cp ansible/inventory.ssh.example.yml ansible/inventory.yml
```

Заполните адрес, пользователя, путь ключа, LAN-IP, домен и email.
Проверьте SSH и отпечаток сервера, сохраните его в known_hosts. Ключ должен
иметь права 0600. Затем:

```bash
cd ansible
../.state/ansible-venv/bin/ansible-playbook -i inventory.yml site.yml --syntax-check
../.state/ansible-venv/bin/ansible-playbook -i inventory.yml site.yml
```

При необходимости добавьте `--ask-become-pass` для sudo. Пароли в inventory
не записываются. Проверка SSH host key включена.

Вместо Python-окружения можно использовать контроллер в Docker, из корня проекта:

```bash
docker build -t kinosfera-ansible:local -f ansible/Dockerfile.controller ansible
docker run --rm -v "$PWD:/workspace" -v "$HOME/.ssh:/root/.ssh:ro" \
  kinosfera-ansible:local -i inventory.yml site.yml
```

Ключ в inventory указывается как `/root/.ssh/ИМЯ_КЛЮЧА`. Docker socket
контейнеру не нужен: управление сервером выполняется по SSH.

Поддерживаются Ubuntu 22.04 x86-64 и путь `/opt/kinosfera`. Изменение файлов
или параметров вызывает развёртывание, которое может пересоздать реплики.
Для принудительного запуска используйте `-e kinosfera_force_deploy=true`.
`--check` не выполняет установку и приёмку, на пустом сервере не заменяет
реальный запуск.
