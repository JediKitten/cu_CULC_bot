import { useEffect, useState } from "react";
import * as api from "../api";
import { daysLeft, dateTimeLabel } from "../dates";
import { audienceLabel } from "../labels";
import { plural } from "../plural";
import type { Board, ClubEvent, DemandCard } from "../types";

/** Вкладка «Афиша» — один список из двух ярусов.
 *
 * Наверху встречи: сначала те, где идёт голосование за время (по ним ждут
 * действия, и они подсвечены), затем назначенные. Под ними — спрос: книги,
 * которых ждут, но ведущего ещё нет. Это одна и та же история на разных
 * стадиях, поэтому и экран один.
 */
export function Events({
  onOpenEvent,
  onOpenBook,
}: {
  onOpenEvent(id: number): void;
  onOpenBook(bookId: number, want?: boolean): void;
}) {
  const [board, setBoard] = useState<Board | null>(null);
  const [past, setPast] = useState<ClubEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .board()
      .then(setBoard)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="screen error">{error}</p>;
  if (!board) return <p className="screen hint">Загружаем…</p>;

  return (
    <div className="screen">
      <h2 style={{ marginTop: 0 }}>Встречи</h2>
      {board.events.length === 0 && (
        <p className="hint">
          Пока ничего не назначено. Загляните в спрос ниже — может, вы и проведёте.
        </p>
      )}
      {board.events.map((event) => (
        <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
      ))}

      <h2>Ждут встречи</h2>
      {board.demands.length === 0 && (
        <p className="hint">
          Спроса пока нет. Отметьте на карточке книги, что хотите её обсудить, — и он появится.
        </p>
      )}
      {board.demands.map((demand) => (
        <DemandRow
          key={demand.book.id}
          demand={demand}
          onOpen={() => onOpenBook(demand.book.id!, !demand.joined)}
        />
      ))}

      <h2>Прошедшие</h2>
      {past === null ? (
        <button
          className="ghost"
          style={{ width: "100%" }}
          onClick={() => api.pastBoard().then((result) => setPast(result.events))}
        >
          Показать прошедшие
        </button>
      ) : past.length === 0 ? (
        <p className="hint">Ещё ничего не прошло.</p>
      ) : (
        past.map((event) => (
          <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
        ))
      )}
    </div>
  );
}

function EventCard({ event, onOpen }: { event: ClubEvent; onOpen(): void }) {
  const voting = event.status === "voting";
  const mine = event.status === "slot_selection" && event.my_event;

  return (
    <button
      className={`card ${voting || mine ? "card--live" : ""}`}
      style={{ display: "block", width: "100%", textAlign: "left" }}
      onClick={onOpen}
    >
      <div className="spread">
        <b>{event.book.title}</b>
        <span className={`badge ${voting || mine ? "badge--live" : ""}`}>
          {mine
            ? "нужны окна"
            : voting
              ? "выбираем время"
              : event.status === "scheduled"
                ? "назначена"
                : event.status === "cancelled"
                  ? "отменена"
                  : "прошла"}
        </span>
      </div>
      <div className="meta">
        {event.event_type_title} · ведёт {event.organizer_name}
      </div>

      {event.starts_at && (
        <div style={{ marginTop: 6 }}>
          🗓 {dateTimeLabel(event.starts_at)}
          {event.place && ` · ${event.place}`}
        </div>
      )}
      {voting && event.vote_deadline && (
        <div style={{ marginTop: 6 }}>
          🗳 {event.slots.length} {plural(event.slots.length, ["вариант", "варианта", "вариантов"])}{" "}
          времени · голосование до {daysLeft(event.vote_deadline)}
          {event.slots.some((slot) => slot.my_vote) ? " · вы проголосовали" : ""}
        </div>
      )}
      {mine && <div style={{ marginTop: 6 }}>Заявку одобрили — предложите удобные окна.</div>}
      {event.status === "scheduled" && (
        <div className="meta" style={{ marginTop: 6 }}>
          Идут: {event.going}
          {event.my_state === "going" && " · вы записаны"}
        </div>
      )}
      {event.audience.length > 0 && (
        <div className="meta" style={{ marginTop: 4 }}>
          Только для: {event.audience.map(audienceLabel).join(", ")}
        </div>
      )}
    </button>
  );
}

function DemandRow({ demand, onOpen }: { demand: DemandCard; onOpen(): void }) {
  return (
    <button
      className="card"
      style={{ display: "block", width: "100%", textAlign: "left" }}
      onClick={onOpen}
    >
      <div className="spread">
        <b>{demand.book.title}</b>
        <span className="badge badge--waiting">
          {demand.waiting} {plural(demand.waiting, ["человек", "человека", "человек"])}
        </span>
      </div>
      <div className="meta">{demand.book.authors.join(", ")}</div>
      <div className="row row--wrap" style={{ marginTop: 8 }}>
        {demand.types.map((type) => (
          <span key={type.event_type_id} className="badge">
            {type.title} · {type.count}
          </span>
        ))}
      </div>
      <div className="meta" style={{ marginTop: 6 }}>
        {demand.joined ? "Вы в списке ожидающих" : "Нажмите, чтобы присоединиться"}
        {demand.readers > 0 && ` · читали ${demand.readers}`}
        {demand.has_application && " · есть заявка от ведущего"}
      </div>
    </button>
  );
}
