import { describe, expect, it } from "vitest";
import { landingRoute } from "./telegramHash";

describe("landingRoute", () => {
  it("sends a bare Telegram launch hash to home", () => {
    expect(landingRoute("#tgWebAppData=abc&tgWebAppVersion=8.0")).toBe("/");
  });

  it("keeps an explicit route that Telegram appended params to", () => {
    expect(landingRoute("#/faq?tgWebAppData=abc")).toBe("/faq");
    expect(landingRoute("#/shop&tgWebAppData=abc")).toBe("/shop");
  });

  it("leaves ordinary app routes alone", () => {
    expect(landingRoute("#/")).toBeNull();
    expect(landingRoute("#/order")).toBeNull();
    expect(landingRoute("")).toBeNull();
  });
});
