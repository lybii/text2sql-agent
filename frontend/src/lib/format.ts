const MONEY_HINTS = /(revenue|price|commission|spent|spend|value|cost|amount|target)/i;
const PERCENT_HINTS = /(rate|achievement|percent|share)/i;

const nf = (digits: number) => new Intl.NumberFormat("vi-VN", { maximumFractionDigits: digits });

/** Compact Vietnamese money: 2458707000000 → "2.458,71 tỷ". */
export function formatMoney(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${nf(2).format(value / 1e9)} tỷ`;
  if (abs >= 1e6) return `${nf(1).format(value / 1e6)} triệu`;
  return nf(0).format(value);
}

export function formatCell(column: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (typeof value === "number") {
    if (/^(year|month|quarter)$/i.test(column)) return String(value);
    if (PERCENT_HINTS.test(column)) return `${nf(2).format(value)}%`;
    if (MONEY_HINTS.test(column)) return formatMoney(value);
    return nf(2).format(value);
  }
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-");
    return d === "01" && column.toLowerCase().includes("month") ? `${m}/${y}` : `${d}/${m}/${y}`;
  }
  return String(value);
}

export function humanizeColumn(name: string): string {
  const map: Record<string, string> = {
    city: "Thành phố",
    district: "Quận/huyện",
    property_type: "Loại BĐS",
    project_name: "Dự án",
    agent_name: "Nhân viên",
    customer_source: "Nguồn khách",
    status: "Trạng thái",
    month: "Tháng",
    quarter: "Quý",
    year: "Năm",
    completed_revenue: "Doanh thu",
    total_commission: "Hoa hồng",
    completed_deals: "Số giao dịch hoàn tất",
    avg_deal_value: "Giá trị GD trung bình",
    cancellation_rate: "Tỷ lệ hủy",
    available_units: "Tồn kho",
    listed_units: "Số SP mở bán",
    avg_list_price: "Giá niêm yết TB",
    avg_price_per_m2: "Giá TB/m²",
    avg_area: "Diện tích TB",
    new_customers: "Khách hàng mới",
    customer_count: "Số khách hàng",
    buyer_conversion_rate: "Tỷ lệ khách đã mua",
    avg_customer_spend: "Chi tiêu TB",
    agent_revenue: "Doanh thu",
    target_achievement: "Hoàn thành chỉ tiêu",
  };
  return map[name] ?? name.replace(/_/g, " ");
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
}

export function timeLeft(iso: string, now = Date.now()): string | null {
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return null;
  const minutes = Math.ceil(ms / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút` : `${minutes} phút`;
}
