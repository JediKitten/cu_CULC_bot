import { describe, expect, it } from "vitest";
import { audienceLabel, kindLabel } from "./labels";

describe("подписи аудитории", () => {
  it("склоняет категории для фразы «только для…»", () => {
    expect(audienceLabel("student")).toBe("студентов");
    expect(audienceLabel("guest")).toBe("внешних гостей");
  });

  it("не падает на незнакомом значении", () => {
    // Сервер может завести новую категорию раньше, чем обновится приложение.
    expect(audienceLabel("alumni")).toBe("alumni");
    expect(kindLabel("alumni")).toBe("alumni");
  });
});
