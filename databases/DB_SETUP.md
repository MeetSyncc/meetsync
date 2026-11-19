# Подключение базы данных (для backend)

## 1. Установка

- PostgreSQL (локально), версия 14 или новее.
- Python-библиотека: `pip install "psycopg[binary]"`

## 2. Создание базы

```bash
createdb meetsync
psql -d meetsync -f schema.sql
```

(Если `createdb` просит пользователя: `createdb -U postgres meetsync` и
`psql -U postgres -d meetsync -f schema.sql`.)

`schema.sql` создаёт все таблицы с нуля. Запускать нужно один раз на пустую базу.
Если база уже была создана по старой версии `../schema.sql`, проще всего удалить её
(`dropdb meetsync`) и создать заново.

## 3. Строка подключения

Задайте переменную окружения `DATABASE_URL`:

```bash
# Linux / macOS
export DATABASE_URL=postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/meetsync

# Windows (PowerShell)
$env:DATABASE_URL = "postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/meetsync"
```


## 4. Использование в коде

```python
from db import get_connection
import repository

with get_connection() as conn:
    user = repository.create_user(conn, telegram_user_id=12345, telegram_username="ivan")
    repository.create_interval(conn, user["user_id"], day=1,
                               start_time=time(18, 0), end_time=time(22, 0))
```

- Функции из `repository.py` сами **не делают commit** — это делает backend.
- Блок `with get_connection() as conn:` сам делает commit при успешном выходе и
  rollback при исключении, затем закрывает соединение.
- Если несколько действий должны выполниться вместе (например, создать встречу и
  добавить участников), вызывайте их внутри одного блока `with`.

## 5. Что возвращают функции

- `create_*` / `update_*` — словарь со строкой из БД (`update_*` вернёт `None`,
  если записи с таким id нет).
- `get_*` — словарь, `None` или список словарей.
- `delete_*` — `True`, если запись была удалена, иначе `False`.
- Нарушение ограничений БД (например, неверный `status`) вызывает исключение
  `psycopg.errors.CheckViolation` / `UniqueViolation` и т.п.
