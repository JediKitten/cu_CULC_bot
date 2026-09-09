import { describe, expect, it } from "vitest";
import { plural } from "./plural";

describe("склонения", () => {
  const forms: [string, string, string] = ["человек", "человека", "человек"];

  it("выбирает форму по последней цифре", () => {
    expect(plural(1, forms)).toBe("человек");
    expect(plural(2, forms)).toBe("человека");
    expect(plural(5, forms)).toBe("человек");
    expect(plural(21, forms)).toBe("человек");
    expect(plural(22, forms)).toBe("человека");
  });

  it("знает про исключения от 11 до 14", () => {
    expect(plural(11, forms)).toBe("человек");
    expect(plural(12, forms)).toBe("человек");
    expect(plural(14, forms)).toBe("человек");
    expect(plural(112, forms)).toBe("человек");
  });
});
