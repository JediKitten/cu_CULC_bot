import { useState } from "react";
import * as api from "../api";
import type { Profile, Reference } from "../types";

const PACES = [
  { key: "none", label: "Вообще не читаю" },
  { key: "rare", label: "Несколько книг в год" },
  { key: "steady", label: "Примерно книга в месяц" },
  { key: "fast", label: "Несколько книг в месяц" },
];

const EXPERIENCE = [
  { key: "none", label: "Ни разу не был" },
  { key: "visitor", label: "Бывал гостем" },
  { key: "organizer", label: "Вёл встречи" },
];

/** Необязательная часть анкеты: вкусы.
 *
 * Обязательное — имя, роль, почта — спрашивает бот. Здесь всё можно
 * пропустить: пустой ответ честнее выдуманного, а недоспрошенный человек
 * всё равно полноценный участник клуба.
 */
export function Preferences({
  initial,
  reference,
  onSaved,
  onCancel,
}: {
  initial: Profile | null;
  reference: Reference;
  onSaved(profile: Profile): void;
  onCancel?: () => void;
}) {
  const [pace, setPace] = useState(initial?.reading_pace ?? "");
  const [experience, setExperience] = useState(initial?.club_experience ?? "");
  const [genres, setGenres] = useState<string[]>(initial?.genres ?? []);
  const [types, setTypes] = useState<number[]>(initial?.event_type_ids ?? []);
  const [about, setAbout] = useState(initial?.about ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      onSaved(
        await api.savePreferences({
          reading_pace: pace || null,
          club_experience: experience || null,
          genres,
          event_type_ids: types,
          about: about || null,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не сохранилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen">
      <h1>Немного о вкусах</h1>
      <p className="hint">
        Четыре вопроса, чтобы звать вас на подходящие встречи. Любой можно
        пропустить — просто не отвечайте.
      </p>

      <h2>Как много читаете?</h2>
      <Choice options={PACES} value={pace} onChange={setPace} />

      <h2>Опыт книжных клубов</h2>
      <Choice options={EXPERIENCE} value={experience} onChange={setExperience} />

      <h2>Любимые жанры</h2>
      <div className="row row--wrap">
        {reference.genres.map((genre) => (
          <button
            key={genre}
            className={`chip ${genres.includes(genre) ? "chip--on" : ""}`}
            onClick={() =>
              setGenres((prev) =>
                prev.includes(genre) ? prev.filter((g) => g !== genre) : [...prev, genre],
              )
            }
          >
            {genre}
          </button>
        ))}
      </div>

      <h2>Какие встречи хотели бы посещать?</h2>
      {reference.event_types.map((type) => (
        <label className="check" key={type.id}>
          <input
            type="checkbox"
            checked={types.includes(type.id)}
            onChange={(e) =>
              setTypes((prev) =>
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

      <label className="field" style={{ marginTop: 12 }}>
        <span>О себе — если хочется</span>
        <textarea rows={2} value={about} onChange={(e) => setAbout(e.target.value)} />
      </label>

      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy} onClick={save}>
        Сохранить
      </button>
      {onCancel && (
        <button className="ghost" style={{ width: "100%", marginTop: 8 }} onClick={onCancel}>
          Назад
        </button>
      )}
    </div>
  );
}

/** Один выбор из списка с возможностью снять его вовсе — это и есть «пропустить». */
function Choice({
  options,
  value,
  onChange,
}: {
  options: { key: string; label: string }[];
  value: string;
  onChange(next: string): void;
}) {
  return (
    <div className="row row--wrap">
      {options.map((item) => (
        <button
          key={item.key}
          className={`chip ${value === item.key ? "chip--on" : ""}`}
          onClick={() => onChange(value === item.key ? "" : item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
