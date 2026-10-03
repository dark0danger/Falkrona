import { describe, expect, it } from "vitest";
import { componentStatus } from "./health";

describe("componentStatus", () => {
  it("keeps missing health explicit", () => {
    expect(componentStatus({ status: "loading" }, "database")).toBe("unknown");
  });

  it("returns the backend component state", () => {
    expect(
      componentStatus(
        { status: "ready", components: { database: { status: "ok" } } },
        "database",
      ),
    ).toBe("ok");
  });
});
