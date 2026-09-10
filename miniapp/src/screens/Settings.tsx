import { useState } from "react";
import { Identity } from "./Identity";
import { Preferences } from "./Preferences";
import type { Profile, Reference } from "../types";

/** Настройки за шестерёнкой: обе части анкеты в одном месте.
 *
 * Раньше это были две кнопки в профиле среди прочих — они занимали место
 * и путались с переходами в списки. Настройки — редкое действие, им место
 * за отдельной дверью.
 */
export function Settings({
  profile,
  reference,
  onSaved,
  onClose,
}: {
  profile: Profile;
  reference: Reference;
  onSaved(next: Profile): void;
  onClose(): void;
}) {
  const [tab, setTab] = useState<"none" | "identity" | "preferences">("none");

  if (tab === "identity") {
    return (
      <div className="overlay">
        <Head onClose={() => setTab("none")} />
        <Identity
          initial={profile}
          reference={reference}
          onSaved={(next) => {
            onSaved(next);
            setTab("none");
          }}
          onCancel={() => setTab("none")}
        />
      </div>
    );
  }

  if (tab === "preferences") {
    return (
      <div className="overlay">
        <Head onClose={() => setTab("none")} />
        <Preferences
          initial={profile}
          reference={reference}
          onSaved={(next) => {
            onSaved(next);
            setTab("none");
          }}
          onCancel={() => setTab("none")}
        />
      </div>
    );
  }

  return (
    <div className="overlay">
      <Head onClose={onClose} />
      <div className="screen">
        <h1>Настройки</h1>

        <button className="big-card" onClick={() => setTab("identity")}>
          <span className="big-card__icon" aria-hidden>
            🪪
          </span>
          <span>
            <b>Анкета</b>
            <div className="meta">
              {profile.full_name} · {profile.member_kind_title}
              {profile.university_email && ` · ${profile.university_email}`}
            </div>
          </span>
        </button>

        <button className="big-card" onClick={() => setTab("preferences")}>
          <span className="big-card__icon" aria-hidden>
            🎨
          </span>
          <span>
            <b>Вкусы и предпочтения</b>
            <div className="meta">
              {profile.preferences_at
                ? [
                    profile.genres.length > 0 && `${profile.genres.length} жанров`,
                    profile.event_type_ids.length > 0 &&
                      `${profile.event_type_ids.length} форматов`,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "заполнено"
                : "не заполнено — четыре необязательных вопроса"}
            </div>
          </span>
        </button>
      </div>
    </div>
  );
}

function Head({ onClose }: { onClose(): void }) {
  return (
    <div className="overlay-head">
      <button className="back" onClick={onClose} aria-label="Назад">
        ←
      </button>
    </div>
  );
}
