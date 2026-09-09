import { useEffect, useState } from "react";
import * as api from "../api";
import { audienceLabel } from "../labels";
import type { Application, BookRequest, MemberKind, Room, Setting } from "../types";

const KINDS: MemberKind[] = ["student", "applicant", "staff", "guest"];
const TABS = ["Заявки", "Книги", "Переговорки", "Настройки", "Аналитика"] as const;

/** Панель оргкомитета. Пять вкладок вместо пяти экранов: всё, чем управляют
 * руками, живёт в одном месте, и не нужно помнить, где что. */
export function Admin({ onClose, role }: { onClose(): void; role: string }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Заявки");

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
          {TABS.map((item) => (
            <button
              key={item}
              className={`chip ${tab === item ? "chip--on" : ""}`}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>

        {tab === "Заявки" && <Applications />}
        {tab === "Книги" && <BookRequests />}
        {tab === "Переговорки" && <Rooms />}
        {tab === "Настройки" && <Settings canEdit={role === "superadmin"} />}
        {tab === "Аналитика" && <Analytics />}
      </div>
    </div>
  );
}

function Applications() {
  const [items, setItems] = useState<Application[]>([]);
  const [audience, setAudience] = useState<Record<number, MemberKind[]>>({});
  const [error, setError] = useState<string | null>(null);

  const reload = () => api.applications().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, []);

  async function act(action: Promise<unknown>) {
    try {
      await action;
      setError(null);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    }
  }

  return (
    <>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && <p className="hint">Открытых заявок нет.</p>}
      {items.map((item) => {
        const chosen = audience[item.id] ?? [];
        return (
          <div className="card" key={item.id}>
            <div className="spread">
              <b>{item.book.title}</b>
              <span className="badge">
                {item.status === "submitted" ? "новая" : "чат открыт"}
              </span>
            </div>
            <div className="meta">
              {item.user_name}
              {item.user_username && ` · @${item.user_username}`} ·{" "}
              {item.event_type_title ?? `свой формат: ${item.proposed_type_title}`}
            </div>

            <div style={{ margin: "8px 0" }}>
              {Object.entries(item.answers).map(([question, answer]) => (
                <div key={question} className="meta">
                  <b>{question}</b> — {formatAnswer(answer)}
                </div>
              ))}
            </div>

            {item.status === "submitted" && (
              <button
                className="ghost"
                style={{ width: "100%", marginBottom: 8 }}
                onClick={() => act(api.openRoom(item.id))}
              >
                💬 Открыть переговорку
              </button>
            )}
            {item.room_title && <p className="meta">Чат: {item.room_title}</p>}

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
              onClick={() => act(api.approveApplication(item.id, { audience: chosen }))}
            >
              Одобрить
            </button>
            <button
              className="ghost danger"
              style={{ width: "100%", marginTop: 8 }}
              onClick={() => {
                const comment = prompt("Почему отказ? Текст увидит кандидат.");
                if (comment) act(api.rejectApplication(item.id, comment));
              }}
            >
              Отклонить
            </button>
          </div>
        );
      })}
    </>
  );
}

function BookRequests() {
  const [items, setItems] = useState<BookRequest[]>([]);
  const reload = () => api.bookRequests().then(setItems);
  useEffect(() => {
    reload();
  }, []);

  return (
    <>
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

function Rooms() {
  const [items, setItems] = useState<Room[]>([]);
  const [chatId, setChatId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => api.rooms().then(setItems);
  useEffect(() => {
    reload();
  }, []);

  return (
    <>
      <p className="hint">
        Бот не умеет создавать чаты — такого метода нет в Telegram вовсе. Заведите несколько
        пустых супергрупп руками, сделайте бота администратором (права: менять данные чата,
        приглашать, удалять сообщения) и добавьте их сюда по id. Дальше бот сам будет
        раздавать их заявкам и прибирать за собой.
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <input
          value={chatId}
          placeholder="-1001234567890"
          onChange={(e) => setChatId(e.target.value)}
        />
        <button
          className="ghost"
          onClick={() =>
            api
              .addRoom(Number(chatId))
              .then(() => {
                setChatId("");
                setError(null);
                reload();
              })
              .catch((e) => setError(e.message))
          }
        >
          Добавить
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      {items.map((room) => (
        <div className="card" key={room.id}>
          <div className="spread">
            <b>{room.title}</b>
            <span className={`badge ${room.status === "free" ? "badge--ok" : ""}`}>
              {{ free: "свободна", busy: "занята", disabled: "выключена" }[room.status]}
            </span>
          </div>
          <div className="meta">id {room.chat_id}</div>
          {room.check_error && <p className="error">{room.check_error}</p>}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="chip" onClick={() => api.checkRoom(room.id).then(reload)}>
              проверить права
            </button>
            {room.status === "busy" && (
              <button className="chip" onClick={() => api.releaseRoom(room.id).then(reload)}>
                освободить
              </button>
            )}
          </div>
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
    api.settings().then(setItems);
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

  useEffect(() => {
    api.funnel().then(setFunnel);
    api.unmetDemand().then(setUnmet);
    api.byType().then(setTypes);
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
