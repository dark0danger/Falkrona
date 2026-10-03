import { describe, expect, it } from "vitest";
import { cairoInput, lastDayOfWeek } from "./postingTime";

describe("Cairo posting dates",()=>{
  it("uses Cairo's summer offset instead of the browser timezone",()=>{
    expect(cairoInput("2026-10-03T12:00:00Z")).toBe("2026-10-03T15:00");
  });
  it("uses Cairo's winter offset",()=>{
    expect(cairoInput("2026-12-29T12:00:00Z")).toBe("2026-12-29T14:00");
  });
  it("keeps week limits correct across a year boundary",()=>{
    expect(lastDayOfWeek("2026-12-28")).toBe("2027-01-03");
  });
});
