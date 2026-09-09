import { useEffect, useState } from "react";
import * as api from "../api";
import { BookRow } from "../components/BookRow";
import type { BookBrief } from "../types";

const FILTERS = [
  { key: "", label: "Все" },
  { key: "finished", label: "Прочитал" },
  { key: "reading", label: "Читаю" },
  { key: "want_to_read", label: "Хочу прочитать" },
  { key: "abandoned", label: "Бросил" },
];

/** Дневник списком. Живёт в профиле, а не отдельной вкладкой: главное про
 * книгу человек делает на её карточке, а сюда приходит посмотреть на итог. */
export function MyBooks({
  onOpenBook,
  onClose,
}: {
  onOpenBook(book: BookBrief, want?: boolean): void;
  onClose(): void;
}) {
  const [filter, setFilter] = useState("");
  const [items, setItems] = useState<BookBrief[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .myBooks(filter || undefined)
      .then(setItems)
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button onClick={onClose} aria-label="Назад">
          ←
        </button>
        <b>Мои книги</b>
      </div>

      <div className="screen">
        <div className="row row--wrap" style={{ marginBottom: 12 }}>
          {FILTERS.map((item) => (
            <button
              key={item.key}
              className={`chip ${filter === item.key ? "chip--on" : ""}`}
              onClick={() => setFilter(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {loading && <p className="hint">Загружаем…</p>}
        {!loading && items.length === 0 && (
          <p className="hint">Здесь пусто. Отмечайте книги во вкладке «Книги».</p>
        )}
        {items.map((book) => (
          <BookRow
            key={book.id}
            book={book}
            onOpen={() => onOpenBook(book)}
            onRead={() => api.markRead(book.id!).then(() => setFilter((f) => f))}
            onWant={() => onOpenBook(book, true)}
          />
        ))}
      </div>
    </div>
  );
}
