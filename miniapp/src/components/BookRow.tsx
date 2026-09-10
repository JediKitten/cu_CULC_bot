import { useState } from "react";
import { StarRating } from "./StarRating";
import type { BookBrief } from "../types";

/** Строка списка книг.
 *
 * Нажатие в любое место строки открывает карточку — раньше срабатывало
 * только по названию, и это ощущалось поломкой. Две кнопки под названием
 * работают на месте: «Читал» ставит отметку и тут же показывает звёзды,
 * «Хочу меро» — отметку и две двери вглубь карточки. Когда с книгой уже
 * всё понятно, дополнительные кнопки сворачиваются: список должен
 * оставаться списком.
 */
/** Оценка книги: своя клубная, а при её отсутствии — мировая.
 *
 * Клубная важнее даже при одной-двух оценках: она про своих, а мировая
 * усредняет миллионы чужих. Но пока в клубе не оценил никто, показывать
 * нечего, и тогда лучше чужая цифра, чем пустота.
 */
function ratingLine(book: BookBrief): string {
  if (book.club_ratings > 0 && book.club_score !== null) {
    const score = (book.club_score / 2).toFixed(1).replace(".", ",");
    return `★ ${score} в клубе · ${book.club_ratings} оц.`;
  }
  if (book.world_rating) {
    const world = book.world_rating.toFixed(1).replace(".", ",");
    return `☆ ${world} в мире${
      book.world_ratings_count ? ` · ${book.world_ratings_count} оц.` : ""
    }`;
  }
  return "";
}

export function BookRow({
  book,
  onOpen,
  onRead,
  onWant,
  onScore,
  onLike,
  onRefine,
  onOrganize,
  busy = false,
}: {
  book: BookBrief;
  onOpen(): void;
  onRead(): void;
  onWant(): void;
  onScore?(score: number | null): void;
  onLike?(): void;
  onRefine?(): void;
  onOrganize?(): void;
  busy?: boolean;
}) {
  const read = book.reading_status === "finished";
  // Показываем звёзды и двери только сразу после нажатия: строка со всем
  // раскрытым у каждой книги превратила бы список в простыню.
  const [justRead, setJustRead] = useState(false);
  const [justWanted, setJustWanted] = useState(false);

  const showStars = justRead && read;
  // Если тип встречи уже уточнён, разворачивать нечего.
  const showWantActions = justWanted && book.demanded;

  return (
    <div className="book-row" onClick={onOpen} role="button" tabIndex={0}>
      {book.cover_url ? (
        <img className="cover" src={book.cover_url} alt="" loading="lazy" />
      ) : (
        <span className="cover cover--empty" aria-hidden>
          📖
        </span>
      )}

      <div>
        <div className="book-title">{book.title}</div>
        <div className="meta">
          {[book.authors.join(", "), book.year].filter(Boolean).join(" · ") || "—"}
        </div>
        <div className="meta">{ratingLine(book)}</div>

        {/* Клики по кнопкам не должны проваливать в карточку — там свои действия. */}
        <div className="book-actions" onClick={(e) => e.stopPropagation()}>
          <button
            className={`chip chip--read ${read ? "chip--on" : ""}`}
            disabled={busy}
            onClick={() => {
              setJustRead(!read);
              onRead();
            }}
          >
            {read ? "✓ Читал" : "Читал"}
          </button>
          <button
            className={`chip chip--want ${book.demanded ? "chip--on" : ""}`}
            disabled={busy}
            onClick={() => {
              setJustWanted(!book.demanded);
              onWant();
            }}
          >
            {book.demanded ? "✓ Жду встречу" : "Хочу меро"}
          </button>
          {onLike && (
            <button
              className={`chip ${book.liked ? "chip--on" : ""}`}
              disabled={busy}
              onClick={onLike}
              aria-label={book.liked ? "Убрать из любимых" : "Нравится"}
            >
              {book.liked ? "♥" : "♡"}
            </button>
          )}
          {book.demand_count > 0 && (
            <span className="chip" title="Столько человек ждут встречу по этой книге">
              👥 {book.demand_count}
            </span>
          )}
        </div>

        {showStars && onScore && (
          <div className="book-actions" onClick={(e) => e.stopPropagation()}>
            <StarRating
              value={book.my_score === null ? null : book.my_score / 2}
              busy={busy}
              onChange={onScore}
            />
          </div>
        )}

        {showWantActions && (
          <div className="book-actions" onClick={(e) => e.stopPropagation()}>
            <button className="chip" onClick={onRefine ?? onOpen}>
              Уточнить тип
            </button>
            <button className="chip" onClick={onOrganize ?? onOpen}>
              Хочу организовать
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
