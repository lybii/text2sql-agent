import { describe, expect, it } from "vitest";

import { formatCell, formatMoney, humanizeColumn, timeLeft } from "./format";

describe("format", () => {
  it("formats VND compactly", () => {
    expect(formatMoney(2_458_707_000_000)).toBe("2.458,71 tỷ");
    expect(formatMoney(12_300_000)).toBe("12,3 triệu");
  });

  it("formats cells by column semantics", () => {
    expect(formatCell("completed_revenue", 1_500_000_000)).toBe("1,5 tỷ");
    expect(formatCell("cancellation_rate", 12.5)).toBe("12,5%");
    expect(formatCell("year", 2025)).toBe("2025");
    expect(formatCell("month", "2025-03-01")).toBe("03/2025");
    expect(formatCell("is_available", true)).toBe("Có");
    expect(formatCell("city", null)).toBe("—");
  });

  it("humanizes known columns", () => {
    expect(humanizeColumn("completed_revenue")).toBe("Doanh thu");
    expect(humanizeColumn("some_column")).toBe("some column");
  });

  it("computes remaining approval time", () => {
    const now = Date.parse("2026-01-01T00:00:00Z");
    expect(timeLeft("2026-01-01T00:10:00Z", now)).toBe("10 phút");
    expect(timeLeft("2025-12-31T23:00:00Z", now)).toBeNull();
  });
});
