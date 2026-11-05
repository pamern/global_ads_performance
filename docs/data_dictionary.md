# Data Dictionary

Bộ dữ liệu `global_ads_performance_dataset.csv` ghi nhận hiệu quả quảng cáo theo ngày và các chiều phân loại chiến dịch. Mỗi dòng là một bản ghi gắn với ngày, nền tảng, loại chiến dịch, ngành và quốc gia.

| Cột | Ý nghĩa | Cách đọc / đơn vị |
|---|---|---|
| `date` | Ngày gắn với bản ghi hiệu quả quảng cáo | Định dạng `YYYY-MM-DD`. Dataset không ghi rõ đây là ngày chạy hay ngày xuất báo cáo. |
| `platform` | Nền tảng quảng cáo | Phân loại, ví dụ `Google Ads`, `Meta Ads`, `TikTok Ads`. |
| `campaign_type` | Loại/hình thức chiến dịch quảng cáo | Phân loại, ví dụ `Search`, `Video`, `Display`, `Shopping`. |
| `industry` | Ngành/lĩnh vực của chiến dịch | Phân loại, ví dụ `Fintech`, `EdTech`, `Healthcare`. |
| `country` | Quốc gia gắn với chiến dịch hoặc thị trường | Phân loại, ví dụ `USA`, `UK`, `Germany`. |
| `impressions` | Số lượt quảng cáo được hiển thị | Số lượt; không nhất thiết là số người dùng duy nhất. |
| `clicks` | Số lượt nhấp vào quảng cáo | Số lượt nhấp. |
| `CTR` | Tỷ lệ nhấp (Click-Through Rate) | `clicks / impressions`; thường biểu diễn dưới dạng tỷ lệ hoặc phần trăm. CSV lưu dạng tỷ lệ thập phân, ví dụ `0.0353` tương đương `3.53%`. |
| `CPC` | Chi phí trung bình cho mỗi lượt nhấp (Cost Per Click) | `ad_spend / clicks`; đơn vị tiền tệ không được nêu trong dataset. |
| `ad_spend` | Tổng chi phí quảng cáo | Đơn vị tiền tệ không được nêu trong dataset. |
| `conversions` | Số lượt chuyển đổi được ghi nhận | Số lượt; dataset không định nghĩa hành động nào được tính là chuyển đổi. |
| `CPA` | Chi phí trung bình cho mỗi chuyển đổi (Cost Per Acquisition/Action) | `ad_spend / conversions`; đơn vị tiền tệ không được nêu trong dataset. |
| `revenue` | Doanh thu được ghi nhận | Đơn vị tiền tệ và cách ghi nhận doanh thu không được nêu trong dataset. |
| `ROAS` | Doanh thu trên chi phí quảng cáo (Return On Ad Spend) | `revenue / ad_spend`; ví dụ `1.8` nghĩa là ghi nhận 1.8 đơn vị doanh thu trên mỗi 1 đơn vị chi phí quảng cáo. |

## Lưu ý

- Công thức CTR, CPC, CPA và ROAS ở trên khớp với giá trị của các dòng mẫu trong CSV; các giá trị trong file có thể đã được làm tròn.
- Không nên gán ký hiệu tiền tệ cho `CPC`, `ad_spend`, `CPA` hoặc `revenue` nếu chưa xác nhận currency từ nguồn dữ liệu.
- Khi tổng hợp nhiều dòng, nên tính lại các tỷ lệ từ tổng số liệu gốc thay vì lấy trung bình đơn giản của CTR, CPC, CPA hoặc ROAS từng dòng.