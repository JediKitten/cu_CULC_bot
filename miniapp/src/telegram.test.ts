import { describe, expect, it } from "vitest";
import { parseFragmentInitData } from "./telegram";

/** Telegram кладёт подписанные данные во фрагмент адреса, а SDK лишь достаёт
 * их оттуда. Когда скрипт SDK не догружается — а через прокси это обычное
 * дело, — этот разбор остаётся единственным способом войти. */
describe("initData из адреса", () => {
  const initData =
    "query_id=AAF_test&user=%7B%22id%22%3A1%7D&auth_date=1757000000&hash=abc123";

  it("достаёт подписанную строку", () => {
    const hash = `#tgWebAppData=${encodeURIComponent(initData)}&tgWebAppVersion=7.0`;
    expect(parseFragmentInitData(hash)).toBe(initData);
  });

  it("работает и без решётки в начале", () => {
    expect(parseFragmentInitData(`tgWebAppData=${encodeURIComponent(initData)}`)).toBe(
      initData,
    );
  });

  it("не путает с похожим по названию параметром", () => {
    const hash = "#tgWebAppVersion=7.0&tgWebAppPlatform=android";
    expect(parseFragmentInitData(hash)).toBe("");
  });

  it("не превращает плюс в пробел", () => {
    // URLSearchParams сделал бы из «a+b» строку «a b» и сломал бы подпись.
    const hash = "#tgWebAppData=hash%3Da%2Bb";
    expect(parseFragmentInitData(hash)).toBe("hash=a+b");
  });

  it("переживает битую последовательность", () => {
    expect(parseFragmentInitData("#tgWebAppData=%E0%A4%A")).toBe("");
  });

  it("отдаёт пустое на пустом адресе", () => {
    expect(parseFragmentInitData("")).toBe("");
  });
});
