"""Параметры клуба.

Реестр в коде — единственный источник правды о типах, границах и значениях по
умолчанию. В базе лежат только переопределения: новый параметр не требует
миграции данных, а забытый ключ сам берёт значение из кода.
"""

from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

SettingType = Literal["int", "float", "bool", "str"]


class SettingsError(ValueError):
    """Неизвестный ключ или значение вне границ — вина вызывающего."""


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    type: SettingType
    default: Any
    group: str
    label: str
    min: float | None = None
    max: float | None = None
    help: str | None = None


REGISTRY: tuple[SettingSpec, ...] = (
    # --- Спрос ---
    SettingSpec(
        "demand_threshold",
        "int",
        4,
        "demand",
        "Порог спроса",
        1,
        100,
        help="Сколько человек должны ждать встречу по книге, чтобы оргкомитет "
        "получил уведомление и начал искать ведущего.",
    ),
    SettingSpec(
        "demand_highlight_days",
        "int",
        30,
        "demand",
        "Окно свежести спроса, дней",
        1,
        365,
        help="Отметки старше этого срока опускаются в списке ниже свежих.",
    ),
    # --- Заявки организаторов ---
    SettingSpec(
        "auto_open_room",
        "bool",
        False,
        "applications",
        "Открывать переговорку автоматически",
        help="Если включено, чат по заявке заводится сразу после подачи, без "
        "решения администратора.",
    ),
    SettingSpec(
        "invite_link_ttl_hours",
        "int",
        48,
        "applications",
        "Срок жизни ссылки в переговорку, часов",
        1,
        720,
    ),
    SettingSpec(
        "room_cleanup_batch",
        "int",
        100,
        "applications",
        "Сколько сообщений чистить за раз",
        1,
        100,
        help="Telegram удаляет не больше сотни сообщений одним запросом.",
    ),
    # --- Мероприятия ---
    SettingSpec(
        "vote_days",
        "int",
        5,
        "events",
        "Длительность голосования за время, дней",
        1,
        30,
        help="По истечении срока система сама закрепляет слот с максимумом "
        "голосов. Организатор может закрепить время раньше.",
    ),
    SettingSpec(
        "default_min_attendance",
        "int",
        4,
        "events",
        "Кворум по умолчанию",
        1,
        100,
        help="Если подтверждений меньше, организатор и оргкомитет получают "
        "предупреждение. Решение о проведении всё равно за ними.",
    ),
    SettingSpec(
        "attendance_code_ttl_minutes",
        "int",
        15,
        "events",
        "Срок жизни кода присутствия, минут",
        1,
        240,
        help="Код называют вслух на встрече; по истечении срока он меняется, "
        "чтобы его нельзя было переслать тому, кто не пришёл.",
    ),
    SettingSpec(
        "feedback_delay_hours",
        "int",
        3,
        "events",
        "Через сколько часов после встречи просить отзыв",
        1,
        168,
    ),
)

BY_KEY = {spec.key: spec for spec in REGISTRY}
DEFAULTS = {spec.key: spec.default for spec in REGISTRY}


def coerce(spec: SettingSpec, raw: Any) -> Any:
    """Приводит значение к типу параметра и проверяет границы."""
    try:
        if spec.type == "int":
            value: Any = int(raw)
        elif spec.type == "float":
            value = float(raw)
        elif spec.type == "bool":
            value = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "да")
        else:
            value = str(raw)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"«{spec.label}»: не то значение") from exc

    if spec.type in ("int", "float"):
        if spec.min is not None and value < spec.min:
            raise SettingsError(f"«{spec.label}»: не меньше {spec.min:g}")
        if spec.max is not None and value > spec.max:
            raise SettingsError(f"«{spec.label}»: не больше {spec.max:g}")
    return value


class SettingsService:
    """Читает параметры пачкой. Инстанс живёт в пределах одного запроса,
    поэтому кэш внутри него не может протухнуть на середине расчёта."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cache: dict[str, Any] | None = None

    async def all(self) -> dict[str, Any]:
        if self._cache is None:
            rows = (await self._session.execute(sa.select(Setting))).scalars().all()
            values = dict(DEFAULTS)
            for row in rows:
                if spec := BY_KEY.get(row.key):
                    try:
                        values[row.key] = coerce(spec, row.value)
                    except SettingsError:
                        # Мусор в базе не должен ронять приложение — берём дефолт.
                        values[row.key] = spec.default
            self._cache = values
        return self._cache

    async def get(self, key: str) -> Any:
        return (await self.all())[key]

    async def set_many(self, updates: dict[str, Any], actor_id: int | None) -> dict[str, Any]:
        cleaned = {}
        for key, raw in updates.items():
            spec = BY_KEY.get(key)
            if spec is None:
                raise SettingsError(f"Неизвестный параметр: {key}")
            cleaned[key] = coerce(spec, raw)

        for key, value in cleaned.items():
            stmt = insert(Setting).values(key=key, value=value, updated_by=actor_id)
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Setting.key],
                    set_={
                        "value": stmt.excluded.value,
                        "updated_by": stmt.excluded.updated_by,
                        "updated_at": sa.func.now(),
                    },
                )
            )
        await self._session.commit()
        self._cache = None
        return await self.all()
