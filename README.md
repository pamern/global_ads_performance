# NEXORA — Global Ad Spend

Dự án phân tích hiệu quả quảng cáo trên Google, Meta và TikTok. Dữ liệu được xử lý bằng Python, xây dựng Data Warehouse bằng dbt + PostgreSQL và trực quan hóa trên Power BI. DSS mô phỏng các phương án phân bổ ngân sách từ dữ liệu lịch sử.

## Cài đặt

Cần Python 3.14+, uv và PostgreSQL. Mở dashboard bằng Power BI Desktop.

```bash
uv sync
cp .env.example .env
```

Cấu hình kết nối trong `.env`. Local mặc định dùng PostgreSQL tại `127.0.0.1:55432`, database và user `nexora`; cần tạo và khởi động database trước khi chạy.

## Chạy local

Nếu database chưa có dữ liệu Raw, nạp CSV nguồn:

```bash
DATABASE_URL=postgresql://nexora@127.0.0.1:55432/nexora uv run python scripts/load_raw_to_postgres.py
```

Sau đó xây dựng warehouse và chạy DSS:

```bash
uv run python scripts/dbt_warehouse.py build --target local
uv run python scripts/run_dss.py --target local
```

Mở `powerbi/Global_Ads_Dashboard.pbip` trong Power BI Desktop và cấu hình nguồn PostgreSQL tương ứng.

## Tài liệu

- [Data Warehouse](dbt-modeling/README.md): mô hình dữ liệu và cách chạy dbt.
- [DSS](dss/README.md): mô phỏng phân bổ ngân sách.
- [Data Dictionary](docs/data_dictionary.md): mô tả dữ liệu.
