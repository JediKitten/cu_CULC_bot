import { useEffect, useState } from "react";
import * as api from "../api";
import { Bars } from "../components/Bars";
import { BookRow } from "../components/BookRow";
import { dateTimeLabel } from "../dates";
import { plural } from "../plural";
import { BookPicker } from "./BookPicker";
import { Settings } from "./Settings";
import type {
  Application,
  BookBrief,
  ClubEvent,
  MyStats,
  Profile as ProfileData,
  Reference,
  User,
} from "../types";

const SHELF = [1, 2, 3, 4];

const FILTERS = [
  { key: "", label: "Все" },
  { key: "liked", label: "♥ Любимые" },
  { key: "finished", label: "Прочитал" },
  { key: "reading", label: "Читаю" },
  { key: "want_to_read", label: "Хочу прочитать" },
  { key: "abandoned", label: "Бросил" },
];

/** Свой профиль.
 *
 * Всё, что человек показывает клубу и о себе знает, на одном экране: витрина
 * любимых книг, цифры, распределение оценок и полка целиком. Настройки ушли
 * за шестерёнку — они нужны редко и не должны занимать место среди списков.
 */
export function Profile({
  user,
  reference,
  onOpenFriends,
  onOpenAdmin,
  onOpenEvent,
  onOpenBook,
}: {
  user: User;
  reference: Reference;
  onOpenFriends(): void;
  onOpenAdmin(): void;
  onOpenEvent(id: number): void;
  onOpenBook(book: BookBrief, want?: boolean): void;
}) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [stats, setStats] = useState<MyStats | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [events, setEvents] = useState<ClubEvent[]>([]);
  const [books, setBooks] = useState<BookBrief[]>([]);
  const [filter, setFilter] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [picking, setPicking] = useState<number | null>(null);
  const [hidden, setHidden] = useState(false);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    api.getProfile().then(setProfile);
    api.myApplications().then(setApplications);
    api.myEvents().then(setEvents);
  }, []);

  useEffect(() => {
    api.myStats().then(setStats);
    // «Любимые» — не статус чтения, а отдельная отметка: фильтруем на клиенте.
    api
      .myBooks(filter && filter !== "liked" ? filter : undefined)
      .then((rows) => setBooks(filter === "liked" ? rows.filter((b) => b.liked) : rows));
  }, [filter, reloads]);

  const refresh = () => setReloads((n) => n + 1);

  async function reloadProfile() {
    setProfile(await api.getProfile());
    refresh();
  }

  async function pick(book: BookBrief) {
    if (picking === null || book.id === null) return;
    await api.setFavourite(book.id, picking);
    setPicking(null);
    await reloadProfile();
  }

  // Плашка «допройти анкету». Крестик прячет её до следующего запуска бота,
  // «больше не предупреждать» — навсегда; и то и другое решает сервер.
  const showReminder = Boolean(profile?.needs_preferences) && !hidden;

  async function dismiss(forever: boolean) {
    setHidden(true);
    await api.dismissReminder(forever);
  }

  if (settingsOpen && profile) {
    return (
      <Settings
        profile={profile}
        reference={reference}
        onSaved={setProfile}
        onClose={() => setSettingsOpen(false)}
      />
    );
  }

  const openApplications = applications.filter((item) =>
    ["submitted", "chat_open"].includes(item.status),
  );

  return (
    <div className="screen">
      <div className="profile-head">
        {user.photo_url ? (
          <img className="avatar avatar--big" src={user.photo_url} alt="" />
        ) : (
          <span className="avatar avatar--big" aria-hidden>
            {(profile?.full_name || user.display_name).slice(0, 1)}
          </span>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ marginBottom: 2 }}>{profile?.full_name || user.display_name}</h1>
          <p className="meta">
            {profile?.member_kind_title}
            {user.tg_username && ` · @${user.tg_username}`}
          </p>
        </div>
        <button
          className="gear"
          aria-label="Настройки"
          onClick={() => setSettingsOpen(true)}
        >
          ⚙
        </button>
      </div>

      {showReminder && (
        <div className="notice notice--nudge">
          <button className="notice__close" aria-label="Скрыть" onClick={() => dismiss(false)}>
            ✕
          </button>
          <b>Допройти анкету</b>
          <div style={{ marginTop: 4 }}>
            Четыре необязательных вопроса о вкусах — чтобы звать вас на подходящие встречи.
            Любой можно пропустить.
          </div>
          <div className="row row--wrap" style={{ marginTop: 10 }}>
            <button
              className="primary"
              style={{ width: "auto" }}
              onClick={() => setSettingsOpen(true)}
            >
              Перейти к анкете
            </button>
            <button className="ghost" onClick={() => dismiss(true)}>
              Больше не предупреждать
            </button>
          </div>
        </div>
      )}

      {/* Витрина видна всегда, даже пустая: четыре места сами говорят, что их
          можно занять, — иначе о такой возможности просто не узнать. */}
      <h2>Любимые книги</h2>
      <div className="favourites">
        {SHELF.map((position) => {
          const book = profile?.favourites.find((b) => b.favourite_position === position);
          if (!book) {
            return (
              <button
                className="favourite-slot"
                key={position}
                aria-label={`Добавить книгу на место ${position}`}
                onClick={() => setPicking(position)}
              >
                +
              </button>
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

      {stats && (
        <div className="stats-grid stats-grid--three">
          <div className="stat">
            <b>{stats.finished}</b>
            <span className="meta">
              {plural(stats.finished, ["книга", "книги", "книг"])} прочитано
            </span>
          </div>
          <div className="stat">
            <b>{stats.events_attended}</b>
            <span className="meta">
              {plural(stats.events_attended, ["встреча", "встречи", "встреч"])}
            </span>
          </div>
          <div className="stat">
            <b>{stats.friends}</b>
            <span className="meta">{plural(stats.friends, ["друг", "друга", "друзей"])}</span>
          </div>
        </div>
      )}

      {stats && stats.ratings > 0 && (
        <>
          <div className="spread" style={{ marginTop: 18 }}>
            <h2 style={{ margin: 0 }}>Как оцениваете</h2>
            <span className="hint">
              {stats.ratings} {plural(stats.ratings, ["оценка", "оценки", "оценок"])}
            </span>
          </div>
          <Bars
            data={stats.ratings_by_score.map((count, index) => ({
              // Подпись у каждого столбика: без неё половинки пришлось бы
              // отсчитывать глазами от ближайшей целой звезды.
              label: String((index + 1) / 2).replace(".", ","),
              value: count,
            }))}
            color="var(--live)"
            hint={`Сколько книг получили каждую оценку. Средняя — ${
              stats.avg_score ? (stats.avg_score / 2).toFixed(1).replace(".", ",") : "—"
            } из 5.`}
          />
        </>
      )}

      <button className="big-card" onClick={onOpenFriends}>
        <span className="big-card__icon" aria-hidden>
          👥
        </span>
        <span>
          <b>Друзья</b>
          <div className="meta">
            {stats && stats.friends > 0
              ? `${stats.friends} ${plural(stats.friends, ["человек", "человека", "человек"])} · найти ещё`
              : "Найти знакомых и посмотреть, что читают"}
          </div>
        </span>
      </button>

      {user.role !== "user" && (
        <button className="big-card" onClick={onOpenAdmin}>
          <span className="big-card__icon" aria-hidden>
            🛠
          </span>
          <span>
            <b>Оргкомитет</b>
            <div className="meta">Заявки, книги, переговорки, роли, аналитика</div>
          </span>
        </button>
      )}

      {openApplications.length > 0 && (
        <>
          <h2>Мои заявки</h2>
          {openApplications.map((item) => (
            <div className="card" key={item.id}>
              <div className="spread">
                <b>{item.book.title}</b>
                <span className="badge">
                  {item.status === "submitted" ? "на рассмотрении" : "обсуждаем в чате"}
                </span>
              </div>
              <div className="meta">{item.event_type_title ?? item.proposed_type_title}</div>
              {item.invite_link && (
                <a
                  className="chip"
                  href={item.invite_link}
                  style={{ marginTop: 8, display: "inline-block" }}
                >
                  Войти в чат с оргкомитетом
                </a>
              )}
              <button
                className="ghost danger"
                style={{ width: "100%", marginTop: 8 }}
                onClick={() =>
                  api
                    .withdrawApplication(item.id)
                    .then(() => api.myApplications().then(setApplications))
                }
              >
                Отозвать заявку
              </button>
            </div>
          ))}
        </>
      )}

      {events.length > 0 && (
        <>
          <h2>Мои встречи</h2>
          {events.map((event) => (
            <button
              key={event.id}
              className="card"
              style={{ display: "block", width: "100%", textAlign: "left" }}
              onClick={() => onOpenEvent(event.id)}
            >
              <div className="spread">
                <b>{event.book.title}</b>
                {event.my_event && <span className="badge badge--live">веду</span>}
              </div>
              <div className="meta">
                {event.starts_at ? dateTimeLabel(event.starts_at) : "время ещё выбирают"}
              </div>
            </button>
          ))}
        </>
      )}

      {/* Полка развёрнута прямо здесь: отдельный экран ради списка своих же
          книг был лишней дверью. */}
      <h2>Мои книги</h2>
      <div className="row row--wrap" style={{ marginBottom: 8 }}>
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

      {books.length === 0 && (
        <p className="hint">
          {filter === "liked"
            ? "Пока ничего не понравилось. Сердечко стоит на строке книги и на её карточке."
            : "Здесь пусто. Отмечайте книги во вкладке «Книги»."}
        </p>
      )}
      {books.map((book) => (
        <BookRow
          key={book.id}
          book={book}
          onOpen={() => onOpenBook(book)}
          onRead={() => api.markRead(book.id!).then(refresh)}
          onLike={() => api.setLike(book.id!, !book.liked).then(refresh)}
          onWant={() =>
            (book.demanded
              ? api.dropDemand(book.id!)
              : api.addDemand(book.id!, [])
            ).then(refresh)
          }
          onScore={(stars) =>
            api
              .saveDiary(book.id!, {
                status: "finished",
                score: stars === null ? null : Math.round(stars * 2),
              })
              .then(refresh)
          }
          onRefine={() => onOpenBook(book, true)}
          onOrganize={() => onOpenBook(book, true)}
        />
      ))}

      {picking !== null && (
        <BookPicker position={picking} onPick={pick} onClose={() => setPicking(null)} />
      )}
    </div>
  );
}
