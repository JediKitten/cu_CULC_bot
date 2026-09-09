import { useEffect, useState } from "react";
import * as api from "../api";
import type { BookCard, EventType, SurveyQuestion } from "../types";

/** Заявка «хотел бы организовать».
 *
 * Вопросы приходят с сервера: формулировки будут меняться, и держать их
 * в двух местах — верный способ однажды разойтись.
 */
export function ApplicationForm({
  book,
  eventTypes,
  onClose,
  onSent,
}: {
  book: BookCard;
  eventTypes: EventType[];
  onClose(): void;
  onSent(): void;
}) {
  const [questions, setQuestions] = useState<SurveyQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [typeId, setTypeId] = useState<number | null>(null);
  const [ownType, setOwnType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.survey().then(setQuestions).catch((e) => setError(e.message));
  }, []);

  async function send() {
    setBusy(true);
    try {
      await api.applyToOrganize({
        book_id: book.id,
        event_type_id: typeId,
        proposed_type_title: ownType || null,
        answers,
      });
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не отправилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay">
      <div className="overlay-head">
        <button onClick={onClose} aria-label="Назад">
          ←
        </button>
        <b>Заявка на организацию</b>
      </div>

      <div className="screen">
        <h1>{book.title}</h1>
        <p className="hint">
          Оргкомитет посмотрит заявку и позовёт вас в чат — обсудить, что будет на встрече.
          После этого вы предложите удобные даты.
        </p>

        <h2>Формат</h2>
        {eventTypes.map((type) => (
          <label className="check" key={type.id}>
            <input
              type="radio"
              name="type"
              checked={typeId === type.id}
              onChange={() => {
                setTypeId(type.id);
                setOwnType("");
              }}
            />
            <span>
              <b>{type.title}</b>
              {type.description && <div className="hint">{type.description}</div>}
            </span>
          </label>
        ))}
        <label className="field">
          <span>Или свой формат</span>
          <input
            value={ownType}
            placeholder="Например: читка вслух"
            onChange={(e) => {
              setOwnType(e.target.value);
              if (e.target.value) setTypeId(null);
            }}
          />
        </label>

        <h2>Пара вопросов</h2>
        {questions.map((question) => (
          <Question
            key={question.key}
            question={question}
            value={answers[question.key]}
            onChange={(value) => setAnswers((prev) => ({ ...prev, [question.key]: value }))}
          />
        ))}

        {error && <p className="error">{error}</p>}
        <button
          className="primary"
          disabled={busy || (typeId === null && !ownType.trim())}
          onClick={send}
        >
          Отправить заявку
        </button>
      </div>
    </div>
  );
}

function Question({
  question,
  value,
  onChange,
}: {
  question: SurveyQuestion;
  value: unknown;
  onChange(value: unknown): void;
}) {
  if (question.type === "bool") {
    return (
      <div className="field">
        <span>
          {question.title}
          {question.required && " *"}
        </span>
        <div className="row">
          {[true, false].map((option) => (
            <button
              key={String(option)}
              className={`chip ${value === option ? "chip--on" : ""}`}
              onClick={() => onChange(option)}
            >
              {option ? "Да" : "Нет"}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (question.type === "choice") {
    return (
      <div className="field">
        <span>
          {question.title}
          {question.required && " *"}
        </span>
        <div className="row row--wrap">
          {(question.options ?? []).map((option) => (
            <button
              key={option}
              className={`chip ${value === option ? "chip--on" : ""}`}
              onClick={() => onChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (question.type === "multi") {
    const chosen = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="field">
        <span>{question.title}</span>
        <div className="row row--wrap">
          {(question.options ?? []).map((option) => (
            <button
              key={option}
              className={`chip ${chosen.includes(option) ? "chip--on" : ""}`}
              onClick={() =>
                onChange(
                  chosen.includes(option)
                    ? chosen.filter((item) => item !== option)
                    : [...chosen, option],
                )
              }
            >
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <label className="field">
      <span>
        {question.title}
        {question.required && " *"}
      </span>
      {question.type === "int" ? (
        <input
          type="number"
          value={(value as number) ?? ""}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        />
      ) : (
        <textarea
          rows={2}
          value={(value as string) ?? ""}
          placeholder={question.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}
