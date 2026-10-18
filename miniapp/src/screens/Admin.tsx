import { useEffect, useState } from "react";
import * as api from "../api";
import { Section } from "../components/Section";
import { dateTimeLabel, daysLeft } from "../dates";
import {
  applicationStatusLabel,
  audienceLabel,
  eventStatus,
  toneClass,
} from "../labels";
import type {
  AdminEvent,
  Application,
  BookRequest,
  EventTypeItem,
  MemberKind,
  Room,
  Setting,
  Topic,
} from "../types";

const KINDS: MemberKind[] = ["applicant", "bachelor", "master", "staff", "guest"];

type Tab = "Встречи" | "Заявки" | "Книги" | "Форум" | "Роли" | "Настройки" | "Аналитика";

const TABS: Tab[] = ["Встречи", "Заявки", "Книги", "Форум", "Роли", "Настройки", "Аналитика"];

const ROLES: { key: string; title: string; hint: string }[] = [
  { key: "user", title: "Участник", hint: "обычный доступ" },
  { key: "moderator", title: "Модератор", hint: "модерация книг" },
  { key: "admin", title: "Администратор", hint: "заявки, встречи, форум, аналитика" },
  {
    key: "superadmin",
    title: "Главный администратор",
    hint: "то же плюс настройки и раздача ролей",
  },
];

/** Панель оргкомитета. Одно место вместо россыпи экранов: всё, чем управляют
 * руками, лежит рядом, и не нужно помнить, где что. */
export function Admin({
  onClose,
  role,
  onOpenEvent,
  eventOpen,
}: {
  onClose(): void;
  role: string;
  onOpenEvent(id: number): void;
  /** Открыта ли поверх карточка встречи: по её закрытии список обновляем. */
  eventOpen: boolean;
}) {
  const tabs = TABS;
  const [tab, setTab] = useState<Tab>("Встречи");

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button onClick={onClose} aria-label="Назад">
          ←
        </button>
        <b>Оргкомитет</b>
      </div>
      <div className="screen">
        <div className="row row--wrap" style={{ marginBottom: 12 }}>
          {tabs.map((item) => (
            <button
              key={item}
              className={`chip ${tab === item ? "chip--on" : ""}`}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>

        {tab === "Встречи" && <AdminEvents onOpenEvent={onOpenEvent} eventOpen={eventOpen} />}
        {tab === "Заявки" && <Applications onOpenEvent={onOpenEvent} />}
        {tab === "Книги" && <BookRequests />}
        {tab === "Форум" && <Forum onOpenEvent={onOpenEvent} />}
        {tab === "Роли" && <Roles canEdit={role === "superadmin"} />}
        {tab === "Настройки" && <Settings canEdit={role === "superadmin"} />}
        {tab === "Аналитика" && <Analytics />}
      </div>
    </div>
  );
}

const EVENT_GROUPS: { title: string; statuses: string[]; hint: string; open: boolean }[] = [
  {
    title: "Ведущий выбирает время",
    statuses: ["slot_selection"],
    hint: "Заявка одобрена, ведущий расставляет окна. Если он прислал их в форум — откройте встречу и расставьте за него.",
    open: true,
  },
  {
    title: "Идёт голосование",
    statuses: ["voting"],
    hint: "Участники выбирают время. По дедлайну встреча встанет на окно-победитель.",
    open: true,
  },
  { title: "Назначены", statuses: ["scheduled"], hint: "", open: true },
  {
    title: "Прошли и отменены",
    statuses: ["held", "cancelled"],
    hint: "За последний месяц.",
    open: false,
  },
];

function AdminEvents({
  onOpenEvent,
  eventOpen,
}: {
  onOpenEvent(id: number): void;
  eventOpen: boolean;
}) {
  const [items, setItems] = useState<AdminEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () =>
    api
      .adminEvents()
      .then(setItems)
      .catch((e) => setError(e.message));

  useEffect(() => {
    // Перечитываем и при закрытии карточки встречи: там могли закрепить
    // время или отменить её.
    if (!eventOpen) reload();
  }, [eventOpen]);

  async function act(action: Promise<unknown>) {
    setBusy(true);
    try {
      await action;
      setError(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  if (items === null) return error ? <p className="error">{error}</p> : <p className="hint">Загружаем…</p>;

  return (
    <>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && (
        <p className="hint">
          Встреч пока нет. Они появляются, когда вы одобряете заявку ведущего во вкладке
          «Заявки».
        </p>
      )}
      {EVENT_GROUPS.map((group) => {
        const rows = items.filter((item) => group.statuses.includes(item.status));
        if (rows.length === 0) return null;
        return (
          <Section
            key={group.title}
            title={group.title}
            count={rows.length}
            hint={group.hint || undefined}
            defaultOpen={group.open}
            storageKey={`admin-events-${group.statuses[0]}`}
          >
            {rows.map((item) => (
              <AdminEventCard
                key={item.id}
                item={item}
                busy={busy}
                onOpen={() => onOpenEvent(item.id)}
                onAct={act}
              />
            ))}
          </Section>
        );
      })}
    </>
  );
}

function AdminEventCard({
  item,
  busy,
  onOpen,
  onAct,
}: {
  item: AdminEvent;
  busy: boolean;
  onOpen(): void;
  onAct(action: Promise<unknown>): void;
}) {
  const status = eventStatus(item.status);
  const live = ["slot_selection", "voting", "scheduled"].includes(item.status);

  return (
    <div className="card">
      <div className="spread">
        <b>{item.book.title}</b>
        <span className={toneClass(status.tone)}>{status.label}</span>
      </div>
      <div className="meta">
        {item.event_type_title} · ведёт {item.organizer_name}
        {item.organizer_username && ` @${item.organizer_username}`}
      </div>
      {item.audience.length > 0 && (
        <div className="meta">Только для {item.audience.map(audienceLabel).join(", ")}</div>
      )}
      <div className="meta" style={{ marginTop: 4 }}>
        {item.status === "voting" &&
          item.vote_deadline &&
          `Голосование ещё ${daysLeft(item.vote_deadline)} · проголосовали ${item.voters}`}
        {item.starts_at && `🗓 ${dateTimeLabel(item.starts_at)}`}
        {item.status === "scheduled" && ` · идут ${item.going}`}
        {item.status === "cancelled" && item.cancel_reason && `Причина: ${item.cancel_reason}`}
      </div>

      <div className="meta" style={{ marginTop: 4 }}>
        {item.topic_link ? (
          <a className="link" href={item.topic_link}>
            💬 Тема в форуме
          </a>
        ) : (
          live && "Темы в форуме нет"
        )}
      </div>

      <div className="row row--wrap" style={{ marginTop: 8 }}>
        <button className="chip chip--on" onClick={onOpen}>
          открыть
        </button>
        {live && !item.topic_link && item.application_id && (
          <button
            className="chip"
            disabled={busy}
            onClick={() => onAct(api.openRoom(item.application_id!))}
          >
            открыть тему
          </button>
        )}
        {item.topic_link && item.application_id && (
          <button
            className="chip"
            disabled={busy}
            onClick={() => {
              if (
                confirm(
                  "Удалить тему вместе со всей перепиской? Ведущего исключат из форума, " +
                    "если других тем у него нет.",
                )
              ) {
                onAct(api.closeRoom(item.application_id!));
              }
            }}
          >
            закрыть тему
          </button>
        )}
        {live && (
          <button
            className="chip danger"
            disabled={busy}
            onClick={() => {
              const reason = prompt(
                "Почему отменяем? Причину увидят ведущий, записавшиеся и голосовавшие.",
              );
              if (reason && reason.trim().length >= 3) {
                onAct(api.cancelEvent(item.id, reason.trim()));
              }
            }}
          >
            отменить
          </button>
        )}
      </div>
    </div>
  );
}

const APPLICATION_FILTERS: { label: string; statuses: string[] | undefined; empty: string }[] = [
  { label: "На рассмотрении", statuses: undefined, empty: "Открытых заявок нет." },
  { label: "Одобренные", statuses: ["approved"], empty: "Одобренных заявок нет." },
  {
    label: "Отклонённые",
    statuses: ["rejected", "withdrawn"],
    empty: "Отклонённых и отозванных заявок нет.",
  },
];

// Значение в выборе формата, означающее «завести формат кандидата как новый».
const NEW_TYPE = -1;

function Applications({ onOpenEvent }: { onOpenEvent(id: number): void }) {
  const [filter, setFilter] = useState(0);
  const [items, setItems] = useState<Application[]>([]);
  const [types, setTypes] = useState<EventTypeItem[]>([]);
  const [audience, setAudience] = useState<Record<number, MemberKind[]>>({});
  const [typeFor, setTypeFor] = useState<Record<number, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = (index = filter) =>
    api
      .applications(APPLICATION_FILTERS[index].statuses)
      .then(setItems)
      .catch((e) => setError(e.message));

  useEffect(() => {
    reload();
    api
      .eventTypes()
      .then((all) => setTypes(all.filter((t) => t.status === "active")))
      .catch(() => setTypes([]));
  }, []);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      setError(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function approve(item: Application) {
    let typeId: number | null = null;
    if (!item.event_type_id) {
      const chosen = typeFor[item.id];
      if (chosen === NEW_TYPE) {
        typeId = (await api.createEventType(item.proposed_type_title ?? "Свой формат")).id;
      } else {
        typeId = chosen;
      }
    }
    await api.approveApplication(item.id, {
      audience: audience[item.id] ?? [],
      event_type_id: typeId,
    });
  }

  return (
    <>
      <div className="row row--wrap" style={{ marginBottom: 12 }}>
        {APPLICATION_FILTERS.map((item, index) => (
          <button
            key={item.label}
            className={`chip ${filter === index ? "chip--on" : ""}`}
            onClick={() => {
              setFilter(index);
              reload(index);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="hint">{APPLICATION_FILTERS[filter].empty}</p>}
      {items.map((item) => {
        const open = item.status === "submitted" || item.status === "chat_open";
        const chosen = audience[item.id] ?? [];
        const needsType = !item.event_type_id;
        return (
          <div className="card" key={item.id}>
            <div className="spread">
              <b>{item.book.title}</b>
              <span className={`badge ${item.status === "approved" ? "badge--ok" : ""}`}>
                {applicationStatusLabel(item.status)}
              </span>
            </div>
            <div className="meta">
              {item.user_name}
              {item.user_username && ` · @${item.user_username}`} ·{" "}
              {item.event_type_title ?? `свой формат: ${item.proposed_type_title}`}
            </div>

            {open && (
              <div style={{ margin: "8px 0" }}>
                {Object.entries(item.answers).map(([question, answer]) => (
                  <div key={question} className="meta">
                    <b>{question}</b> — {formatAnswer(answer)}
                  </div>
                ))}
              </div>
            )}
            {item.decision_comment && (
              <p className="meta">Комментарий: {item.decision_comment}</p>
            )}

            {item.topic_link ? (
              <p className="meta">
                <a className="link" href={item.topic_link}>
                  💬 Тема в форуме
                </a>
              </p>
            ) : (
              open && (
                <button
                  className="ghost"
                  style={{ width: "100%", marginBottom: 8 }}
                  disabled={busy}
                  onClick={() => act(() => api.openRoom(item.id))}
                >
                  💬 Открыть тему в форуме
                </button>
              )
            )}

            {item.event_id && (
              <button
                className="ghost"
                style={{ width: "100%", marginTop: 4 }}
                onClick={() => onOpenEvent(item.event_id!)}
              >
                К встрече →
              </button>
            )}

            {open && (
              <>
                {needsType && (
                  <label className="field" style={{ marginTop: 8 }}>
                    <span>
                      Кандидат предложил свой формат. К какому его отнести?
                    </span>
                    <select
                      value={typeFor[item.id] ?? ""}
                      onChange={(e) =>
                        setTypeFor((prev) => ({ ...prev, [item.id]: Number(e.target.value) }))
                      }
                    >
                      <option value="" disabled>
                        выберите формат
                      </option>
                      <option value={NEW_TYPE}>
                        Завести новый: «{item.proposed_type_title}»
                      </option>
                      {types.map((type) => (
                        <option key={type.id} value={type.id}>
                          {type.title}
                        </option>
                      ))}
                    </select>
                  </label>
                )}

                <p className="hint" style={{ marginTop: 8 }}>
                  Кому будет доступна встреча? Ничего не отмечено — значит всем.
                </p>
                <div className="row row--wrap" style={{ marginBottom: 8 }}>
                  {KINDS.map((kind) => (
                    <button
                      key={kind}
                      className={`chip ${chosen.includes(kind) ? "chip--on" : ""}`}
                      onClick={() =>
                        setAudience((prev) => ({
                          ...prev,
                          [item.id]: chosen.includes(kind)
                            ? chosen.filter((k) => k !== kind)
                            : [...chosen, kind],
                        }))
                      }
                    >
                      {audienceLabel(kind)}
                    </button>
                  ))}
                </div>

                <button
                  className="primary"
                  disabled={busy || (needsType && typeFor[item.id] === undefined)}
                  onClick={() => act(() => approve(item))}
                >
                  Одобрить
                </button>
                {needsType && typeFor[item.id] === undefined && (
                  <p className="hint">Сначала выберите формат.</p>
                )}
                <button
                  className="ghost danger"
                  style={{ width: "100%", marginTop: 8 }}
                  disabled={busy}
                  onClick={() => {
                    const comment = prompt("Почему отказ? Текст увидит кандидат.");
                    if (comment) act(() => api.rejectApplication(item.id, comment));
                  }}
                >
                  Отклонить
                </button>
              </>
            )}
          </div>
        );
      })}
    </>
  );
}

function BookRequests() {
  const [items, setItems] = useState<BookRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const reload = () =>
    api
      .bookRequests()
      .then(setItems)
      .catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  return (
    <>
      <p className="hint">
        Книги, которых не нашлось в каталоге и которые участники предложили добавить.
      </p>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="hint">Заявок на книги нет.</p>}
      {items.map((item) => (
        <div className="card" key={item.id}>
          <b>{item.title}</b>
          <div className="meta">
            {item.authors.join(", ")} {item.year && `· ${item.year}`} · предложил {item.user_name}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button
              className="chip chip--on"
              onClick={() => api.approveBookRequest(item.id).then(reload)}
            >
              добавить
            </button>
            <button
              className="chip"
              onClick={() => {
                const comment = prompt("Почему не добавляем?") ?? "";
                api.rejectBookRequest(item.id, comment).then(reload);
              }}
            >
              отклонить
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function Forum({ onOpenEvent }: { onOpenEvent(id: number): void }) {
  const [items, setItems] = useState<Room[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [chatId, setChatId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () =>
    Promise.all([api.rooms(), api.topics()])
      .then(([rooms, live]) => {
        setItems(rooms);
        setTopics(live);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  async function act(action: Promise<unknown>) {
    setBusy(true);
    try {
      await action;
      setError(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  const working = items.find((room) => room.status !== "disabled" && !room.check_error);

  return (
    <>
      <p className="hint">
        Переговорки — темы в одном форуме оргкомитета. Под каждую заявку бот заводит тему,
        зовёт туда кандидата и держит её, пока встреча не пройдёт или не отменится; потом
        удаляет тему вместе с перепиской. В форуме все видят все темы — это оргкомитет и
        ведущие.
      </p>

      {!working && (
        <div className="card">
          <b>Как подключить форум</b>
          <ol className="meta" style={{ paddingLeft: 18, margin: "8px 0 0" }}>
            <li>Создайте в Telegram группу, например «Литклуб · оргкомитет».</li>
            <li>В настройках группы включите «Темы» — группа станет форумом.</li>
            <li>
              Добавьте бота администратором с правами: управление темами, приглашение
              пользователей, удаление сообщений, блокировка пользователей.
            </li>
            <li>
              Узнайте id группы — перешлите любое сообщение из неё боту @userinfobot — и
              впишите ниже. Приставку <code>-100</code> можно не писать.
            </li>
          </ol>
        </div>
      )}

      <div className="row" style={{ margin: "12px 0" }}>
        <input
          value={chatId}
          placeholder="-1001234567890"
          onChange={(e) => setChatId(e.target.value)}
        />
        <button
          className="ghost"
          disabled={busy || !chatId.trim()}
          onClick={() => act(api.addRoom(Number(chatId)).then(() => setChatId("")))}
        >
          Подключить
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      {items.map((room) => (
        <div className="card" key={room.id}>
          <div className="spread">
            <b>{room.title}</b>
            <span
              className={`badge ${room === working ? "badge--ok" : ""}`}
            >
              {room.status === "disabled"
                ? "отключён"
                : room.check_error
                  ? "не работает"
                  : room === working
                    ? "работает"
                    : "запасной"}
            </span>
          </div>
          <div className="meta">
            id {room.chat_id} · живых тем: {room.topics}
          </div>
          {room.check_error && <p className="error">{room.check_error}</p>}
          <div className="row row--wrap" style={{ marginTop: 8 }}>
            <button
              className="chip"
              disabled={busy}
              onClick={() => act(api.checkRoom(room.id))}
            >
              проверить права
            </button>
            <button
              className="chip danger"
              disabled={busy}
              onClick={() => {
                if (
                  confirm(
                    `Отключить «${room.title}»? Сама группа и темы останутся — бот из неё не ` +
                      "выйдет, просто перестанет заводить и удалять темы.",
                  )
                ) {
                  act(api.deleteRoom(room.id));
                }
              }}
            >
              отключить
            </button>
          </div>
        </div>
      ))}

      {topics.length > 0 && (
        <>
          <h2>Живые темы</h2>
          {topics.map((topic) => (
            <div className="card" key={topic.application_id}>
              <div className="spread">
                <b>{topic.book.title}</b>
                <span className="badge">
                  {topic.event_status
                    ? eventStatus(topic.event_status).label
                    : applicationStatusLabel(topic.application_status)}
                </span>
              </div>
              <div className="meta">{topic.user_name}</div>
              <div className="row row--wrap" style={{ marginTop: 8 }}>
                {topic.link && (
                  <a className="chip" href={topic.link}>
                    открыть в Telegram
                  </a>
                )}
                {topic.event_id && (
                  <button className="chip" onClick={() => onOpenEvent(topic.event_id!)}>
                    к встрече
                  </button>
                )}
                <button
                  className="chip danger"
                  disabled={busy}
                  onClick={() => {
                    if (
                      confirm(
                        "Удалить тему вместе со всей перепиской? Кандидата исключат из " +
                          "форума, если других тем у него нет.",
                      )
                    ) {
                      act(api.closeRoom(topic.application_id));
                    }
                  }}
                >
                  закрыть тему
                </button>
              </div>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function Roles({ canEdit }: { canEdit: boolean }) {
  const [people, setPeople] = useState<
    { id: number; name: string; username: string | null; role: string }[]
  >([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => api.people().then(setPeople).catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  async function assign(userId: number, next: string) {
    const person = people.find((p) => p.id === userId);
    if (
      next === "superadmin" &&
      !confirm(
        `Выдать «${person?.name}» права главного администратора? ` +
          "Он сможет менять настройки клуба и раздавать роли, в том числе снимать их с других.",
      )
    ) {
      return;
    }
    try {
      await api.setRole(userId, next);
      setError(null);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    }
  }

  const shown = query.trim()
    ? people.filter((p) =>
        `${p.name} ${p.username ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : people;

  return (
    <>
      {!canEdit && (
        <p className="hint">
          Раздавать роли может только главный администратор. Список ниже — для справки.
        </p>
      )}
      <p className="hint">
        {ROLES.map((r) => `${r.title} — ${r.hint}`).join("; ")}.
      </p>

      <div className="search">
        <input
          type="search"
          value={query}
          placeholder="Найти по имени или @нику"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {error && <p className="error">{error}</p>}

      {shown.length === 0 && <p className="hint">Никого не нашли.</p>}
      {shown.map((person) => (
        <div className="card" key={person.id}>
          <div className="spread">
            <b>{person.name}</b>
            <span className={`badge ${person.role !== "user" ? "badge--ok" : ""}`}>
              {ROLES.find((r) => r.key === person.role)?.title ?? person.role}
            </span>
          </div>
          {person.username && <div className="meta">@{person.username}</div>}
          {canEdit && (
            <div className="row row--wrap" style={{ marginTop: 8 }}>
              {ROLES.map((r) => (
                <button
                  key={r.key}
                  className={`chip ${person.role === r.key ? "chip--on" : ""}`}
                  disabled={person.role === r.key}
                  onClick={() => assign(person.id, r.key)}
                >
                  {r.title}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function Settings({ canEdit }: { canEdit: boolean }) {
  const [items, setItems] = useState<Setting[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  async function save() {
    try {
      await api.saveSettings(
        Object.fromEntries(
          Object.entries(draft).map(([key, value]) => [
            key,
            value === "true" ? true : value === "false" ? false : value,
          ]),
        ),
      );
      setSaved(true);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не сохранилось");
    }
  }

  return (
    <>
      {!canEdit && <p className="hint">Менять параметры может главный администратор.</p>}
      {items.map((item) => (
        <label className="field" key={item.key}>
          <span>{item.title}</span>
          {typeof item.value === "boolean" ? (
            <select
              disabled={!canEdit}
              value={String(draft[item.key] ?? item.value)}
              onChange={(e) => setDraft((prev) => ({ ...prev, [item.key]: e.target.value }))}
            >
              <option value="true">включено</option>
              <option value="false">выключено</option>
            </select>
          ) : (
            <input
              disabled={!canEdit}
              value={draft[item.key] ?? String(item.value)}
              onChange={(e) => setDraft((prev) => ({ ...prev, [item.key]: e.target.value }))}
            />
          )}
          {item.hint && <span className="hint">{item.hint}</span>}
        </label>
      ))}
      {error && <p className="error">{error}</p>}
      {canEdit && (
        <button className="primary" onClick={save}>
          {saved ? "Сохранено" : "Сохранить"}
        </button>
      )}
    </>
  );
}

function Analytics() {
  const [funnel, setFunnel] = useState<Record<string, number> | null>(null);
  const [unmet, setUnmet] = useState<{ title: string; waiting: number }[]>([]);
  const [types, setTypes] = useState<
    { type: string; events: number; attendances: number; avg_score: number | null }[]
  >([]);
  const [programs, setPrograms] = useState<
    { title: string; member_kind: string | null; people: number; attendances: number }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fail = (e: Error) => setError(e.message);
    api.funnel().then(setFunnel).catch(fail);
    api.unmetDemand().then(setUnmet).catch(fail);
    api.byType().then(setTypes).catch(fail);
    api.byKind().then(setPrograms).catch(fail);
  }, []);

  const labels: Record<string, string> = {
    books_with_demand: "книг ждут",
    applications: "заявок",
    approved: "одобрено",
    scheduled: "назначено",
    held: "состоялось",
    attendances: "отметок присутствия",
  };

  return (
    <>
      {error && <p className="error">{error}</p>}
      <h2 style={{ marginTop: 0 }}>Воронка</h2>
      <div className="stats-grid">
        {funnel &&
          Object.entries(labels).map(([key, label]) => (
            <div className="stat" key={key}>
              <b>{funnel[key] ?? 0}</b>
              <span className="meta">{label}</span>
            </div>
          ))}
      </div>

      <h2>Ждут дольше всего</h2>
      {unmet.length === 0 && <p className="hint">Весь спрос разобран.</p>}
      {unmet.map((row) => (
        <div className="spread" key={row.title} style={{ padding: "6px 0" }}>
          <span>{row.title}</span>
          <span className="badge badge--waiting">{row.waiting}</span>
        </div>
      ))}

      <h2>Кто в клубе</h2>
      <table>
        <thead>
          <tr>
            <th>Роль</th>
            <th>Людей</th>
            <th>Посещений</th>
          </tr>
        </thead>
        <tbody>
          {programs.map((row, index) => (
            <tr key={index}>
              <td>{row.title}</td>
              <td>{row.people}</td>
              <td>{row.attendances}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>По форматам</h2>
      <table>
        <thead>
          <tr>
            <th>Формат</th>
            <th>Встреч</th>
            <th>Явка</th>
            <th>Оценка</th>
          </tr>
        </thead>
        <tbody>
          {types.map((row) => (
            <tr key={row.type}>
              <td>{row.type}</td>
              <td>{row.events}</td>
              <td>{row.attendances}</td>
              <td>{row.avg_score ? (row.avg_score / 2).toFixed(1).replace(".", ",") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function formatAnswer(answer: unknown): string {
  if (typeof answer === "boolean") return answer ? "да" : "нет";
  if (Array.isArray(answer)) return answer.join(", ");
  return String(answer ?? "—");
}
