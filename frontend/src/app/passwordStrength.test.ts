import { describe, it, expect } from "vitest";
import { passwordStrength } from "./passwordStrength";

describe("passwordStrength", () => {
  it("is empty (score 0) with no input", () => {
    expect(passwordStrength("")).toMatchObject({ score: 0, meets: false });
  });
  it("is weak below the minimum and reports how many chars are missing", () => {
    const s = passwordStrength("short"); // 5 of 15
    expect(s.meets).toBe(false);
    expect(s.remaining).toBe(10);
    expect(s.score).toBeLessThanOrEqual(2);
  });
  it("passes the policy at exactly the minimum length", () => {
    const s = passwordStrength("a".repeat(15));
    expect(s.meets).toBe(true);
    expect(s.score).toBeGreaterThanOrEqual(3);
    expect(s.remaining).toBe(0);
  });
  it("rates a long, varied passphrase as strong (score 4)", () => {
    expect(passwordStrength("Minha Senha do Aval 2026!").score).toBe(4);
  });
  it("honours a custom minLength", () => {
    expect(passwordStrength("abcdefgh", 8).meets).toBe(true);
  });
});
