# Каналы и топики

Куда бот шлёт контент, задаётся в `.env` и через `services/destinations.py`.

## Назначения

| Поток | Переменные | Куда |
|-------|------------|------|
| Будни | `MAIN_CHANNEL_ID`, опционально `MAIN_THREAD_ID` | хроника / story |
| Важное | `IMPORTANT_CHANNEL_ID` или `IMPORTANT_THREAD_ID` (+ fallback на main) | important |
| Флуд | `FLOOD_CHAT_ID` или `FLOOD_THREAD_ID` | мемы, тизеры |
| Услуги / заявки | `JOB_CHAT_ID` (или `JOB_CHANNEL_ID`) / `JOB_THREAD_ID` | карточки ServiceJob |
| Магазин | `SHOP_CHAT_ID` / `SHOP_THREAD_ID` | карточки товаров и услуг |
| Staff | `STAFF_CHAT_ID` | служебные алерты, модерация |
| Баги / предложения | `BUGS_CHAT_ID` или `BUGS_THREAD_ID` (+ fallback на main) | приём `/bug` и `/upgrade` → админка |

## Одна форум-группа

У всех топиков форума **один** `chat_id`. Различает их `message_thread_id`.

Типичная схема:

```
MAIN_CHANNEL_ID=<id форума>
MAIN_THREAD_ID=<топик Будни>
IMPORTANT_THREAD_ID=<топик Важное>
FLOOD_THREAD_ID=<топик Флуд>
JOB_THREAD_ID=<топик заказов>
SHOP_THREAD_ID=<топик Магазин>
BUGS_THREAD_ID=<топик Баги предложения>
```

`IMPORTANT_CHANNEL_ID` / `FLOOD_CHAT_ID` / `SHOP_CHAT_ID` можно не задавать, если топики в той же группе, что `MAIN_CHANNEL_ID`.

## Симптомы кривого конфига

- «не задан IMPORTANT_… / FLOOD_…» при публикации
- пост ушёл не в тот топик
- реакции не цепляются (бот ждёт пару chat_id + message_id публикации)
- тишина Будней считается по `main_channel_id` (для story)

Пустые значения thread id в `.env` лучше комментировать, а не оставлять пустой строкой.
