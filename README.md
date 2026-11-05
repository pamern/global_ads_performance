# Project Structure

```text
global_ads_performance/
│
├── config/
│
├── data/
│   ├── raw/
│   └── sample/
│
├── analytics/
│
├── dbt-modeling/
│   ├── models/
│   └── tests/
│
├── src/ # Viết logic xử lý
│
├── scripts/ # Chạy task
│
├── dashboard/
│   └── screenshots/
│
├── docs/
```

# **QUY TRÌNH LÀM VIỆC GIT – POWER BI TEAM**

**1. Quy định nhánh**
- `main`: Nhánh chính của toàn bộ dự án. Không tự ý merge.
- `power-bi-dev`: Nhánh tích hợp chung của team Power BI.
- `feature/<ten-thanh-vien>-<chuc-nang>`: Nhánh cá nhân để phát triển tính năng.

**2. Quy trình làm việc**

**Bước 1 – Tạo nhánh cá nhân từ `power-bi-dev`**

```bash
git fetch origin
git switch power-bi-dev
git pull --ff-only origin power-bi-dev
git switch -c feature/ten-thanh-vien-chuc-nang
```

**Bước 2 – Code và commit trên nhánh cá nhân**

```bash
git status
git add <file-or-folder>
git commit -m "feat(powerbi): mô tả thay đổi"
git push -u origin feature/ten-thanh-vien-chuc-nang
```

**Bước 3 – Tạo Pull Request trên GitHub**

- Base: `power-bi-dev`
- Compare: `feature/ten-thanh-vien-chuc-nang`
- Thành viên khác review và thống nhất trước khi merge.

**3. Nguyên tắc bắt buộc**
- Không commit trực tiếp lên `main` hoặc `power-bi-dev`.
- Không tự ý merge PR khi chưa được review/chấp thuận.
- Mỗi người làm trên nhánh riêng, hạn chế chỉnh sửa đồng thời cùng file PBIP.
- Trước khi tạo PR, cập nhật thay đổi mới nhất từ `power-bi-dev` và xử lý conflict nếu có.
- Commit rõ nội dung, chỉ đưa những file liên quan vào commit.

**4. Khi hoàn thiện dashboard**

Sau khi tích hợp và kiểm thử toàn bộ dashboard trên `power-bi-dev`, nhóm trưởng sẽ xem xét tạo PR:

`power-bi-dev` → `main`

**Lưu ý: Mọi PR của team Power BI trong quá trình phát triển phải hướng vào `power-bi-dev`, tuyệt đối không hướng vào `main` khi chưa được phê duyệt.**