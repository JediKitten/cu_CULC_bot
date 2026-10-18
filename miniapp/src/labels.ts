/** Подписи справочных значений.
 *
 * Отдельным файлом, а не рядом с экранами: их зовут из нескольких мест,
 * и экспорт функции из файла с компонентами ломает горячую перезагрузку.
 */

const AUDIENCE: Record<string, string> = {
  applicant: "абитуриентов",
  bachelor: "бакалавров",
  master: "магистрантов",
  staff: "сотрудников",
  guest: "внешних гостей",
};

const KIND: Record<string, string> = {
  applicant: "абитуриент",
  bachelor: "бакалавр",
  master: "магистрант",
  staff: "сотрудник",
  guest: "внешний гость",
};

/** «только для студентов» — в родительном падеже, как в фразе целиком. */
export const audienceLabel = (kind: string): string => AUDIENCE[kind] ?? kind;

/** «студент» — как подпись в профиле. */
export const kindLabel = (kind: string): string => KIND[kind] ?? kind;

const EVENT_STATUS: Record<string, { label: string; tone: "" | "live" | "ok" | "waiting" }> = {
  slot_selection: { label: "ведущий выбирает время", tone: "waiting" },
  voting: { label: "выбираем время", tone: "live" },
  scheduled: { label: "назначена", tone: "ok" },
  held: { label: "прошла", tone: "" },
  cancelled: { label: "отменена", tone: "" },
};

/** Подпись статуса встречи и цвет бейджа — одни и те же в афише и в оргкомитете. */
export const eventStatus = (status: string) =>
  EVENT_STATUS[status] ?? { label: status, tone: "" as const };

/** CSS-класс бейджа по тону статуса. */
export const toneClass = (tone: string) => (tone ? `badge badge--${tone}` : "badge");

const APPLICATION_STATUS: Record<string, string> = {
  submitted: "новая",
  chat_open: "обсуждаем",
  approved: "одобрена",
  rejected: "отклонена",
  withdrawn: "отозвана",
};

export const applicationStatusLabel = (status: string): string =>
  APPLICATION_STATUS[status] ?? status;
