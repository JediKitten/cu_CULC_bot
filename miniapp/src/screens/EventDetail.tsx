import { useEffect, useState } from "react";
import * as api from "../api";
import { StarRating } from "../components/StarRating";
import { audienceLabel } from "../labels";
import { SlotBuilder } from "./SlotBuilder";
import { dateTimeLabel, daysLeft } from "../dates";
import type { ClubEvent } from "../types";

/** Карточка встречи: голосование за время, запись, код присутствия, отзыв.
 *
 * Экран один на все стадии — что показать, решает статус встречи. Так человек
 * возвращается по той же ссылке из уведомления и видит то, что от него сейчас
 * требуется, а не ищет нужную страницу.
 */
export function EventDetail({ eventId, onClose }: { eventId: number; onClose(): void }) {
  const [event, setEvent] = useState<ClubEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<number[]>([]);
  const [code, setCode] = useState("");
  const [shownCode, setShownCode] = useState<string | null>(null);
  const [people, setPeople] = useState<{ id: number; name: string; state: string }[] | null>(
    null,
  );
  const [peopleOpen, setPeopleOpen] = useState(false);

  useEffect(() => {
    api
      .getEvent(eventId)
      .then((loaded) => {
        setEvent(loaded);
        setChosen(loaded.slots.filter((slot) => slot.my_vote).map((slot) => slot.id));
        // Список идущих грузим сразу: ведущему он нужен всегда, а отдельная
        // кнопка «показать» была лишним шагом — и однажды просто не работала.
        if (loaded.can_manage) {
          api.eventPeople(eventId).then(setPeople).catch(() => setPeople([]));
        }
      })
      .catch((e) => setError(e.message));
  }, [eventId]);

  async function run(action: Promise<ClubEvent>) {
    setBusy(true);
    try {
      const next = await action;
      setEvent(next);
      setChosen(next.slots.filter((slot) => slot.my_vote).map((slot) => slot.id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  if (error && !event) {
    return (
      <div className="overlay">
        <Head onClose={onClose} title="Встреча" />
        <p className="screen error">{error}</p>
      </div>
    );
  }
  if (!event) {
    return (
      <div className="overlay">
        <Head onClose={onClose} title="Встреча" />
        <p className="screen hint">Загружаем…</p>
      </div>
    );
  }

  // Организатору после одобрения нужно первым делом расставить окна —
  // остальной экран до этого момента пуст и только сбивал бы с толку.
  if (event.status === "slot_selection") {
    return (
      <div className="overlay">
        <Head onClose={onClose} title={event.book.title} />
        <div className="screen">
          {event.can_manage && !event.my_event && (
            <p className="notice">
              Окна выбирает ведущий — {event.organizer_name}. Если он прислал их в форум,
              можно расставить их здесь за него.
            </p>
          )}
          {event.can_manage ? (
            <SlotBuilder
              event={event}
              onDone={(next) => setEvent(next)}
              onError={(message) => setError(message)}
            />
          ) : (
            <p className="hint">Ведущий ещё выбирает, когда сможет провести встречу.</p>
          )}
          {error && <p className="error">{error}</p>}
          <Manage event={event} busy={busy} onCancel={(reason) => run(api.cancelEvent(event.id, reason))} />
        </div>
      </div>
    );
  }

  const maxVotes = Math.max(1, ...event.slots.map((slot) => slot.votes));

  return (
    <div className="overlay">
      <Head onClose={onClose} title={event.book.title} />
      <div className="screen">
        <h1>{event.title || event.book.title}</h1>
        <p className="meta">
          {event.event_type_title} · ведёт {event.organizer_name}
        </p>
        {event.audience.length > 0 && (
          <p className="meta">Встреча только для {event.audience.map(audienceLabel).join(", ")}</p>
        )}
        {event.description && <p className="description">{event.description}</p>}
        {error && <p className="error">{error}</p>}

        {event.status === "voting" && (
          <>
            <h2>Когда вам удобно?</h2>
            <p className="hint">
              Отметьте все подходящие варианты. По истечении срока встреча встанет на тот,
              что набрал больше голосов; ведущий может закрепить время раньше.
              {event.vote_deadline && ` Осталось: ${daysLeft(event.vote_deadline)}.`}
            </p>
            {event.slots.map((slot) => (
              <button
                key={slot.id}
                className={`slot-row ${chosen.includes(slot.id) ? "slot-row--mine" : ""}`}
                disabled={busy}
                onClick={() => {
                  const next = chosen.includes(slot.id)
                    ? chosen.filter((id) => id !== slot.id)
                    : [...chosen, slot.id];
                  setChosen(next);
                  run(api.voteSlots(event.id, next));
                }}
              >
                <span>
                  <b>{dateTimeLabel(slot.starts_at)}</b>
                  <div className="meta">
                    {slot.duration_minutes} мин
                    {slot.place && ` · ${slot.place}`}
                    {slot.note && ` · ${slot.note}`}
                  </div>
                  <div className="bar">
                    <i style={{ width: `${(slot.votes / maxVotes) * 100}%` }} />
                  </div>
                </span>
                <span className="badge">{slot.votes}</span>
              </button>
            ))}

            {event.can_manage && (
              <div className="card" style={{ marginTop: 12 }}>
                <p className="hint">
                  {event.my_event ? "Вы ведущий" : "Вы в оргкомитете"}: можно закрепить время,
                  не дожидаясь конца голосования, — например, если известно про занятый зал
                  или сессию.
                </p>
                {event.slots.map((slot) => (
                  <button
                    key={slot.id}
                    className="ghost"
                    style={{ width: "100%", marginBottom: 6 }}
                    disabled={busy}
                    onClick={() => run(api.decideSlot(event.id, slot.id))}
                  >
                    Закрепить {dateTimeLabel(slot.starts_at)}
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {event.status === "scheduled" && (
          <>
            <div className="card card--live">
              <b>🗓 {event.starts_at && dateTimeLabel(event.starts_at)}</b>
              {event.place && <div className="meta">{event.place}</div>}
              <div className="meta">
                Идут: {event.going}
                {event.capacity && ` из ${event.capacity}`}
              </div>
            </div>

            <div className="row" style={{ marginBottom: 12 }}>
              {(["going", "declined"] as const).map((state) => (
                <button
                  key={state}
                  className={`chip ${event.my_state === state ? "chip--on" : ""}`}
                  disabled={busy}
                  onClick={() => run(api.setParticipation(event.id, state))}
                >
                  {{ going: "Иду", declined: "Не иду" }[state]}
                </button>
              ))}
            </div>

            {event.my_state === "going" && (
              <p className="notice">
                Вы записаны. Если встреча идёт через клубную афишу вуза, отметьтесь ещё
                и там — так вас посчитают на входе.{" "}
                <a className="link" href="https://t.me/cu_clubs_bot">
                  @cu_clubs_bot
                </a>
              </p>
            )}

            {(event.friends_going.length > 0 || event.friends_waiting.length > 0) && (
              <p className="meta">
                {event.friends_going.length > 0 && `👋 Идут: ${event.friends_going.join(", ")}. `}
                {event.friends_waiting.length > 0 &&
                  `Ждали эту встречу: ${event.friends_waiting.join(", ")}.`}
              </p>
            )}
            {event.my_state === "waitlist" && (
              <p className="notice">Мест уже нет — вы в очереди, сообщим, если освободится.</p>
            )}

            {!event.attended && event.code_available && (
              <div className="card">
                <p className="hint">Ведущий назовёт код на встрече — введите его здесь.</p>
                <div className="row">
                  <input
                    value={code}
                    maxLength={8}
                    placeholder="ABCD"
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                  />
                  <button
                    className="ghost"
                    disabled={busy || code.length < 3}
                    onClick={() => run(api.attend(event.id, code))}
                  >
                    Я здесь
                  </button>
                </div>
              </div>
            )}
            {event.attended && <p className="notice">Вы отмечены на встрече. Хорошего вечера!</p>}

            {event.can_manage && (
              <div className="card">
                <h2 style={{ marginTop: 0 }}>{event.my_event ? "Ведущему" : "Управление"}</h2>
                {shownCode ? (
                  <div className="big-code">{shownCode}</div>
                ) : event.code_available ? (
                  <button
                    className="ghost"
                    style={{ width: "100%" }}
                    onClick={() =>
                      api
                        .attendanceCode(event.id)
                        .then((result) => setShownCode(result.code))
                        .catch((e) => setError(e.message))
                    }
                  >
                    Показать код присутствия
                  </button>
                ) : (
                  <p className="hint">
                    Код появится за полчаса до начала и будет работать несколько часов
                    после — чтобы его нельзя было переслать тому, кто не пришёл.
                  </p>
                )}

                {event.slots.length > 1 && (
                  <details style={{ marginTop: 12 }}>
                    <summary className="link">Перенести на другое окно</summary>
                    <p className="hint">
                      Записавшимся придёт уведомление, их отметки «иду» сбросятся.
                    </p>
                    {event.slots
                      .filter((slot) => slot.starts_at !== event.starts_at)
                      .map((slot) => (
                        <button
                          key={slot.id}
                          className="ghost"
                          style={{ width: "100%", marginBottom: 6 }}
                          disabled={busy}
                          onClick={() => {
                            if (confirm(`Перенести встречу на ${dateTimeLabel(slot.starts_at)}?`)) {
                              run(api.decideSlot(event.id, slot.id));
                            }
                          }}
                        >
                          {dateTimeLabel(slot.starts_at)} · голосов {slot.votes}
                        </button>
                      ))}
                  </details>
                )}
              </div>
            )}
          </>
        )}

        {event.attended && (
          <div className="card">
            <h2 style={{ marginTop: 0 }}>Как прошло?</h2>
            <StarRating
              value={event.my_feedback_score === null ? null : event.my_feedback_score / 2}
              busy={busy}
              onChange={(next) =>
                run(
                  api.sendFeedback(event.id, {
                    score: next === null ? null : Math.round(next * 2),
                  }),
                )
              }
            />
          </div>
        )}

        {event.status === "held" && !event.attended && (
          <p className="hint">
            Оценить можно встречу, на которой вы были: отметка ставится кодом на месте.
          </p>
        )}

        {event.status === "cancelled" && (
          <p className="notice">Встреча отменена. {event.cancel_reason}</p>
        )}

        {event.can_manage && people !== null && (
          <section style={{ marginTop: 18 }}>
            <button
              className="section__head"
              onClick={() => setPeopleOpen((open) => !open)}
              aria-expanded={peopleOpen}
            >
              <span className="section__title">
                Кто идёт
                <span className="hint"> · {people.filter((p) => p.state === "going").length}</span>
              </span>
              <span className={`section__chevron ${peopleOpen ? "is-open" : ""}`} aria-hidden>
                ▾
              </span>
            </button>

            {peopleOpen &&
              (people.length === 0 ? (
                <p className="hint">Пока никто не записался.</p>
              ) : (
                people.map((person) => (
                  <div className="person-row" key={person.id}>
                    <span style={{ flex: 1 }}>{person.name}</span>
                    <span className="badge">
                      {{ going: "идёт", declined: "не идёт", waitlist: "в очереди" }[
                        person.state
                      ] ?? person.state}
                    </span>
                    <button
                      className="chip"
                      disabled={busy}
                      onClick={() => run(api.attendManual(event.id, person.id))}
                    >
                      отметить
                    </button>
                  </div>
                ))
              ))}
          </section>
        )}

        <Manage
          event={event}
          busy={busy}
          onCancel={(reason) => run(api.cancelEvent(event.id, reason))}
        />
      </div>
    </div>
  );
}

/** Нижний блок для ведущего и оргкомитета: тема в форуме и отмена.
 *
 * Отмена только у оргкомитета: ведущему, который не может провести встречу,
 * проще написать в тему, чем решать за клуб в одиночку.
 */
function Manage({
  event,
  busy,
  onCancel,
}: {
  event: ClubEvent;
  busy: boolean;
  onCancel(reason: string): void;
}) {
  if (!event.can_manage) return null;
  const live = ["slot_selection", "voting", "scheduled"].includes(event.status);
  if (!live && !event.topic_link) return null;

  return (
    <div className="card" style={{ marginTop: 18 }}>
      {event.topic_link ? (
        <a className="link" href={event.topic_link}>
          💬 Тема встречи в форуме оргкомитета
        </a>
      ) : (
        live && (
          <p className="hint" style={{ margin: 0 }}>
            Темы в форуме у этой встречи нет. Открыть её можно в оргкомитете, во вкладке
            «Встречи».
          </p>
        )
      )}
      {event.is_admin && live && (
        <button
          className="ghost danger"
          style={{ width: "100%", marginTop: 12 }}
          disabled={busy}
          onClick={() => {
            const reason = prompt(
              "Почему отменяем? Причину увидят ведущий, записавшиеся и голосовавшие.",
            );
            if (reason && reason.trim().length >= 3) onCancel(reason.trim());
          }}
        >
          Отменить встречу
        </button>
      )}
    </div>
  );
}

function Head({ onClose, title }: { onClose(): void; title: string }) {
  return (
    <div className="overlay-head">
      <button onClick={onClose} aria-label="Назад">
        ←
      </button>
      <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</b>
    </div>
  );
}
