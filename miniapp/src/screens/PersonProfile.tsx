import { useEffect, useState } from "react";
import * as api from "../api";
import type { BookBrief, PersonProfile as PersonData } from "../types";

/** Чужой профиль: витрина любимых книг и немного цифр.
 *
 * Открыт всем участникам, а не только друзьям: сюда приходят знакомиться,
 * и закрытый профиль этому мешает.
 */
export function PersonProfile({
  userId,
  onClose,
  onOpenBook,
}: {
  userId: number;
  onClose(): void;
  onOpenBook(book: BookBrief): void;
}) {
  const [data, setData] = useState<PersonData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .personProfile(userId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [userId]);

  async function befriend() {
    setBusy(true);
    try {
      await api.addFriend(userId);
      setData(await api.personProfile(userId));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button className="back" onClick={onClose} aria-label="Назад">
          ←
        </button>
      </div>

      <div className="screen">
        {error && <p className="error">{error}</p>}
        {!data && !error && <p className="hint">Загружаем…</p>}

        {data && (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              {data.person.photo_url ? (
                <img
                  className="avatar"
                  style={{ width: 56, height: 56 }}
                  src={data.person.photo_url}
                  alt=""
                />
              ) : (
                <span className="avatar" style={{ width: 56, height: 56 }} aria-hidden>
                  {data.person.display_name.slice(0, 1)}
                </span>
              )}
              <div>
                <h1 style={{ marginBottom: 2 }}>{data.person.display_name}</h1>
                <p className="meta">
                  {[
                    data.person.member_kind_title,
                    data.person.tg_username && `@${data.person.tg_username}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </div>

            {data.person.friendship === "none" && (
              <button
                className="ghost"
                style={{ width: "100%", marginBottom: 12 }}
                disabled={busy}
                onClick={befriend}
              >
                Добавить в друзья
              </button>
            )}
            {data.person.friendship === "outgoing" && (
              <p className="hint">Заявка отправлена, ждём ответа.</p>
            )}
            {data.person.friendship === "incoming" && (
              <button
                className="primary"
                style={{ marginBottom: 12 }}
                disabled={busy}
                onClick={befriend}
              >
                Принять заявку в друзья
              </button>
            )}

            <Favourites books={data.favourites} onOpenBook={onOpenBook} />

            {data.about && <p className="description">{data.about}</p>}

            <div className="stats-grid" style={{ marginTop: 12 }}>
              <div className="stat">
                <b>{data.finished}</b>
                <span className="meta">книг прочитано</span>
              </div>
              <div className="stat">
                <b>{data.events_attended}</b>
                <span className="meta">встреч посетил</span>
              </div>
            </div>

            {data.genres.length > 0 && (
              <>
                <h2>Любимые жанры</h2>
                <div className="row row--wrap">
                  {data.genres.map((genre) => (
                    <span key={genre} className="badge">
                      {genre}
                    </span>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Витрина из четырёх книг — как полка на видном месте. */
export function Favourites({
  books,
  onOpenBook,
  empty,
}: {
  books: BookBrief[];
  onOpenBook(book: BookBrief): void;
  empty?: string;
}) {
  if (books.length === 0) {
    return empty ? <p className="hint">{empty}</p> : null;
  }
  return (
    <>
      <h2>Любимые книги</h2>
      <div className="favourites">
        {[1, 2, 3, 4].map((position) => {
          const book = books.find((b) => b.favourite_position === position);
          if (!book) {
            return (
              <div className="favourite-slot" key={position} aria-hidden>
                +
              </div>
            );
          }
          return (
            <button key={position} onClick={() => onOpenBook(book)} title={book.title}>
              {book.cover_url ? (
                <img className="cover" src={book.cover_url} alt={book.title} />
              ) : (
                <span className="cover cover--empty">📖</span>
              )}
            </button>
          );
        })}
      </div>
    </>
  );
}
