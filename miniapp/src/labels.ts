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
