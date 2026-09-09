import type { BookBrief } from "../types";

/** Строка списка книг.
 *
 * Кнопок ровно две — «Читал» и «Хочу меро», как договаривались: список нужен,
 * чтобы быстро отметить, а не чтобы разбираться. «Хочу меро» не создаёт спрос
 * молча — оно открывает карточку на блоке уточнения форматов, иначе
 * оргкомитет получал бы отметки без ответа на вопрос «какую именно встречу».
 */
export function BookRow({
  book,
  onOpen,
  onRead,
  onWant,
  busy = false,
}: {
  book: BookBrief;
  onOpen(): void;
  onRead(): void;
  onWant(): void;
  busy?: boolean;
}) {
  const read = book.reading_status === "finished";

  return (
    <div className="book-row">
      <button onClick={onOpen} aria-label={`Открыть «${book.title}»`}>
        {book.cover_url ? (
          <img className="cover" src={book.cover_url} alt="" loading="lazy" />
        ) : (
          <span className="cover cover--empty" aria-hidden>
            📖
          </span>
        )}
      </button>

      <div>
        <button onClick={onOpen} style={{ textAlign: "left", width: "100%" }}>
          <div className="book-title">{book.title}</div>
          <div className="meta">
            {[book.authors.join(", "), book.year].filter(Boolean).join(" · ") || "—"}
          </div>
        </button>

        <div className="book-actions">
          <button
            className={`chip chip--read ${read ? "chip--on" : ""}`}
            onClick={onRead}
            disabled={busy}
          >
            {read ? "✓ Читал" : "Читал"}
          </button>
          <button
            className={`chip chip--want ${book.demanded ? "chip--on" : ""}`}
            onClick={onWant}
            disabled={busy}
          >
            {book.demanded ? "✓ Жду встречу" : "Хочу меро"}
          </button>
          {book.demand_count > 0 && (
            <span className="chip" title="Столько человек ждут встречу по этой книге">
              👥 {book.demand_count}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
