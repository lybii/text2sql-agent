# Runbook vận hành

## SLO

| SLI | SLO (28 ngày) |
|---|---|
| Tỷ lệ request lập kế hoạch không lỗi 5xx | ≥ 99 % |
| P95 thời gian lập kế hoạch | < 8 s |
| Red-team blocked rate (CI) | 100 % |

Error budget = 1 % request lỗi / 28 ngày. Khi đốt quá 50 % budget trong tuần: dừng thay đổi prompt/model, chỉ sửa lỗi.

## Alert

### PlanningLatencyP95High
1. Grafana → *LLM latency p95 by task*: chậm ở `analyze_question`, `generate_sql` hay ở DB?
2. Nếu do provider: kiểm tra status page; cân nhắc đặt `LLM_FALLBACK_MODEL` nhỏ hơn hoặc giảm `LLM_TIMEOUT_SECONDS`
   để circuit breaker chuyển nhanh sang fallback.
3. Nếu `repair rate` tăng (nhiều lần sinh SQL): xem trace, có thể prompt/semantic layer vừa đổi → rollback.

### HttpErrorRateHigh
1. `docker compose logs backend | grep '"level": "ERROR"'` — lọc theo `request_id`.
2. `/health` lỗi → kiểm tra PostgreSQL (`docker compose ps db`), số kết nối.
3. Lỗi sau deploy → rollback image trước.

### LLMCircuitOpen
- Hệ thống **vẫn phục vụ** qua fallback ladder (chất lượng thấp hơn). Kiểm tra provider, quota, API key.
- Circuit tự thử lại sau `BREAKER_RESET_SECONDS` (HALF_OPEN). Không cần restart.

### GuardRejectionSpike
- Hai khả năng: (a) prompt/model regression → so sánh `by_prompt_version` ở trang *Chất lượng AI*, chạy
  `make eval`; (b) ai đó đang dò hệ thống → xem `/admin/audit?action=query.planned`, `block_reason`, user.

### LLMCostBurn
- Trang *Chất lượng AI* → chi phí theo prompt version; kiểm tra plan cache hit rate, vòng lặp sửa SQL.
- Biện pháp tạm: hạ `RATE_LIMIT_PER_MINUTE`, đổi `LLM_MODEL` sang model rẻ hơn.

## Tác vụ thường gặp

| Việc | Cách làm |
|---|---|
| Xoay vòng `JWT_SECRET` | Đổi trong `.env`, restart backend. Mọi phiên đăng nhập bị hủy. |
| Xoay vòng mật khẩu role DB | Đổi `APP_BACKEND_PASSWORD`/`ANALYTICS_READER_PASSWORD`, chạy `ALTER ROLE … PASSWORD …` bằng owner, restart. |
| Thêm metric/dataset | Sửa YAML trong `backend/semantic/`, thêm case vào `golden.jsonl`, chạy `make check eval`, mở PR. Fingerprint semantic đổi → plan cache tự vô hiệu. |
| Đổi prompt | Sửa `app/llm/prompts.py`, **tăng `PROMPT_VERSION`**, chạy eval A/B + `eval.compare`. |
| Thu hồi quyền khẩn cấp | Admin → *Duyệt quyền* → *Thu hồi*. Truy vấn đang chờ duyệt sẽ thất bại khi chạy (kiểm tra quyền lần 2). |
| Điều tra một câu trả lời sai | Lấy `query_run.id` → `trace_url` (Langfuse) + `/admin/audit` → thêm case vào golden set với `source: fail_<ngày>`. |
