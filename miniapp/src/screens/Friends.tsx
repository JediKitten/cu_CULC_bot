import { useEffect, useState } from "react";
import * as api from "../api";
import type { Friends as FriendsData, PersonBrief } from "../types";

/** Друзья: поиск участников, входящие и исходящие заявки. */
export function Friends({
  onClose,
  onOpenPerson,
}: {
  onClose(): void;
  onOpenPerson(id: number): void;
}) {
  const [data, setData] = useState<FriendsData | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<PersonBrief[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = () => api.friends().then(setData).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) {
      setFound([]);
      return;
    }
    const timer = setTimeout(() => {
      api.searchPeople(query).then(setFound).catch(() => setFound([]));
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);

  async function add(person: PersonBrief) {
    await api.addFriend(person.id);
    setQuery("");
    setFound([]);
    reload();
  }

  async function remove(person: PersonBrief) {
    await api.dropFriend(person.id);
    reload();
  }

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button onClick={onClose} aria-label="Назад">
          ←
        </button>
        <b>Друзья</b>
      </div>

      <div className="screen">
        <div className="search">
          <input
            type="search"
            value={query}
            placeholder="Найти участника по имени"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {error && <p className="error">{error}</p>}

        {found.map((person) => (
          <Person
            key={person.id}
            person={person}
            onOpen={() => onOpenPerson(person.id)}
            action={
              person.friendship === "none" ? (
                <button className="chip" onClick={() => add(person)}>
                  добавить
                </button>
              ) : (
                <span className="badge">{label(person.friendship)}</span>
              )
            }
          />
        ))}

        {data?.incoming.length ? (
          <>
            <h2>Хотят дружить</h2>
            {data.incoming.map((person) => (
              <Person
                key={person.id}
                person={person}
                onOpen={() => onOpenPerson(person.id)}
                action={
                  <>
                    <button className="chip chip--on" onClick={() => add(person)}>
                      принять
                    </button>
                    <button className="chip" onClick={() => remove(person)}>
                      нет
                    </button>
                  </>
                }
              />
            ))}
          </>
        ) : null}

        <h2>Мои друзья</h2>
        {data && data.friends.length === 0 && (
          <p className="hint">Пока никого. Найдите знакомых поиском выше.</p>
        )}
        {data?.friends.map((person) => (
          <Person
            key={person.id}
            person={person}
            onOpen={() => onOpenPerson(person.id)}
            action={
              <button className="chip" onClick={() => remove(person)}>
                убрать
              </button>
            }
          />
        ))}

        {data?.outgoing.length ? (
          <>
            <h2>Ждут ответа</h2>
            {data.outgoing.map((person) => (
              <Person
                key={person.id}
                person={person}
                onOpen={() => onOpenPerson(person.id)}
                action={
                  <button className="chip" onClick={() => remove(person)}>
                    отменить
                  </button>
                }
              />
            ))}
          </>
        ) : null}
      </div>
    </div>
  );
}

function Person({
  person,
  action,
  onOpen,
}: {
  person: PersonBrief;
  action: React.ReactNode;
  onOpen?: () => void;
}) {
  return (
    <div className="person-row" onClick={onOpen} role={onOpen ? "button" : undefined}>
      {person.photo_url ? (
        <img className="avatar" src={person.photo_url} alt="" />
      ) : (
        <span className="avatar" aria-hidden>
          {person.display_name.slice(0, 1)}
        </span>
      )}
      <span style={{ flex: 1 }}>
        <b>{person.display_name}</b>
        <div className="meta">
          {[person.member_kind_title, person.tg_username && `@${person.tg_username}`]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </span>
      {/* Кнопки не должны проваливать в профиль — у них своё действие. */}
      <span onClick={(e) => e.stopPropagation()}>{action}</span>
    </div>
  );
}

function label(state: PersonBrief["friendship"]): string {
  const titles: Record<string, string> = {
    friends: "уже друзья",
    outgoing: "заявка отправлена",
    incoming: "ждёт вашего ответа",
  };
  return titles[state ?? "none"] ?? "";
}
