/** Форматирование дат в локальной зоне пользователя.
 *
 * С сервера времена приходят в UTC (ISO с суффиксом Z), браузер сам переводит
 * их в зону устройства — нам остаётся только выбрать формат.
 */

const WEEKDAYS = [
  "воскресенье",
  "понедельник",
  "вторник",
  "среда",
  "четверг",
  "пятница",
  "суббота",
];

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function weekdayName(iso: string): string {
  return WEEKDAYS[new Date(iso).getDay()];
}

/** «понедельник, 8 сентября» */
export function dayLabel(iso: string): string {
  const date = new Date(iso);
  return `${weekdayName(iso)}, ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** «19:00» */
export function timeLabel(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** «8 сентября, 19:00» — подпись слота и назначенного времени. */
export function dateTimeLabel(iso: string): string {
  const date = new Date(iso);
  return `${date.getDate()} ${MONTHS[date.getMonth()]}, ${timeLabel(iso)}`;
}

/** Короткая подпись «8 сентября» для дедлайнов. */
export function shortDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** «через 3 дня» / «сегодня» — сколько осталось до дедлайна голосования. */
export function daysLeft(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "истёк";
  const days = Math.floor(ms / 86_400_000);
  if (days === 0) return "сегодня";
  if (days === 1) return "завтра";
  return `${days} дн.`;
}
