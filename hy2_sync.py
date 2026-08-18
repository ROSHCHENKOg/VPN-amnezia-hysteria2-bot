#!/usr/bin/env python3
"""
Раскатывает пользователей Hysteria2 из базы бота на все серверы.

Обычно вызывается самим ботом при выдаче/отзыве ключа. Руками нужен, если
конфиг на сервере разъехался с базой - например, после переустановки сервера.

Запуск:  ./venv/bin/python hy2_sync.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import hy2

if __name__ == "__main__":
    result = hy2.sync()
    print(f"ключей: {result['keys']}")
    print("раскатка: " + ", ".join(
        f"{name}={'OK' if ok else 'ОШИБКА'}" for name, ok in result["servers"].items()))
    sys.exit(0 if all(result["servers"].values()) else 1)
