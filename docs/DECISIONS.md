# Quyết định kiến trúc (ADR rút gọn)

Mỗi mục: **bối cảnh → quyết định → đánh đổi**.

## ADR-01 — Modular monolith, chia theo tính năng

- **Bối cảnh:** Chia theo tầng kỹ thuật (`routes/`, `services/`, `repositories/`) làm một tính năng
  nằm rải ở nhiều nơi; các file service/repository dùng chung dễ phình thành nghìn dòng.
- **Quyết định:** `app/modules/<feature>/` (router + service). Lõi dùng chung (agent, sql, llm,
  guardrails, semantic) là package độc lập, không phụ thuộc HTTP.
- **Đánh đổi:** Vài truy vấn DB lặp giữa các module; chấp nhận để giữ ranh giới rõ.

## ADR-02 — LangGraph chỉ bao bước lập kế hoạch; không dùng checkpointer/interrupt

- **Bối cảnh:** Cách phổ biến là `interrupt_before` + `PostgresSaver` để dừng graph chờ người duyệt.
  Nhưng việc duyệt có thể diễn ra sau vài giờ, khác process; trạng thái khi đó tồn tại song song ở
  checkpoint và ở bảng nghiệp vụ (hai nguồn sự thật), và resume phụ thuộc phiên bản state.
- **Quyết định:** Graph kết thúc ở `awaiting_approval`. Mọi thứ cần để thực thi (SQL, hash, dataset,
  hạn duyệt) nằm trong `app.query_runs`. Approve/execute là hàm tuần tự, tất định.
- **Đánh đổi:** Không dùng `interrupt()`; đổi lại không có bảng checkpoint, không lỗi resume, và bước
  thực thi — phần nhạy cảm nhất — không có LLM nào tham gia.

## ADR-03 — Làm rõ câu hỏi bằng standalone-question rewriting

- **Quyết định:** `analyze_question` nhận N message gần nhất và trả về câu hỏi độc lập đã hợp nhất ngữ
  cảnh. Câu trả lời làm rõ chỉ là message tiếp theo — không cần lưu “slot đang thiếu”.
- **Đánh đổi:** Phụ thuộc chất lượng rewrite; được đo bằng slice `clarification` trong golden set.

## ADR-04 — Một đường sinh SQL cho mỗi provider, cùng một guard

- **Bối cảnh:** Nhiều đường sinh SQL song song (compiler, AI fallback, OLAP engine ngoài) nhân số
  trường hợp phải test và khó giải thích.
- **Quyết định:** `openai`: LLM sinh SQL với ngữ cảnh semantic (metric có sẵn biểu thức + filter chuẩn).
  `demo`: biên dịch tất định từ semantic layer — đồng thời là bậc fallback cuối. Cả hai qua cùng guard
  và cùng luồng duyệt.

## ADR-05 — Semantic layer bằng YAML trong git

- **Quyết định:** YAML + Pydantic; validate khi khởi động và trong CI (mọi `examples[].sql` phải qua guard).
  Review qua PR, version theo git.
- **Đánh đổi:** Đổi metadata cần deploy lại — phù hợp quy mô vài chục view.

## ADR-06 — Guard dùng SQLGlot `qualify` để xác thực cột

- **Quyết định:** Parse → đúng một câu `SELECT` → chặn node DDL/DML → allowlist bảng → `qualify` với
  schema của dataset (phân giải alias/CTE/subquery, báo lỗi cột lạ) → chặn hàm ngoài allowlist → ép `LIMIT`.
  `qualify` chỉ dùng để **kiểm tra**; SQL đem chạy là bản người dùng đã thấy.
- **Đánh đổi:** Phụ thuộc phiên bản SQLGlot (đã pin); khóa hành vi bằng bộ red-team.

## ADR-07 — JWT nội bộ

- **Quyết định:** Backend tự cấp JWT (HS256) + bcrypt; tài khoản demo khi seed. Module `auth` cô lập để
  có thể thay bằng OIDC.
- **Đánh đổi:** Không có refresh token / reset mật khẩu.

## ADR-08 — Một migration baseline

Dự án chưa có dữ liệu production; một baseline Alembic, các thay đổi sau thêm migration mới.

## ADR-09 — Biểu đồ vẽ ở client

Backend trả *chart spec* chọn bằng heuristic tất định; frontend vẽ bằng Recharts. Không render ảnh server.

## ADR-10 — Thực thi đồng bộ trong request `approve`

Truy vấn bị chặn bởi `statement_timeout` (10 s) và `LIMIT`, nên không cần job queue + polling. Nếu sau này
cho phép truy vấn dài, chuyển sang worker.

## ADR-11 — Plan cache khớp chính xác, không dùng semantic cache

- **Bối cảnh:** Semantic cache (embedding + ngưỡng similarity) hợp với chatbot hỏi đáp, nhưng với
  Text-to-SQL hai câu “doanh thu năm 2024” và “doanh thu năm 2025” gần như trùng embedding mà đáp án khác hẳn.
- **Quyết định:** Cache `SqlDraft` theo khóa = câu hỏi độc lập đã chuẩn hóa + dataset + `PROMPT_VERSION`
  + fingerprint semantic layer, có TTL. Kết quả truy vấn **không** cache (dữ liệu thay đổi; quyền thay đổi).
  SQL lấy từ cache vẫn qua guard và luồng duyệt.
- **Đánh đổi:** Hit rate thấp hơn semantic cache; đổi lại không bao giờ trả SQL sai kỳ. Cache in-process —
  chạy nhiều instance thì chuyển sang Redis.

## ADR-12 — Circuit breaker + fallback ladder

- **Quyết định:** Model chính bọc trong circuit breaker (CLOSED/OPEN/HALF_OPEN). Khi lỗi hoặc OPEN:
  model dự phòng (nếu cấu hình) → `DemoProvider` tất định. Ghi `llm_route` trên query run để đo fallback rate.
- **Đánh đổi:** Chất lượng của bậc demo thấp hơn (chỉ phủ dạng câu hỏi phổ biến) — nhưng nó vẫn đi qua
  guard + duyệt nên không thể kém an toàn hơn.

## ADR-13 — HITL theo rủi ro, có Edit và TTL

- **Quyết định:** `APPROVAL_MODE=always` (mặc định) hoặc `risk_based`. Rủi ro **cao** nếu dataset
  `confidential` hoặc truy vấn trả dữ liệu từng dòng (không tổng hợp); còn lại **thấp**. Ở `risk_based`,
  rủi ro thấp được tự chạy (audit `auto_executed`). Người dùng có thể sửa SQL (guard lại, hash mới,
  audit `edited`). Yêu cầu chờ duyệt hết hạn sau `APPROVAL_TTL_MINUTES`.
- **Lý do không dùng “confidence” do LLM tự chấm:** tự chấm điểm thường quá tự tin và chưa được hiệu
  chuẩn; rủi ro tính tất định từ dataset và hình dạng truy vấn thì kiểm chứng được.

## ADR-14 — Audit log append-only

- **Quyết định:** `app.audit_events` chỉ INSERT; trigger chặn UPDATE/DELETE (kể cả role backend).
  Ghi mọi quyết định: planned, edited, approved, auto_executed, cancelled, expired, executed, failed,
  access requested/approved/rejected/revoked.

## ADR-15 — Single-agent

- **Bối cảnh:** Multi-agent (router + SQL agent + analyst agent…) tăng số lần gọi LLM, độ trễ, và bề mặt tấn công.
- **Quyết định:** Một graph có cấu trúc cố định, 2–3 lần gọi LLM mỗi câu hỏi. Chuyên môn hóa nằm ở node,
  không ở agent tự trị.

## ADR-16 — Eval: tất định trước, LLM-judge sau

- **Quyết định:** Execution accuracy (so tập kết quả với SQL chuẩn) và red-team là kiểm tra tất định, chạy
  trong CI. LLM-judge chỉ dùng cho faithfulness của diễn giải, chấm **PASS/FAIL nhị phân**, chỉ đáng tin khi
  đã đo TPR/TNR trên tập nhãn người. So sánh phiên bản luôn **theo cặp** trên cùng golden set.
