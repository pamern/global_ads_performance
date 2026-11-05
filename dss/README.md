# NEXORA DSS

## Mục đích

Hỗ trợ đánh giá phân bổ ngân sách Google, Meta, TikTok từ dữ liệu lịch sử. Kết quả phục vụ Power BI và người ra quyết định; không phải lệnh tự động điều chỉnh ngân sách.

## Cơ chế hoạt động

`mart.DssMonthly → Python simulation/Maximin → schema dss → Power BI`.

Baseline = tỷ trọng pooled spend Q4/2024, ngân sách B = tổng spend trung bình tháng Q4. Sinh grid 1 điểm phần trăm (5.151 điểm), giữ điểm trong Convex Hull lịch sử, yêu cầu impressions và conversions không giảm ở mọi training state. Chọn worst revenue uplift cao nhất, phân định bằng median; không có điểm hợp lệ thì giữ baseline. OOT gồm 6 folds Jan–Jun → Jul đến Jan–Nov → Dec; baseline/hull/selection và hướng ROAS benchmark chỉ dùng training. So sánh DSS với previous-month, simple5 và matched-risk theo POC. Break-even dùng pooled Q4; concavity stress beta 1/0,9/0,8/0,7. Decision status chỉ mô tả bằng chứng, giữ ngưỡng so sánh 0,001 từ POC.

## Input

Chỉ đọc `mart."DssMonthly"`, 36 trạng thái Platform × Month năm 2024. Các cột: Platform, Month, AdSpend, Revenue, Impressions, Conversions và ba rates PerDollar. Kiểm tra đủ panel, không trùng/NULL, spend dương, measures/rates hữu hạn và khớp ratio-of-sums. Không sửa Mart hay tự chạy dbt.

## Output

Mặc định schema `dss`; các bảng liên kết bằng `run_id`:

| Bảng | Grain / nội dung |
|---|---|
| `runs` | Một kết quả theo fingerprint input/code/parameters/versions/target; summary có kiểu số, decision status, metadata, snapshot input gốc |
| `history` | Run × Platform × Month; historical measures/rates, monthly shares, đỉnh hull full-sample |
| `allocations` | Run × evaluation × strategy × platform; tỷ trọng và ngân sách |
| `scenarios` | Run × evaluation × strategy × state_month; simulated outcomes và uplifts |
| `validation` | Run × test_month × strategy; OOT, benchmark, training cutoff, feasibility và movement |
| `sensitivity` | Run × beta; concavity outcomes/uplift |
| `executions` | Một lần thực thi thành công; timestamp và cờ reuse |

`evaluation='full'` là in-sample; evaluation dạng ngày là tháng OOT. Shares/uplifts là fractions; `break_even_deterioration_pct` là %. `found=false` ở DSS nghĩa là fallback; matched benchmark không tìm được có metrics NULL. Simple5 được giữ nguyên dù ngoài support/boundary theo POC và được gắn cờ. Re-run cùng fingerprint giữ nguyên kết quả, thêm execution log có chủ đích. Toàn bộ ghi nằm trong một transaction; lỗi rollback cả DDL/dữ liệu. Không nhận schema có sẵn nếu thiếu marker NEXORA DSS; schema khác cấu trúc cần migration thủ công. Power BI chọn một `run_id` từ `runs` để tránh cộng gộp các phiên bản mô phỏng.

## Cách chạy

```bash
uv sync
# Chỉ khi upstream và BI Mart đã có; database mới xem dbt-modeling/README.md.
uv run python scripts/dbt_warehouse.py build --target local --select dss_monthly
uv run python scripts/run_dss.py --target local
# Dev: kiểm tra đúng endpoint/database và quyền CREATE trước khi ghi.
uv run python scripts/dbt_warehouse.py build --target dev --select dss_monthly
uv run python scripts/run_dss.py --target dev

uv run python -m unittest discover -s tests -v
# Integration local: schema test được rollback, không giữ dữ liệu test.
NEXORA_DSS_DB_TEST=1 uv run python -m unittest discover -s tests -v
```

Mặc định target local. Local dùng `LOCAL_PG*` và defaults từ `dbt-modeling/profiles.yml`, chỉ cho loopback; dev dùng `DATABASE_URL` qua utility hiện có và TLS, từ chối loopback. `.env` được load, biến đã export ưu tiên hơn; không fallback target. Input schema kế thừa `database.schemas.mart`; input table và output schemas khai báo trong `config/project.yaml`. Hai target có cùng tên schema nhưng ở hai PostgreSQL riêng. Với [Supabase shared pooler](https://supabase.com/docs/guides/database/connecting-to-postgres), username chứa project suffix; kiểm tra server identity đối chiếu PostgreSQL role tương ứng. Cần quyền đọc input và tạo/ghi output schema; không ghi warehouse.

## Giới hạn

Chỉ 12 tháng quan sát và ba nền tảng. Hiệu suất tuyến tính không mô tả tác động scale, seasonality hoặc quan hệ nhân quả. OOT vẫn là mô phỏng; uplift không phải doanh thu chắc chắn. Beta stress minh họa, không fit đường cong hoặc ước lượng break-even beta. Hull suy biến làm dừng rõ ràng vì POC chưa định nghĩa cách thay thế. Monthly Mart không đủ tái tạo slice consistency và row-level diminishing-return diagnostics của POC; engine không đọc thêm Raw để suy diễn các kết quả đó. Chưa có backtest nhiều năm hay tiêu chí production approval; decision status không loại bỏ ảnh hưởng chênh lệch budget movement giữa DSS và benchmark.
