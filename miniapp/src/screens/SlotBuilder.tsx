import { useState } from "react";
import * as api from "../api";
import type { ClubEvent } from "../types";

type Draft = { starts_at: string; duration_minutes: number; place: string; note: string };

const EMPTY: Draft = { starts_at: "", duration_minutes: 120, place: "", note: "" };

/** Ближайшее допустимое время — завтрашняя полночь в местной зоне.
 * Встречу, назначенную на сегодня, всё равно не успеют увидеть. */
function earliest(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(0, 0, 0, 0);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

/** Форма окон для организатора.
 *
 * Окон просим несколько: смысл голосования в том, чтобы выбрать из
 * альтернатив, а одно окно превращает его в объявление.
 */
export function SlotBuilder({
  event,
  onDone,
  onError,
}: {
  event: ClubEvent;
  onDone(next: ClubEvent): void;
  onError(message: string): void;
}) {
  const [drafts, setDrafts] = useState<Draft[]>([{ ...EMPTY }, { ...EMPTY }]);
  const [title, setTitle] = useState(event.title ?? "");
  const [description, setDescription] = useState(event.description ?? "");
  const [capacity, setCapacity] = useState("");
  const [busy, setBusy] = useState(false);

  const ready = drafts.filter((draft) => draft.starts_at);

  function patch(index: number, change: Partial<Draft>) {
    setDrafts((rows) => rows.map((row, i) => (i === index ? { ...row, ...change } : row)));
  }

  async function publish() {
    setBusy(true);
    try {
      const next = await api.publishSlots(event.id, {
        title: title || null,
        description: description || null,
        capacity: capacity ? Number(capacity) : null,
        slots: ready.map((draft) => ({
          // datetime-local отдаёт время без зоны — считаем его местным
          // временем устройства, как человек его и вводил.
          starts_at: new Date(draft.starts_at).toISOString(),
          duration_minutes: draft.duration_minutes,
          place: draft.place || null,
          note: draft.note || null,
        })),
      });
      onDone(next);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Когда проведём?</h1>
      <p className="hint">
        Предложите несколько окон — участники отметят удобные, и встреча встанет на самое
        популярное. Чем больше вариантов, тем больше народу дойдёт.
      </p>

      <label className="field">
        <span>Название встречи</span>
        <input value={title} placeholder={event.book.title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="field">
        <span>О чём поговорим</span>
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="field">
        <span>Сколько мест (если ограничено)</span>
        <input
          type="number"
          value={capacity}
          placeholder="без ограничения"
          onChange={(e) => setCapacity(e.target.value)}
        />
      </label>

      <h2>Окна</h2>
      {drafts.map((draft, index) => (
        <div className="card" key={index}>
          <label className="field">
            <span>Дата и время</span>
            <input
              type="datetime-local"
              min={earliest()}
              value={draft.starts_at}
              onChange={(e) => patch(index, { starts_at: e.target.value })}
            />
          </label>
          <div className="grid-2">
            <label className="field">
              <span>Длительность, мин</span>
              <input
                type="number"
                value={draft.duration_minutes}
                onChange={(e) => patch(index, { duration_minutes: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              <span>Место</span>
              <input
                value={draft.place}
                placeholder="Аудитория"
                onChange={(e) => patch(index, { place: e.target.value })}
              />
            </label>
          </div>
          <button
            className="ghost danger"
            disabled={drafts.length === 1}
            onClick={() => setDrafts((rows) => rows.filter((_, i) => i !== index))}
          >
            Убрать это время
          </button>
        </div>
      ))}

      <button
        className="ghost"
        style={{ width: "100%", marginBottom: 12 }}
        onClick={() => setDrafts((rows) => [...rows, { ...EMPTY }])}
      >
        + Ещё окно
      </button>

      <button className="primary" disabled={busy || ready.length === 0} onClick={publish}>
        Опубликовать и открыть голосование
      </button>
    </>
  );
}
