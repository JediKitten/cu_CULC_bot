import { useState } from "react";
import * as api from "../api";
import type { MemberKind, Profile, Reference } from "../types";

/** Правка обязательной части: фамилия и имя, роль, почта.
 *
 * Впервые это спрашивает бот. Здесь только исправляют — сменилась роль,
 * опечатка в фамилии. Правила те же, что в боте, и живут они на сервере.
 */
export function Identity({
  initial,
  reference,
  onSaved,
  onCancel,
}: {
  initial: Profile;
  reference: Reference;
  onSaved(profile: Profile): void;
  onCancel(): void;
}) {
  const [kind, setKind] = useState<MemberKind>(initial.member_kind);
  const [fullName, setFullName] = useState(initial.full_name);
  const [email, setEmail] = useState(initial.university_email ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const needsEmail = reference.kinds.find((k) => k.key === kind)?.email_required ?? false;

  async function save() {
    setBusy(true);
    try {
      onSaved(
        await api.saveIdentity({
          member_kind: kind,
          full_name: fullName,
          university_email: email || null,
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
      <h1>Кто вы</h1>

      <label className="field">
        <span>Фамилия и имя</span>
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </label>

      <h2>Роль в вузе</h2>
      <div className="row row--wrap">
        {reference.kinds.map((item) => (
          <button
            key={item.key}
            className={`chip ${kind === item.key ? "chip--on" : ""}`}
            onClick={() => setKind(item.key)}
          >
            {item.title}
          </button>
        ))}
      </div>

      {needsEmail && (
        <label className="field" style={{ marginTop: 12 }}>
          <span>Студенческая почта</span>
          <input
            type="email"
            value={email}
            placeholder={`ivanov@${reference.email_domains[0] ?? ""}`}
            onChange={(e) => setEmail(e.target.value)}
          />
          <span className="hint">
            Только домен {reference.email_domains.map((d) => `@${d}`).join(" или ")}
          </span>
        </label>
      )}

      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !fullName.trim()} onClick={save}>
        Сохранить
      </button>
      <button className="ghost" style={{ width: "100%", marginTop: 8 }} onClick={onCancel}>
        Отмена
      </button>
    </div>
  );
}
