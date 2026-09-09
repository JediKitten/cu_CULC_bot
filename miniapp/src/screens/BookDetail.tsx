import { useEffect, useState } from "react";
import * as api from "../api";
import { StarRating } from "../components/StarRating";
import type { BookBrief, BookCard, EventType } from "../types";

const STATUSES: { key: string; label: string }[] = [
  { key: "want_to_read", label: "Хочу прочитать" },
  { key: "reading", label: "Читаю" },
  { key: "finished", label: "Прочитал" },
  { key: "abandoned", label: "Бросил" },
];

/** Карточка книги — она же читательский дневник.
 *
 * Отдельной вкладки дневника нет намеренно: всё, что человек делает с книгой,
 * должно жить в одном месте, рядом с самой книгой.
 */
export function BookDetail({
  book,
  eventTypes,
  wantOnOpen,
  onClose,
  onOrganize,
  onOpenEvent,
}: {
  book: BookBrief;
  eventTypes: EventType[];
  wantOnOpen: boolean;
  onClose(): void;
  onOrganize(card: BookCard): void;
  onOpenEvent(id: number): void;
}) {
  const [card, setCard] = useState<BookCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wantOpen, setWantOpen] = useState(wantOnOpen);
  const [chosen, setChosen] = useState<number[]>([]);
  const [review, setReview] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const id =
          book.id ??
          (book.source && book.external_id
            ? (await api.ensureBook(book.source, book.external_id)).id
            : null);
        if (id === null) throw new Error("Книга недоступна");
        const loaded = await api.getBook(id);
        setCard(loaded);
        setChosen(loaded.my_demand_type_ids);
        setReview(loaded.my_review ?? "");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не открылось");
      }
    }
    load();
  }, [book]);

  async function update(action: Promise<BookCard>) {
    setBusy(true);
    try {
      const next = await action;
      setCard(next);
      setChosen(next.my_demand_type_ids);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function saveDemand() {
    if (!card?.id || chosen.length === 0) return;
    setBusy(true);
    try {
      await api.addDemand(card.id, chosen);
      setCard(await api.getBook(card.id));
      setWantOpen(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function dropDemand() {
    if (!card?.id) return;
    setBusy(true);
    try {
      await api.dropDemand(card.id);
      setCard(await api.getBook(card.id));
    } finally {
      setBusy(false);
    }
  }

  if (error && !card) {
    return (
      <div className="overlay">
        <Head onClose={onClose} title="Книга" />
        <div className="screen">
          <p className="error">{error}</p>
        </div>
      </div>
    );
  }

  if (!card) {
    return (
      <div className="overlay">
        <Head onClose={onClose} title="Книга" />
        <div className="screen">
          <p className="hint">Загружаем…</p>
        </div>
      </div>
    );
  }

  const status = card.reading_status;

  return (
    <div className="overlay">
      <Head onClose={onClose} title={card.title} />

      <div className="screen">
        <div className="row" style={{ alignItems: "flex-start", marginBottom: 16 }}>
          {card.cover_url ? (
            <img className="detail-cover" src={card.cover_url} alt="" />
          ) : (
            <span className="detail-cover cover--empty" aria-hidden>
              📖
            </span>
          )}
          <div>
            <h1>{card.title}</h1>
            <p className="meta">
              {[card.authors.join(", "), card.year, card.page_count && `${card.page_count} с.`]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {card.ratings_count > 0 && (
              <p className="meta">
                Оценка клуба: {card.avg_score?.toFixed(1).replace(".", ",")} · {card.ratings_count}{" "}
                оц. · читали {card.readers_count}
              </p>
            )}
          </div>
        </div>

        {error && <p className="error">{error}</p>}

        <h2>Мой дневник</h2>
        <div className="row row--wrap" style={{ marginBottom: 10 }}>
          {STATUSES.map(({ key, label }) => (
            <button
              key={key}
              className={`chip ${status === key ? "chip--on" : ""}`}
              disabled={busy}
              onClick={() =>
                update(
                  status === key
                    ? api.dropDiary(card.id!)
                    : api.saveDiary(card.id!, { status: key, score: card.my_score, review }),
                )
              }
            >
              {label}
            </button>
          ))}
        </div>

        {status && (
          <>
            <StarRating
              value={card.my_score === null ? null : card.my_score / 2}
              busy={busy}
              onChange={(next) =>
                update(
                  api.saveDiary(card.id!, {
                    status,
                    score: next === null ? null : Math.round(next * 2),
                    review,
                  }),
                )
              }
            />
            <label className="field" style={{ marginTop: 10 }}>
              <span>Отзыв</span>
              <textarea
                rows={3}
                value={review}
                placeholder="Пара слов для своих"
                onChange={(e) => setReview(e.target.value)}
                onBlur={() =>
                  review !== (card.my_review ?? "") &&
                  update(api.saveDiary(card.id!, { status, score: card.my_score, review }))
                }
              />
            </label>
          </>
        )}

        <h2>Встреча по этой книге</h2>
        {card.open_event_id ? (
          <div className="card card--live">
            <p>По этой книге уже назначена встреча.</p>
            <button className="primary" onClick={() => onOpenEvent(card.open_event_id!)}>
              Открыть встречу
            </button>
          </div>
        ) : (
          <>
            <p className="meta">
              Ждут встречу: {card.demand_count}
              {card.demand_readers > 0 && ` · из них читали ${card.demand_readers}`}
            </p>
            {card.demand_types.length > 0 && (
              <div className="row row--wrap" style={{ margin: "8px 0" }}>
                {card.demand_types.map((type) => (
                  <span key={type.event_type_id} className="badge">
                    {type.title} · {type.count}
                  </span>
                ))}
              </div>
            )}

            {!wantOpen && !card.demanded && (
              <button className="primary" onClick={() => setWantOpen(true)}>
                Хочу встречу по этой книге
              </button>
            )}

            {(wantOpen || card.demanded) && (
              <div className="card">
                <p className="hint">
                  Какие форматы вам интересны? Можно отметить несколько — оргкомитет увидит,
                  чего именно ждут.
                </p>
                {eventTypes.map((type) => (
                  <label className="check" key={type.id}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(type.id)}
                      onChange={(e) =>
                        setChosen((prev) =>
                          e.target.checked
                            ? [...prev, type.id]
                            : prev.filter((id) => id !== type.id),
                        )
                      }
                    />
                    <span>
                      <b>{type.title}</b>
                      {type.description && <div className="hint">{type.description}</div>}
                      {!type.requires_reading && (
                        <div className="hint">Читать заранее не обязательно</div>
                      )}
                    </span>
                  </label>
                ))}
                <button
                  className="primary"
                  disabled={busy || chosen.length === 0}
                  onClick={saveDemand}
                >
                  {card.demanded ? "Сохранить выбор" : "Жду такую встречу"}
                </button>
                {card.demanded && (
                  <button
                    className="ghost danger"
                    style={{ marginTop: 8, width: "100%" }}
                    disabled={busy}
                    onClick={dropDemand}
                  >
                    Больше не жду
                  </button>
                )}
              </div>
            )}

            <button
              className="ghost"
              style={{ width: "100%", marginTop: 8 }}
              disabled={busy || card.my_application_status !== null}
              onClick={() => onOrganize(card)}
            >
              {card.my_application_status
                ? "Ваша заявка на рассмотрении"
                : "Хотел бы организовать"}
            </button>
          </>
        )}

        {card.description && (
          <>
            <h2>О книге</h2>
            <p className="description">{card.description}</p>
          </>
        )}
      </div>
    </div>
  );
}

function Head({ onClose, title }: { onClose(): void; title: string }) {
  return (
    <div className="overlay-head">
      <button onClick={onClose} aria-label="Назад">
        ←
      </button>
      <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {title}
      </b>
    </div>
  );
}
