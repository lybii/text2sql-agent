import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { QueryRun } from "../../api/types";
import { QueryCard, type QueryActions } from "./QueryCard";

const base: QueryRun = {
  id: 1,
  conversation_id: 1,
  status: "awaiting_approval",
  question: "Doanh thu theo thành phố năm 2025",
  standalone_question: null,
  dataset_code: "sales",
  dataset_name: "Giao dịch bán hàng",
  sql: "SELECT city, SUM(sale_price) AS completed_revenue FROM analytics.v_transactions GROUP BY 1",
  sql_hash: "a".repeat(64),
  interpretation: "Tính doanh thu theo thành phố trong năm 2025.",
  assumptions: ["Hiển thị tối đa 500 dòng."],
  validation_errors: [],
  risk_level: "low",
  edited: false,
  auto_executed: false,
  expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
  columns: null,
  rows: null,
  row_count: null,
  truncated: false,
  chart: null,
  explanation: null,
  explanation_grounded: null,
  error_message: null,
  metrics: {
    prompt_version: "v1.1",
    llm_model: "demo-rules",
    llm_route: "demo",
    prompt_tokens: 0,
    completion_tokens: 0,
    cost_usd: 0,
    sql_attempts: 1,
    planning_ms: 12,
    execution_ms: null,
    explain_ms: null,
  },
  feedback: null,
  trace_url: null,
  created_at: new Date().toISOString(),
  approved_at: null,
  finished_at: null,
};

function actions(): QueryActions {
  return { approve: vi.fn(async () => {}), edit: vi.fn(async () => {}), cancel: vi.fn(async () => {}), feedback: vi.fn(async () => {}) };
}

function renderCard(run: QueryRun, a = actions(), reply = run.interpretation ?? "") {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <QueryCard run={run} reply={reply} actions={a} />
    </QueryClientProvider>,
  );
  return a;
}

describe("QueryCard", () => {
  it("shows SQL, risk and approval controls while awaiting approval", async () => {
    const a = renderCard(base);
    expect(screen.getByText("Chờ bạn duyệt")).toBeInTheDocument();
    expect(screen.getByText(/Rủi ro thấp/)).toBeInTheDocument();
    expect(screen.getByText(/SELECT city/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Duyệt & chạy/ }));
    await waitFor(() => expect(a.approve).toHaveBeenCalledWith(base));
  });

  it("lets the user edit SQL before approving", async () => {
    const a = renderCard(base);
    fireEvent.click(screen.getByRole("button", { name: /Sửa SQL/ }));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "SELECT 1" } });
    fireEvent.click(screen.getByRole("button", { name: /Lưu & kiểm tra SQL/ }));
    await waitFor(() => expect(a.edit).toHaveBeenCalledWith(base, "SELECT 1"));
  });

  it("renders results with explanation and table", () => {
    renderCard({
      ...base,
      status: "succeeded",
      columns: [
        { name: "city", type: "text" },
        { name: "completed_revenue", type: "number" },
      ],
      rows: [
        ["Hà Nội", 2_458_707_000_000],
        ["Đà Nẵng", 974_736_000_000],
      ],
      row_count: 2,
      explanation: { summary: "Hà Nội dẫn đầu.", highlights: ["Cao nhất: Hà Nội"] },
    });
    expect(screen.getByText("Hà Nội dẫn đầu.")).toBeInTheDocument();
    expect(screen.getByText("2.458,71 tỷ")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Duyệt & chạy/ })).not.toBeInTheDocument();
  });

  it("offers an access request when the dataset is restricted", () => {
    renderCard({ ...base, status: "access_required", sql: null }, actions(), "Bạn chưa được cấp quyền.");
    expect(screen.getByRole("button", { name: /Gửi yêu cầu truy cập/ })).toBeInTheDocument();
  });
});
