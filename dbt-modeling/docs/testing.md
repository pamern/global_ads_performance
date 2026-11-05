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

## DSS Input Mart — bổ sung 21/10/2026

Phạm vi bước 3: `dss_monthly` → `mart."DssMonthly"`, một dòng cho mỗi Google/Meta/TikTok × tháng năm 2024. Không thay đổi kết quả kiểm thử warehouse đã ghi nhận ngày 20/10 ở trên; các kết quả đó chưa bao gồm DSS.

| Test | Điều kiện vi phạm |
|---|---|
| Generic NOT NULL / accepted_values | Thiếu trường bắt buộc hoặc platform khác Google/Meta/TikTok |
| `dss_monthly_grain` | Trùng Platform × Month, thiếu bất kỳ trạng thái nào trong 3 × 12, hoặc có trạng thái ngoài tập kỳ vọng |
| `dss_monthly_validity` | Nguồn năm 2024 có platform không hợp lệ, measure NULL/âm hoặc tiền NaN/Infinity; tổng spend <= 0, measures/rates không hợp lệ, hoặc rate khác ratio-of-sums |
| `dss_monthly_reconciliation` | Thiếu/thừa nhóm hoặc SUM của AdSpend/Revenue/Impressions/Conversions khác BI Fact kết hợp DimDate/DimPlatform, đối chiếu NUMERIC chính xác |
| `dss_monthly_ratio_of_sums` (unit) | Hai dòng có spend khác nhau không cho tỷ lệ pooled đúng, chia 0 không ra NULL, hoặc lọc năm/platform và nhóm tháng sai |

Rates NULL khi tổng spend bằng 0 là hành vi SQL chủ đích; NOT NULL và validity vẫn báo ERROR để chặn input chưa sẵn sàng cho DSS. Không dùng ngưỡng tùy ý hoặc ép dữ liệu lỗi thành 0. Các tests DSS đều có severity ERROR theo mặc định.

Chạy sau khi được phép thực thi model, từ repository root (upstream và BI Mart phải tồn tại):

```bash
uv run python scripts/dbt_warehouse.py build --target local --select dss_monthly
uv run python scripts/dbt_warehouse.py test --target local --select dss_monthly
```

Tại thời điểm triển khai bước 3 ban đầu, theo yêu cầu **chưa chạy model dbt, unit tests hoặc data tests**. Chỉ kiểm tra parse cấu hình offline; parse không chứng minh SQL chạy đúng trên PostgreSQL hoặc dữ liệu thực tế đủ 36 trạng thái. Chưa có kết quả đối soát database cho DSS.

## Python DSS Engine — 21/10/2026

Engine giữ nguyên `DssMonthly`; `dss/engine.py` xử lý tính toán, `dss/storage.py` phụ trách cấu hình/transaction, `scripts/run_dss.py` điều phối local/dev. Dependencies numpy/scipy là runtime; input/output schema được cấu hình tường minh. Xem [DSS README](../../dss/README.md).

Đã chạy `NEXORA_DSS_DB_TEST=1 uv run python -m unittest discover -s tests -v`: **18 PASS, không skip** trên local. Tests gồm target/TLS/loopback guards, thiếu/trùng/invalid input, grid/simplex/hull, baseline pooled, simulation, funnel, Maximin/tie-break/fallback, hull suy biến, sửa future data không thay allocation fold đầu, sensitivity, summary/detail integrity, fingerprint, repeated writes và rollback giữa lúc ghi. Test POC thực thi lại code notebook từ dữ liệu CSV, đối chiếu baseline/candidate, candidate counts, sáu folds OOT, cả bốn benchmarks và sensitivity; không dùng saved outputs làm đáp án.

Đã chạy CLI local hai lần trên bản code cuối: cùng run_id, lần hai reuse; mỗi run có 36 historical rows, 96 allocation rows, 54 scenario rows, 24 validation rows, 4 sensitivity rows. Không có nhóm trùng theo grain; execution log thêm 2 dòng có chủ đích. Chụp và so sánh toàn bộ dòng của các bảng/view thuộc raw/staging/intermediate/mart/mapping trước/sau: không thay đổi. Schema test trong integration đã rollback, không giữ lại.

Kết quả local: 5.151 grid points, 104 trong hull, 32 qua funnel; selected shares Google 49%, Meta 21%, TikTok 30%. Full-sample worst/median/best simulated revenue uplift ~3,069% / 4,233% / 5,457%; OOT mean ~6,787%; break-even deterioration ~6,122%. Đây là simulation/sensitivity, không phải causal uplift hoặc dự báo chắc chắn. DSS chuyển budget nhiều hơn matched benchmark; không suy diễn mean uplift difference thành lợi ích độc lập của selector.

Bằng chứng máy đọc: [dss/verification_local.json](../../dss/verification_local.json). Các kết quả DSS này không thay thế báo cáo dbt ngày 20/10; đợt triển khai Engine không chạy lại dbt. Slice consistency/row-level diagnostics trong POC không tái tạo được từ Monthly Mart và chưa triển khai.

Dev preflight chỉ đọc: kết nối thành công qua Supabase pooler, nhưng chưa có `mart."DssMonthly"`; dừng trước khi ghi, chưa chạy Engine/output dev. Script đã hỗ trợ username định tuyến của shared pooler và kiểm tra IPv4/IPv6 CIDR của server; có tests riêng. Cần build DSS Monthly trên dev theo quy trình README trước khi chạy `run_dss.py --target dev`.
