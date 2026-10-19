import { useEffect, useState } from "react";
import * as api from "../api";
import { daysLeft, dateTimeLabel } from "../dates";
import { audienceLabel, eventStatus, toneClass } from "../labels";
import { plural } from "../plural";
import type { Board, ClubEvent, DemandCard } from "../types";

/** Вкладка «Афиша» — одна история встречи, разложенная по стадиям.
 *
 * Сверху то, что уже назначено, ниже — где выбирают время (по ним ждут
 * действия, они подсвечены), потом одобренные встречи, где ведущий ещё
 * подбирает окна, и в самом низу спрос: книги, которых ждут, с теми, кто
 * вызвался вести. Раньше всё до голосования сливалось в «ещё не назначено»,
 * и было непонятно, что из этого скоро будет, а что просто хотят.
 */
const PAST_FILTERS: { value: boolean | undefined; label: string }[] = [
  { value: undefined, label: "Все" },
  { value: true, label: "Был" },
  { value: false, label: "Не был" },
];

export function Events({
  onOpenEvent,
  onOpenBook,
}: {
  onOpenEvent(id: number): void;
  onOpenBook(bookId: number, want?: boolean): void;
}) {
  const [board, setBoard] = useState<Board | null>(null);
  const [past, setPast] = useState<ClubEvent[] | null>(null);
  const [pastFilter, setPastFilter] = useState<boolean | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  async function loadPast(attended?: boolean) {
    setPastFilter(attended);
    setPast((await api.pastBoard(attended)).events);
  }

  useEffect(() => {
    api
      .board()
      .then(setBoard)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="screen error">{error}</p>;
  if (!board) return <p className="screen hint">Загружаем…</p>;

  const scheduled = board.events.filter((event) => event.status === "scheduled");
  const voting = board.events.filter((event) => event.status === "voting");
  const preparing = board.preparing ?? [];
  const nothing =
    board.events.length === 0 && preparing.length === 0 && board.demands.length === 0;

  // Пустые разделы не показываем вовсе: заголовок с пояснением, под которым
  // ничего нет, только занимает экран и выглядит поломкой.
  return (
    <div className="screen">
      {nothing && (
        <p className="hint" style={{ marginTop: 0 }}>
          Пока ничего не назначено и не готовится. Откройте книгу в каталоге и нажмите
          «Хочу встречу» — или вызовитесь провести её сами.
        </p>
      )}

      {scheduled.length > 0 && (
        <>
          <h2 style={{ marginTop: 0 }}>Скоро</h2>
          {scheduled.map((event) => (
            <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
          ))}
        </>
      )}

      {voting.length > 0 && (
        <>
          <h2 style={scheduled.length === 0 ? { marginTop: 0 } : undefined}>Выбираем время</h2>
          <p className="hint">Отметьте удобные окна — встреча встанет на самое популярное.</p>
          {voting.map((event) => (
            <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
          ))}
        </>
      )}

      {preparing.length > 0 && (
        <>
          <h2 style={board.events.length === 0 ? { marginTop: 0 } : undefined}>Готовятся</h2>
          <p className="hint">
            Ведущий одобрен и подбирает время. Как только предложит окна, откроется
            голосование.
          </p>
          {preparing.map((event) => (
            <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
          ))}
        </>
      )}

      {board.demands.length > 0 && (
        <>
          <h2
            style={
              board.events.length === 0 && preparing.length === 0 ? { marginTop: 0 } : undefined
            }
          >
            Ждут ведущего
          </h2>
          <p className="hint">
            Книги, по которым хотят встречу. Отметьтесь «хочу» — когда наберётся достаточно
            людей, оргкомитет позовёт ведущего. Или вызовитесь провести сами.
          </p>
          {board.demands.map((demand) => (
            <DemandRow
              key={demand.book.id}
              demand={demand}
              onOpen={() => onOpenBook(demand.book.id!, !demand.joined)}
            />
          ))}
        </>
      )}

      <h2>Прошедшие</h2>
      {past === null ? (
        <button className="ghost" style={{ width: "100%" }} onClick={() => loadPast()}>
          Показать прошедшие
        </button>
      ) : (
        <>
          <div className="row row--wrap" style={{ marginBottom: 10 }}>
            {PAST_FILTERS.map((item) => (
              <button
                key={String(item.value)}
                className={`chip ${pastFilter === item.value ? "chip--on" : ""}`}
                onClick={() => loadPast(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {past.length === 0 ? (
            <p className="hint">
              {pastFilter === true
                ? "Вы пока не были ни на одной встрече."
                : pastFilter === false
                  ? "Вы были на всех прошедших встречах."
                  : "Ещё ничего не прошло."}
            </p>
          ) : (
            past.map((event) => (
              <EventCard key={event.id} event={event} onOpen={() => onOpenEvent(event.id)} />
            ))
          )}
        </>
      )}
    </div>
  );
}

function EventCard({ event, onOpen }: { event: ClubEvent; onOpen(): void }) {
  const voting = event.status === "voting";
  const preparing = event.status === "slot_selection";
  const mine = preparing && event.my_event;
  const status = eventStatus(event.status);

  return (
    <button
      className={`card ${voting || mine ? "card--live" : ""}`}
      style={{ display: "block", width: "100%", textAlign: "left" }}
      onClick={onOpen}
    >
      <div className="spread">
        <b>{event.book.title}</b>
        <span className={mine ? "badge badge--live" : toneClass(status.tone)}>
          {mine ? "нужны окна" : preparing ? "готовится" : status.label}
        </span>
      </div>
      <div className="meta">
        {event.event_type_title} · ведёт {event.my_event ? "вы" : event.organizer_name}
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
      {preparing && !mine && (
        <div className="meta" style={{ marginTop: 6 }}>
          Ведущий подбирает время
        </div>
      )}
      {event.status === "scheduled" && (
        <div className="meta" style={{ marginTop: 6 }}>
          Идут: {event.going}
          {event.my_state === "going" && " · вы записаны"}
        </div>
      )}
      {(event.friends_going.length > 0 || event.friends_waiting.length > 0) && (
        <div className="meta" style={{ marginTop: 4 }}>
          {event.friends_going.length > 0 && `👋 ${event.friends_going.join(", ")} идёт`}
          {event.friends_going.length > 0 && event.friends_waiting.length > 0 && " · "}
          {event.friends_waiting.length > 0 &&
            `${event.friends_waiting.join(", ")} ждёт эту встречу`}
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
  const hosts = demand.hosts ?? [];
  return (
    <button
      className="card"
      style={{ display: "block", width: "100%", textAlign: "left" }}
      onClick={onOpen}
    >
      <div className="spread">
        <b>{demand.book.title}</b>
        <span className="badge badge--waiting">
          {demand.waiting} {plural(demand.waiting, ["хочет", "хотят", "хотят"])}
        </span>
      </div>
      <div className="meta">{demand.book.authors.join(", ")}</div>
      {demand.types.length > 0 && (
        <div className="row row--wrap" style={{ marginTop: 8 }}>
          {demand.types.map((type) => (
            <span key={type.event_type_id} className="badge">
              {type.title} · {type.count}
            </span>
          ))}
        </div>
      )}
      <div className="meta" style={{ marginTop: 6 }}>
        {hosts.length > 0
          ? `🙋 Хочет провести: ${hosts.map((host) => host.name).join(", ")} · на рассмотрении`
          : "Ведущего пока нет"}
      </div>
      <div style={{ marginTop: 6 }}>
        {demand.joined ? (
          <span className="badge badge--ok">✓ Вы в списке</span>
        ) : (
          <span className="meta">Нажмите, чтобы присоединиться</span>
        )}
      </div>
    </button>
  );
}
