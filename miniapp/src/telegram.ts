/** Обёртка над Telegram WebApp SDK.
 *
 * SDK приходит скриптом с telegram.org, типов в пакете нет — описываем только то,
 * чем реально пользуемся. За пределами Telegram объекта нет вовсе, поэтому каждое
 * обращение допускает его отсутствие: приложение должно открываться и в обычном
 * браузере, иначе его невозможно отлаживать.
 */

type BackButton = {
  show(): void;
  hide(): void;
  onClick(cb: () => void): void;
  offClick(cb: () => void): void;
};

type HapticFeedback = {
  impactOccurred(style: "light" | "medium" | "heavy"): void;
  notificationOccurred(type: "error" | "success" | "warning"): void;
};

type WebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  BackButton: BackButton;
  HapticFeedback: HapticFeedback;
  version?: string;
  isVersionAtLeast?(version: string): boolean;
  ready(): void;
  expand(): void;
  showConfirm?(message: string, callback: (ok: boolean) => void): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  showAlert(message: string): void;
  openTelegramLink?(url: string): void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export const webApp = (): WebApp | undefined => window.Telegram?.WebApp;

/** initData из адреса страницы.
 *
 * Telegram кладёт подписанные данные во фрагмент URL — `#tgWebAppData=...`, —
 * а SDK всего лишь их оттуда разбирает. Читаем сами, потому что скрипт SDK
 * грузится с telegram.org, и если этот запрос не прошёл (прокси, фильтрация,
 * плохая сеть), объекта window.Telegram не будет вовсе, а данные при этом
 * никуда не делись.
 *
 * Считываем один раз при загрузке: фрагмент живёт в адресной строке, и его
 * может затереть навигация внутри приложения.
 */
export function parseFragmentInitData(hash: string): string {
  try {
    // Разбираем вручную, а не через URLSearchParams: тот превращает «+»
    // в пробел, а внутри подписанной строки это ломает хеш.
    const match = /(?:^|&)tgWebAppData=([^&]*)/.exec(hash.replace(/^#/, ""));
    return match ? decodeURIComponent(match[1]) : "";
  } catch {
    // Битая последовательность %-кодов — не повод ронять вход.
    return "";
  }
}

const fragmentInitData = parseFragmentInitData(
  typeof location === "undefined" ? "" : location.hash,
);

/** Открыто ли приложение внутри Telegram — по любому из двух признаков.
 * Нужно, чтобы отличить «нет подписи, потому что не Telegram» от «подпись
 * есть, но SDK не догрузился». */
export const insideTelegram = (): boolean =>
  Boolean(webApp()?.initData || fragmentInitData);

// Тот же цвет, что и --bg в index.css. Дублируется намеренно: шапку и фон
// вокруг окна красит сам Telegram, до CSS приложения он не добирается.
const BACKGROUND = "#0f1012";

export function initTelegram(): void {
  const app = webApp();
  app?.ready();
  app?.expand();
  // Методы появились в Bot API 6.9: в старых клиентах их просто нет, и это
  // не повод падать — тогда шапка останется в теме мессенджера.
  try {
    app?.setHeaderColor?.(BACKGROUND);
    app?.setBackgroundColor?.(BACKGROUND);
  } catch {
    /* клиент старее нужного — переживём */
  }
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  webApp()?.HapticFeedback?.impactOccurred(style);
}

export function getInitData(): string {
  const real = webApp()?.initData;
  if (real) return real;

  // SDK не догрузился, но сам Telegram данные передал — берём их из адреса.
  if (fragmentInitData) return fragmentInitData;

  // Отладка вне Telegram: ?initData=<подписанная строка>. Это не обход входа —
  // подпись всё равно проверяется бэкендом по токену бота, здесь лишь способ
  // передать её без мессенджера. В прод-сборку ветка не попадает.
  if (import.meta.env.DEV) {
    return new URLSearchParams(location.search).get("initData") ?? "";
  }
  return "";
}

/** Кнопка «назад» рисуется самим Telegram, а не нами — поэтому подписка живёт здесь. */
export function useTelegramBackButton(visible: boolean, onBack: () => void): () => void {
  const button = webApp()?.BackButton;
  if (!button) return () => {};
  if (visible) {
    button.onClick(onBack);
    button.show();
  } else {
    button.hide();
  }
  return () => {
    button.offClick(onBack);
    button.hide();
  };
}

/** Умеет ли клиент показывать окна сам.
 *
 * Метод в SDK есть всегда, но вне Telegram и в клиентах старее Bot API 6.2 он
 * молча ничего не делает — а `showConfirm` при этом никогда не зовёт колбэк,
 * и обещание, которого ждёт вызывающий, не разрешается никогда.
 */
function supportsPopups(): boolean {
  const app = webApp();
  return Boolean(app?.showAlert && app.isVersionAtLeast?.("6.2"));
}

/** Показать сообщение пользователю.
 *
 * Раньше здесь было `webApp()?.showAlert(m) ?? alert(m)`, и это давало два окна
 * подряд: showAlert ничего не возвращает, поэтому `??` срабатывал всегда.
 */
export function showMessage(message: string): void {
  if (supportsPopups()) {
    webApp()!.showAlert!(message);
  } else {
    alert(message);
  }
}

/** Спросить «точно?» и дождаться ответа.
 *
 * В Telegram это родное окно, вне его — браузерное confirm. Возвращаем
 * промис: вызывающему нужен ответ, а не колбэк посреди обработчика.
 */
export function askConfirm(message: string): Promise<boolean> {
  const app = webApp();
  if (supportsPopups() && app?.showConfirm) {
    return new Promise((resolve) => app.showConfirm!(message, resolve));
  }
  return Promise.resolve(window.confirm(message));
}

/** Переслать ссылку через Telegram.
 *
 * Отправляем только адрес, без приписанного текста: сообщение с текстом
 * выглядело как пересылка чужого поста, а нужно просто дать ссылку.
 * Обычный window.open из webview не работает — нужен openTelegramLink.
 */
export function shareLink(url: string): boolean {
  const app = webApp();
  if (!app?.openTelegramLink) return false;
  app.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url)}`);
  return true;
}
