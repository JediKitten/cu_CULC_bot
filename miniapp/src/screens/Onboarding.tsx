import { useState } from "react";
import * as api from "../api";
import type { EventType, MemberKind, Profile } from "../types";

const KINDS: { key: MemberKind; label: string; hint: string }[] = [
  { key: "student", label: "Студент", hint: "учусь здесь" },
  { key: "applicant", label: "Абитуриент", hint: "собираюсь поступать" },
  { key: "staff", label: "Сотрудник", hint: "работаю в вузе" },
  { key: "guest", label: "Внешний гость", hint: "просто люблю книги" },
];

const PACES = [
  { key: "rare", label: "Несколько книг в год" },
  { key: "steady", label: "Примерно книга в месяц" },
  { key: "fast", label: "Несколько книг в месяц" },
];

const EXPERIENCE = [
  { key: "none", label: "Ни разу не был" },
  { key: "visitor", label: "Бывал гостем" },
  { key: "organizer", label: "Вёл встречи" },
];

/** Анкета. Она же форма правки профиля — правила одни и те же, и держать две
 * формы значило бы однажды забыть про одну из них. */
export function Onboarding({
  initial,
  genres,
  eventTypes,
  onSaved,
  onCancel,
}: {
  initial: Profile | null;
  genres: string[];
  eventTypes: EventType[];
  onSaved(profile: Profile): void;
  onCancel?: () => void;
}) {
  const [kind, setKind] = useState<MemberKind>(initial?.member_kind ?? "student");
  const [fullName, setFullName] = useState(initial?.full_name ?? "");
  const [faculty, setFaculty] = useState(initial?.faculty ?? "");
  const [year, setYear] = useState(initial?.year ? String(initial.year) : "");
  const [email, setEmail] = useState(initial?.university_email ?? "");
  const [pace, setPace] = useState(initial?.reading_pace ?? "");
  const [experience, setExperience] = useState(initial?.club_experience ?? "");
  const [chosenGenres, setChosenGenres] = useState<string[]>(initial?.genres ?? []);
  const [chosenTypes, setChosenTypes] = useState<number[]>(initial?.event_type_ids ?? []);
  const [about, setAbout] = useState(initial?.about ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Почта нужна только своим: у абитуриента и внешнего гостя её просто нет,
  // а требовать её означало бы закрыть им вход.
  const emailRequired = kind === "student" || kind === "staff";
  const asksFaculty = kind !== "guest";

  async function save() {
    setBusy(true);
    try {
      const profile = await api.saveProfile({
        member_kind: kind,
        full_name: fullName,
        faculty: faculty || null,
        year: year ? Number(year) : null,
        university_email: email || null,
        reading_pace: (pace || null) as Profile["reading_pace"],
        club_experience: (experience || null) as Profile["club_experience"],
        genres: chosenGenres,
        event_type_ids: chosenTypes,
        about: about || null,
      });
      onSaved(profile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не сохранилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen">
      <h1>{initial ? "Профиль" : "Знакомимся"}</h1>
      <p className="hint">
        {initial
          ? "Всё можно поменять в любой момент."
          : "Пара вопросов — и откроется остальное приложение."}
      </p>

      <h2>Кто вы клубу</h2>
      <div className="row row--wrap">
        {KINDS.map((item) => (
          <button
            key={item.key}
            className={`chip ${kind === item.key ? "chip--on" : ""}`}
            onClick={() => setKind(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="hint">{KINDS.find((item) => item.key === kind)?.hint}</p>

      <label className="field">
        <span>Имя и фамилия</span>
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </label>

      {emailRequired && (
        <label className="field">
          <span>Вузовская почта (обязательно)</span>
          <input
            type="email"
            value={email}
            placeholder="ivanov@univer.ru"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
      )}

      {asksFaculty && (
        <div className="grid-2">
          <label className="field">
            <span>Факультет</span>
            <input value={faculty} onChange={(e) => setFaculty(e.target.value)} />
          </label>
          {kind === "student" && (
            <label className="field">
              <span>Курс</span>
              <input
                type="number"
                min={1}
                max={8}
                value={year}
                onChange={(e) => setYear(e.target.value)}
              />
            </label>
          )}
        </div>
      )}

      <h2>Как читаете</h2>
      <div className="row row--wrap">
        {PACES.map((item) => (
          <button
            key={item.key}
            className={`chip ${pace === item.key ? "chip--on" : ""}`}
            onClick={() => setPace(item.key as Profile["reading_pace"] as string)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <h2>Опыт книжных клубов</h2>
      <div className="row row--wrap">
        {EXPERIENCE.map((item) => (
          <button
            key={item.key}
            className={`chip ${experience === item.key ? "chip--on" : ""}`}
            onClick={() => setExperience(item.key as Profile["club_experience"] as string)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <h2>Любимые жанры</h2>
      <div className="row row--wrap">
        {genres.map((genre) => (
          <button
            key={genre}
            className={`chip ${chosenGenres.includes(genre) ? "chip--on" : ""}`}
            onClick={() =>
              setChosenGenres((prev) =>
                prev.includes(genre) ? prev.filter((g) => g !== genre) : [...prev, genre],
              )
            }
          >
            {genre}
          </button>
        ))}
      </div>

      <h2>Какие встречи интересны</h2>
      <p className="hint">По ним мы поймём, кого звать, когда такая встреча появится.</p>
      {eventTypes.map((type) => (
        <label className="check" key={type.id}>
          <input
            type="checkbox"
            checked={chosenTypes.includes(type.id)}
            onChange={(e) =>
              setChosenTypes((prev) =>
                e.target.checked ? [...prev, type.id] : prev.filter((id) => id !== type.id),
              )
            }
          />
          <span>
            <b>{type.title}</b>
            {type.description && <div className="hint">{type.description}</div>}
          </span>
        </label>
      ))}

      <label className="field">
        <span>О себе (по желанию)</span>
        <textarea rows={2} value={about} onChange={(e) => setAbout(e.target.value)} />
      </label>

      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !fullName.trim()} onClick={save}>
        Сохранить
      </button>
      {onCancel && (
        <button className="ghost" style={{ width: "100%", marginTop: 8 }} onClick={onCancel}>
          Отмена
        </button>
      )}
    </div>
  );
}
