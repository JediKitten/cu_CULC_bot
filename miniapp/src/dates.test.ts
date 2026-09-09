import { describe, expect, it } from "vitest";
import { daysLeft, dateTimeLabel, shortDay, timeLabel } from "./dates";

describe("подписи времени", () => {
  it("показывает время в зоне устройства", () => {
    // Полдень UTC в Москве — три часа дня.
    process.env.TZ = "Europe/Moscow";
    expect(timeLabel("2026-10-01T12:00:00Z")).toBe("15:00");
  });

  it("склеивает дату и время", () => {
    expect(dateTimeLabel("2026-10-01T15:00:00+03:00")).toBe("1 октября, 15:00");
  });

  it("даёт короткую дату", () => {
    expect(shortDay("2026-11-05T10:00:00+03:00")).toBe("5 ноября");
  });
});

describe("сколько осталось", () => {
  it("считает истёкшим прошедший срок", () => {
    expect(daysLeft(new Date(Date.now() - 1000).toISOString())).toBe("истёк");
  });

  it("говорит «сегодня» про ближайшие часы", () => {
    expect(daysLeft(new Date(Date.now() + 3 * 3600_000).toISOString())).toBe("сегодня");
  });

  it("считает дни", () => {
    expect(daysLeft(new Date(Date.now() + 3.5 * 86_400_000).toISOString())).toBe("3 дн.");
  });
});
