# Kiểm thử Data Warehouse

Tham chiếu: `notebooks/01_data_quality.ipynb` đã cập nhật, CSV 1.800 dòng/14 cột. Đã đọc toàn bộ cells và outputs; kiểm chứng CSV/Raw thực tế trước khi dùng ràng buộc.

## Quy tắc và điều kiện PASS/FAIL

`store_failures` mặc định tắt; test CTR chỉ trả cảnh báo, không lưu bảng lỗi. Các bảng audit từ lần chạy cũ được giữ trong `dbt_test__audit`, không bị tự xóa.

Mọi singular SQL trong `tests/` trả về dòng vi phạm; 0 dòng là PASS. Generic tests nằm trong `models/**/schema.yml` trả về khóa/dòng vi phạm theo SQL do dbt biên dịch. Ngoại trừ `kpi_ctr`, mọi test có severity ERROR; không có ngoại lệ được chấp thuận để bỏ qua lỗi nghiêm trọng.

| Test/config | Mục đích và điều kiện vi phạm |
|---|---|
| `unique`, `not_null` | PK, thuộc tính Dimension và trường Staging bắt buộc trùng/NULL |
| `relationships` | FK Fact không có khóa tương ứng trong Dimension; NOT NULL kiểm tra riêng FK thiếu |
| `source_snapshot_count` | Raw khác 1.800 dòng (hoặc `expected_source_rows` đã xác nhận) |
| `raw_exact_duplicates` | Payload Raw giống hoàn toàn xuất hiện >1 lần; trả payload và số lần |
| `raw_formats` | Ngày không ISO hoặc không hợp lệ; số nguyên/tiền/KPI sai định dạng/precision; chiều rỗng. Cast không hợp lệ cũng làm build ERROR, không coerce thành 0/NULL |
| `validity` | Measure âm, clicks > impressions, CTR ngoài [0,1], KPI nguồn âm; các bất nhất mẫu số 0 trong notebook; tiền NaN/Infinity |
| `layer_counts` | Bất kỳ lớp nào có số dòng khác Raw |
| `grain_and_measures` | Dòng Staging/Fact không có đối ứng ID, hoặc một measure thay đổi |
| `reconciliation` | Count hoặc SUM của 5 measures Raw/Fact khác nhau với NUMERIC |
| `dimensional_reconciliation` | Thiếu nhóm chiều, SUM hoặc bất kỳ 5 KPI ratio-of-sums khác Raw, kiểm tra riêng từng chiều Date/Platform/Campaign Type/Industry/Country |
| `kpi_ctr` | WARN khi abs(source_ctr − ctr) > 0,00005; trả ID, nguồn, tính lại, sai lệch |
| `kpi_cpc`, `kpi_cpa`, `kpi_roas` | ERROR khi sai lệch > 0,005; không nâng tolerance để che lỗi |
| `kpi_division` | Mẫu số 0 nhưng KPI không NULL, hoặc phép tính khác công thức NUMERIC |
| `kpi_zero_denominators` (unit test) | Fixture độc lập gồm toàn mẫu số 0, phân số bình thường và một số mẫu số 0; kết quả phải khớp kỳ vọng, không NaN/Infinity |

Ngưỡng lấy từ precision CSV và notebook: CTR tối đa 4 số thập phân → nửa đơn vị 10^-4; CPC/CPA/ROAS tối đa 2 → nửa đơn vị 10^-2. So sánh bằng NUMERIC, không cộng epsilon cho FLOAT. CTR nguồn dùng thang tỷ lệ, không phải phần trăm. Không có Conversion Rate nguồn để đối chiếu.

12 tổ hợp chiều trùng và outlier thống kê được giữ theo notebook, không xem là duplicate hoặc lỗi nghiệp vụ. Không áp dụng conversions <= clicks. 47 CTR lệch là vấn đề còn mở, không phải accepted exception; Mart chỉ chứa additive measures nên tính CTR từ tổng clicks/impressions.

## Rebuild và bảo toàn Raw

`scripts/verify_warehouse.py --target local|dev` yêu cầu một build ban đầu. Script chụp toàn bộ dòng Raw, toàn bộ Fact/Dimensions có IDs; build lại; so sánh snapshots và totals chính xác, dừng lỗi nếu khác. Kết quả JSON nằm cạnh tài liệu này. Không dùng digest hoặc sample để thay cho đối chiếu đầy đủ.

Lệnh `dbt test` chạy lại data tests; unit test chạy trong `dbt build`. Các artifacts đầy đủ trong `target/run_results.json`, `target/manifest.json` và `logs/dbt.log` không đưa vào git. Dùng `dbt test --select <tên_test> --store-failures` nếu cần lưu dòng lỗi của test ERROR.

## Môi trường kiểm thử

Local PostgreSQL 18.6, dbt-core 1.12.6, dbt-postgres 1.11.0. Raw local được nạp bằng `scripts/load_raw_to_postgres.py` hiện có; không tạo CSV importer mới. Dev dùng DATABASE_URL hiện có và TLS; xem kết quả thực tế trong báo cáo JSON/tóm tắt bên dưới.

## Kết quả thực tế — 20/10/2026 (Asia/Ho_Chi_Minh)

| Environment | dbt debug | Build + rebuild | Tests mỗi build cuối | Raw / Mart / IDs |
|---|---|---|---|---|
| local | PASS | PASS | 68 PASS (67 data + 1 unit), 1 WARN, 0 FAIL/ERROR/SKIP | Raw không đổi; toàn bộ Mart/IDs giống nhau |
| dev (Supabase) | PASS | PASS | 68 PASS (67 data + 1 unit), 1 WARN, 0 FAIL/ERROR/SKIP | Raw không đổi từ trước triển khai; toàn bộ Mart/IDs giống nhau |

Dev được kiểm tra chỉ đọc trước khi build: đúng endpoint/project từ DATABASE_URL hiện có, database `postgres`, Raw đủ 1.800 dòng TEXT và khớp nguyên CSV, quyền CREATE có sẵn, chưa tồn tại schema `nexora_dev*`. Build chỉ tạo/thay thế các đối tượng thuộc namespace mới của warehouse, không sửa Raw. Không dùng full-refresh.

| Measure | Raw (cả hai môi trường) | Fact (cả hai môi trường) | Chênh lệch |
|---|---:|---:|---:|
| Row count | 1800 | 1800 | 0 |
| Impressions | 185254234 | 185254234 | 0 |
| Clicks | 7132816 | 7132816 | 0 |
| Conversions | 326812 | 326812 | 0 |
| Ad spend | 11108749.09 | 11108749.09 | 0 |
| Revenue | 54183330.81 | 54183330.81 | 0 |

Dimensions: Date 365, Platform 3, Campaign Type 4, Industry 5, Country 7. Không có orphan. WARN duy nhất trả về đúng 47 CTR mismatch theo notebook; nguyên nhân chưa được xác nhận, không sửa nguồn hoặc tăng tolerance. Không còn test ERROR. Bằng chứng máy đọc: [local](verification_local.json), [dev](verification_dev.json).

README root, notebook, loader và cấu hình Supabase không bị chỉnh sửa trong quá trình triển khai.

## Cập nhật tên schema

Cả local/dev dùng `staging`, `intermediate`, `mart`, `mapping`; Raw vẫn là `raw`. Giữ schema `mapping` riêng cho `source_rows` và seeds `map_*`. Báo cáo JSON được cập nhật sau khi kiểm thử lại cấu hình mới.

## PascalCase ở Mart

Tên bảng/cột vật lý Mart chuyển sang PascalCase; tên model và `ref()` giữ nguyên. Tests và `verify_warehouse.py` dùng quoted identifiers tương ứng. Các báo cáo JSON thể hiện kết quả với tên bảng mới.
