import { useEffect, useState } from "react";
import * as api from "../api";
import { BookRow } from "../components/BookRow";
import type { BookBrief } from "../types";

/** Вкладка «Книги»: поиск и список.
 *
 * Пустой запрос показывает каталог клуба — то, что уже завели другие.
 * Как только начинают искать, подключаются Google Books и Open Library:
 * показывать чужой каталог целиком вместо своей полки бессмысленно.
 */
export function Books({ onOpenBook }: { onOpenBook(book: BookBrief, want?: boolean): void }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<BookBrief[]>([]);
  const [degraded, setDegraded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Задержка перед запросом: иначе поиск уходит на каждую букву, а за ним
    // тянутся два внешних источника.
    const timer = setTimeout(() => {
      setLoading(true);
      api
        .searchBooks(query)
        .then((result) => {
          setItems(result.items);
          setDegraded(result.sources_degraded);
          setError(null);
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }, query ? 400 : 0);
    return () => clearTimeout(timer);
  }, [query]);

  /** Книга из внешней выдачи попадает в каталог в момент первого действия
   * с ней: до этого держать у себя чужой каталог незачем. */
  async function materialize(book: BookBrief): Promise<number | null> {
    if (book.id !== null) return book.id;
    if (!book.source || !book.external_id) return null;
    const card = await api.ensureBook(book.source, book.external_id);
    return card.id;
  }

  async function read(book: BookBrief) {
    const key = book.id ? `id${book.id}` : `${book.source}:${book.external_id}`;
    setBusy(key);
    try {
      const id = await materialize(book);
      if (id === null) return;
      const card = await api.markRead(id);
      setItems((rows) => rows.map((row) => (row === book ? { ...row, ...card } : row)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(null);
    }
  }

  async function want(book: BookBrief) {
    const key = book.id ? `id${book.id}` : `${book.source}:${book.external_id}`;
    setBusy(key);
    try {
      const id = await materialize(book);
      if (id === null) return;
      // Отметка ставится сразу, без уточнения формата. Уточнить тип встречи
      // можно на карточке книги — это отдельный, необязательный шаг.
      if (book.demanded) await api.dropDemand(id);
      else await api.addDemand(id, []);
      const card = await api.getBook(id);
      setItems((rows) => rows.map((row) => (row === book ? { ...row, ...card } : row)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не получилось");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="screen">
      <div className="search">
        <input
          type="search"
          value={query}
          placeholder="Автор или название"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {degraded && (
        <p className="notice">
          Один из книжных источников сейчас не отвечает — выдача неполная. Если книги нет,
          её можно завести вручную из карточки поиска.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {loading && <p className="hint">Ищем…</p>}

      {!loading && items.length === 0 && (
        <p className="hint">
          {query
            ? "Ничего не нашли. Попробуйте иначе — или заведите книгу вручную в профиле."
            : "В каталоге пока пусто. Найдите первую книгу поиском."}
        </p>
      )}

      {items.map((book) => (
        <BookRow
          key={book.id ?? `${book.source}:${book.external_id}`}
          book={book}
          busy={busy === (book.id ? `id${book.id}` : `${book.source}:${book.external_id}`)}
          onOpen={() => onOpenBook(book)}
          onRead={() => read(book)}
          onWant={() => want(book)}
        />
      ))}
    </div>
  );
}
