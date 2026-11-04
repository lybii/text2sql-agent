# Đánh giá (Evaluation)

## Quy trình

```text
Đọc trace (Langfuse / app.query_runs) → đặt tên lỗi, đếm theo loại → chọn cái cần đo
→ thêm case vào golden set (có slice, source, version) → chạy gate → so sánh theo cặp → deploy
→ traffic thật sinh trace mới → lặp lại
```

Mỗi vòng, golden set **dài thêm** (case lấy từ lỗi thật có `source: fail_<ngày>`), và gate vòng sau chặt hơn.

## Bộ dữ liệu

| File | Nội dung | Trường chính |
|---|---|---|
| `backend/eval/datasets/golden.jsonl` | 33 case: 25 có SQL chuẩn + clarification, multi-turn, access, out-of-scope | `id, version, slice, question, history?, accessible?, expected_outcome, gold_sql?, source` |
| `backend/eval/datasets/redteam.jsonl` | 22 SQL tấn công (DDL/DML, stacked, schema escape, PII, catalog, DoS, file read, exfil, lock) + 12 câu hỏi tấn công (injection, roleplay, prompt leak, PII, privilege) | `id, kind, category, sql?/question?` |

Slice hiện có: `simple_agg, filter, group_by, ranking, time_series, time_relative, inventory, customers,
clarification, multi_turn, access, out_of_scope`.

## Chỉ số

| Chỉ số | Định nghĩa |
|---|---|
| **Outcome accuracy** | Kết quả lập kế hoạch đúng loại mong đợi (chạy SQL / hỏi lại / thiếu quyền / trả lời trực tiếp). |
| **Execution accuracy** | Chạy cả SQL sinh ra và SQL chuẩn, so **multiset các dòng** (bỏ qua thứ tự dòng, thứ tự cột, chênh lệch làm tròn ≤ 0,01). Không so chuỗi SQL — hai câu SQL khác nhau có thể cùng đúng. |
| Khoảng tin cậy | Wilson 95 % cho mỗi tỷ lệ và mỗi slice. Slice nhỏ → khoảng rộng → chỉ dùng để **chẩn đoán**, không dùng làm gate. |
| Repair rate | Tỷ lệ case cần sửa SQL sau lần guard từ chối đầu. |
| Latency | P50 / P95 / P99 thời gian lập kế hoạch. |
| Token / chi phí | Trung bình mỗi case, theo bảng giá trong `LLM_PRICES`. |
| Degraded route rate | Tỷ lệ case có ít nhất một lần gọi rơi xuống fallback. |
| **Red-team blocked rate** | Phải đạt **100 %** — một case lọt là CI đỏ. |

## Kết quả hiện tại

| Cấu hình | Outcome acc. | Execution acc. | Red-team | P95 lập kế hoạch |
|---|---|---|---|---|
| `demo` (semantic compiler tất định) | 100 % (33/33) | 100 % (27/27) | 100 % (34/34) | ~50 ms |
| `demo` + chaos (primary lỗi 100 %) | 100 % | 100 % | — | degraded route 100 % |
| `openai` | chạy `make eval-openai` để điền | | | |

> Điểm 100 % của provider `demo` **không** chứng minh chất lượng mô hình: compiler được viết cho đúng các dạng
> câu hỏi này. Nó là **regression gate** cho toàn bộ pipeline (graph, guard, executor, dữ liệu seed). Hai lỗi thật
> đã được bộ eval bắt ở vòng đầu: thiếu alias “giao dịch hoàn tất”, và “khách hàng **mới** năm” bị hiểu nhầm
> thành “**mỗi** năm” sau khi bỏ dấu tiếng Việt.

## So sánh hai phiên bản

```bash
python -m eval.run --suite golden --out eval/reports/A.json      # trước khi đổi prompt/model
python -m eval.run --suite golden --out eval/reports/B.json      # sau khi đổi
python -m eval.compare eval/reports/A.json eval/reports/B.json
```

`compare` ghép cặp theo `id` trên cùng golden set, liệt kê **fixes** và **regressions**, chênh lệch theo slice,
và p-value McNemar chính xác trên các cặp bất đồng. Đổi phiên bản khi: không regression ở slice quan trọng,
và p < 0,05 (hoặc chênh lệch đủ lớn so với khoảng tin cậy).

## LLM-as-judge (faithfulness của diễn giải)

- Nhãn **PASS/FAIL nhị phân**, không dùng thang 1–5.
- Chỉ đáng tin sau khi **hiệu chuẩn**: gán nhãn tay một mẫu (`judge_labels.jsonl`), chạy
  `python -m eval.judge calibrate …` → **TPR** (bắt được lỗi thật) và **TNR** (không báo nhầm). Đọc riêng hai số;
  độ đồng thuận tổng có thể đánh lừa khi tỷ lệ lỗi thấp.
- Dùng judge để **so sánh hai phiên bản**, không báo cáo như con số tuyệt đối.
- Trong runtime, faithfulness đã có lớp bảo vệ tất định: `guardrails/grounding.py` từ chối mọi con số không truy
  được về kết quả.
