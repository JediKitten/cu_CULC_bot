import { useEffect, useState } from "react";
import * as api from "../api";
import type { BookBrief } from "../types";

/** Выбор книги на витрину — прямо из профиля.
 *
 * Раньше поставить книгу в любимые можно было только с её карточки: чтобы
 * собрать полку из четырёх, приходилось искать каждую по отдельности.
 * Здесь показываем свою полку, а поиск подключается, когда нужной в ней нет.
 */
export function BookPicker({
  position,
  onPick,
  onClose,
}: {
  position: number;
  onPick(book: BookBrief): void;
  onClose(): void;
}) {
  const [mine, setMine] = useState<BookBrief[]>([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<BookBrief[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .myBooks()
      .then(setMine)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) {
      setFound(null);
      return;
    }
    const timer = setTimeout(
      () => api.searchBooks(query).then((result) => setFound(result.items)),
      400,
    );
    return () => clearTimeout(timer);
  }, [query]);

  const shown = found ?? mine;

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button className="back" onClick={onClose} aria-label="Назад">
          ←
        </button>
        <b>Место {position} на витрине</b>
      </div>

      <div className="screen">
        <div className="search">
          <input
            type="search"
            value={query}
            placeholder="Найти книгу"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        {loading && <p className="hint">Загружаем…</p>}
        {!loading && shown.length === 0 && (
          <p className="hint">
            {query ? "Ничего не нашли." : "Ваша полка пуста — найдите книгу поиском."}
          </p>
        )}

        {shown.map((book) => (
          <button
            key={book.id ?? `${book.source}:${book.external_id}`}
            className="book-row"
            style={{ width: "100%", textAlign: "left" }}
            onClick={() => onPick(book)}
          >
            {book.cover_url ? (
              <img className="cover" src={book.cover_url} alt="" loading="lazy" />
            ) : (
              <span className="cover cover--empty" aria-hidden>
                📖
              </span>
            )}
            <span>
              <div className="book-title">{book.title}</div>
              <div className="meta">{book.authors.join(", ")}</div>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
