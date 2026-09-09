/** Подписи справочных значений.
 *
 * Отдельным файлом, а не рядом с экранами: их зовут из нескольких мест,
 * и экспорт функции из файла с компонентами ломает горячую перезагрузку.
 */

const AUDIENCE: Record<string, string> = {
  student: "студентов",
  applicant: "абитуриентов",
  staff: "сотрудников",
  guest: "внешних гостей",
};

const KIND: Record<string, string> = {
  student: "студент",
  applicant: "абитуриент",
  staff: "сотрудник",
  guest: "гость",
};

/** «только для студентов» — в родительном падеже, как в фразе целиком. */
export const audienceLabel = (kind: string): string => AUDIENCE[kind] ?? kind;

/** «студент» — как подпись в профиле. */
export const kindLabel = (kind: string): string => KIND[kind] ?? kind;
