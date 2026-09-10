import { useEffect, useState } from "react";
import * as api from "../api";
import { Onboarding } from "./Onboarding";
import { dateTimeLabel } from "../dates";
import { kindLabel, levelLabel } from "../labels";
import type { Application, ClubEvent, MyStats, Profile as ProfileData, Reference, User } from "../types";

/** Профиль: анкета целиком редактируемая, плюс двери в «Мои книги», друзей,
 * свои заявки и встречи и — у кого есть права — в админку. */
export function Profile({
  user,
  reference,
  onOpenBooks,
  onOpenFriends,
  onOpenAdmin,
  onOpenEvent,
}: {
  user: User;
  reference: Reference;
  onOpenBooks(): void;
  onOpenFriends(): void;
  onOpenAdmin(): void;
  onOpenEvent(id: number): void;
}) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [stats, setStats] = useState<MyStats | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [events, setEvents] = useState<ClubEvent[]>([]);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.getProfile().then(setProfile);
    api.myStats().then(setStats);
    api.myApplications().then(setApplications);
    api.myEvents().then(setEvents);
  }, []);

  if (editing) {
    return (
      <Onboarding
        initial={profile}
        reference={reference}
        onSaved={(next) => {
          setProfile(next);
          setEditing(false);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const openApplications = applications.filter((item) =>
    ["submitted", "chat_open"].includes(item.status),
  );

  // Анкета пополнилась после того, как часть людей её уже заполнила: у них
  // ступень и направление пусты, а заново спрашивать приложение не станет —
  // анкета формально пройдена. Поэтому напоминаем, но не запираем.
  const needsStudyInfo =
    profile?.member_kind === "student" && profile.study_level === null;

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
            {[
              profile && kindLabel(profile.member_kind),
              profile?.program && programTitle(profile.program, reference),
              profile?.study_level && levelLabel(profile.study_level),
              profile?.year && `${profile.year} курс`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>

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

      {needsStudyInfo && (
        <div className="notice" style={{ borderColor: "var(--live)" }}>
          В анкете появились новые вопросы: ступень и направление. Уточните их —
          это займёт полминуты и поможет собирать встречи под ваш поток.
          <button
            className="primary"
            style={{ marginTop: 8 }}
            onClick={() => setEditing(true)}
          >
            Заполнить
          </button>
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
        onClick={() => setEditing(true)}
      >
        ✏️ Изменить анкету
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

/** Название направления берём из справочника, а не дублируем списком:
 * оргкомитет может переименовать его на сервере. */
function programTitle(program: string, reference: Reference): string {
  return reference.programs.find((item) => item.key === program)?.title ?? program;
}
