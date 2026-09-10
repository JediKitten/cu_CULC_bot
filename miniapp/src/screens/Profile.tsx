import { useEffect, useState } from "react";
import * as api from "../api";
import { Favourites } from "./PersonProfile";
import { Identity } from "./Identity";
import { Preferences } from "./Preferences";
import { dateTimeLabel } from "../dates";
import type {
  Application,
  BookBrief,
  ClubEvent,
  MyStats,
  Profile as ProfileData,
  Reference,
  User,
} from "../types";

/** Профиль: анкета целиком редактируемая, плюс двери в «Мои книги», друзей,
 * свои заявки и встречи и — у кого есть права — в админку. */
export function Profile({
  user,
  reference,
  onOpenBooks,
  onOpenFriends,
  onOpenAdmin,
  onOpenEvent,
  onOpenBook,
}: {
  user: User;
  reference: Reference;
  onOpenBooks(): void;
  onOpenFriends(): void;
  onOpenAdmin(): void;
  onOpenEvent(id: number): void;
  onOpenBook(book: BookBrief): void;
}) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [stats, setStats] = useState<MyStats | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [events, setEvents] = useState<ClubEvent[]>([]);
  const [editing, setEditing] = useState<"none" | "identity" | "preferences">("none");
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    api.getProfile().then(setProfile);
    api.myStats().then(setStats);
    api.myApplications().then(setApplications);
    api.myEvents().then(setEvents);
  }, []);

  if (editing === "identity" && profile) {
    return (
      <Identity
        initial={profile}
        reference={reference}
        onSaved={(next) => {
          setProfile(next);
          setEditing("none");
        }}
        onCancel={() => setEditing("none")}
      />
    );
  }

  if (editing === "preferences") {
    return (
      <Preferences
        initial={profile}
        reference={reference}
        onSaved={(next) => {
          setProfile(next);
          setEditing("none");
        }}
        onCancel={() => setEditing("none")}
      />
    );
  }

  const openApplications = applications.filter((item) =>
    ["submitted", "chat_open"].includes(item.status),
  );

  // Плашка «допройти анкету». Крестик прячет её до следующего запуска бота,
  // «больше не предупреждать» — навсегда; и то и другое решает сервер.
  const showReminder = Boolean(profile?.needs_preferences) && !hidden;

  async function dismiss(forever: boolean) {
    setHidden(true);
    await api.dismissReminder(forever);
  }

  return (
    <div className="screen">
      <div className="row" style={{ marginBottom: 12 }}>
        {user.photo_url ? (
          <img className="avatar" style={{ width: 56, height: 56 }} src={user.photo_url} alt="" />
        ) : (
          <span className="avatar" style={{ width: 56, height: 56 }} aria-hidden>
            {user.display_name.slice(0, 1)}
          </span>
        )}
        <div>
          <h1 style={{ marginBottom: 2 }}>{profile?.full_name || user.display_name}</h1>
          <p className="meta">
            {profile?.member_kind_title}
            {user.tg_username && ` · @${user.tg_username}`}
          </p>
        </div>
      </div>

      <Favourites
        books={profile?.favourites ?? []}
        onOpenBook={onOpenBook}
        empty="Соберите витрину: до четырёх любимых книг, отмечаются звёздочкой на карточке."
      />

      {stats && (
        <div className="stats-grid" style={{ marginBottom: 16 }}>
          <div className="stat">
            <b>{stats.finished}</b>
            <span className="meta">книг прочитано</span>
          </div>
          <div className="stat">
            <b>{stats.finished_this_year}</b>
            <span className="meta">в этом году</span>
          </div>
          <div className="stat">
            <b>{stats.avg_score ? (stats.avg_score / 2).toFixed(1).replace(".", ",") : "—"}</b>
            <span className="meta">средняя оценка</span>
          </div>
          <div className="stat">
            <b>{stats.events_attended}</b>
            <span className="meta">встреч посетил</span>
          </div>
        </div>
      )}

      {showReminder && (
        <div className="notice notice--nudge">
          <button
            className="notice__close"
            aria-label="Скрыть"
            onClick={() => dismiss(false)}
          >
            ✕
          </button>
          <b>Допройти анкету</b>
          <div style={{ marginTop: 4 }}>
            Четыре необязательных вопроса о вкусах — чтобы звать вас на подходящие
            встречи. Любой можно пропустить.
          </div>
          <div className="row row--wrap" style={{ marginTop: 10 }}>
            <button className="primary" style={{ width: "auto" }} onClick={() => setEditing("preferences")}>
              Перейти к анкете
            </button>
            <button className="ghost" onClick={() => dismiss(true)}>
              Больше не предупреждать
            </button>
          </div>
        </div>
      )}

      <button className="ghost" style={{ width: "100%", marginBottom: 8 }} onClick={onOpenBooks}>
        📚 Мои книги
      </button>
      <button className="ghost" style={{ width: "100%", marginBottom: 8 }} onClick={onOpenFriends}>
        👥 Друзья
      </button>
      <button
        className="ghost"
        style={{ width: "100%", marginBottom: 8 }}
        onClick={() => setEditing("identity")}
      >
        ✏️ Имя, роль, почта
      </button>
      <button
        className="ghost"
        style={{ width: "100%", marginBottom: 8 }}
        onClick={() => setEditing("preferences")}
      >
        🎨 Вкусы и предпочтения
      </button>
      {user.role !== "user" && (
        <button className="ghost" style={{ width: "100%", marginBottom: 8 }} onClick={onOpenAdmin}>
          🛠 Оргкомитет
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
                <a className="chip" href={item.invite_link} style={{ marginTop: 8, display: "inline-block" }}>
                  Войти в чат с оргкомитетом
                </a>
              )}
              <button
                className="ghost danger"
                style={{ width: "100%", marginTop: 8 }}
                onClick={() =>
                  api.withdrawApplication(item.id).then(() =>
                    api.myApplications().then(setApplications),
                  )
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
    </div>
  );
}
