# BÁO CÁO BENCHMARK VÀ DANH MỤC LỖI HỆ THỐNG SOT-GRAPH (2026-09-13)

- **Môi trường:** macOS Darwin 25.3.0 (Apple M1 Max, 10 Cores, 32 GB RAM, APFS SSD)
- **Công cụ đo kiểm:** `sotgraph` v0.3.0 (`tree-sitter-ast` multi-worker & `codebase-memory-mcp` v0.4.0)
- **Tập mẫu khảo sát:** 94 thư mục tại `~/code/GitHub` (82 git repositories hoạt động)

---

## 1. TỔNG HỢP KẾT QUẢ BENCHMARK THỜI GIAN RECONCILE

Khảo sát được thực hiện đa tầng trên 6 repository đại diện từ nhỏ đến rất lớn (Massive) với 2 chế độ quét:
1. **Cold Run:** Lần chạy lập chỉ mục ban đầu (chưa có cache/database đầy đủ).
2. **Incremental Run (Warm):** Lần quét gia tăng khi mã nguồn **hoàn toàn không có thay đổi (zero-diff)**.

| Repository | Ngôn ngữ chính | Tổng số tệp | CBM Cold Run | CBM Incremental (Warm) | Builtin Cold Run | Builtin Incremental (Warm) | Tỷ lệ tăng tốc (Builtin vs CBM Warm) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`flutter_laocrm`** | Dart / Flutter | 56,192 tệp | 30.64s *(7 up)* | 18.23s *(7 up)* 🚨 | 37.37s *(1,889 up)* | **1.27s** *(0 up)* | **Builtin nhanh hơn 14.4×** |
| **`crm`** | TypeScript / PHP | 7,109 tệp | 24.03s *(5 up)* | 18.61s *(5 up)* 🚨 | 43.78s *(3,134 up)* | **5.62s** *(0 up)* | **Builtin nhanh hơn 3.3×** |
| **`deepseek-harness`**| TypeScript | 16,979 tệp | 2.55s *(0 up)* | 1.89s *(0 up)* | 1.84s *(0 up)* | **1.80s** *(0 up)* | Tương đương (warm cache) |
| **`sotgraph`** | Python | 590 tệp | 25.96s *(30 up)* | 16.01s *(30 up)* 🚨 | 7.27s *(560 up)* | **0.42s** *(0 up)* | **Builtin nhanh hơn 38.1×** |
| **`cliproxyapi`** | Go | 694 tệp | 15.89s *(2 up)* | 15.79s *(2 up)* 🚨 | 3.19s *(1,396 up)* | **0.43s** *(0 up)* | **Builtin nhanh hơn 36.7×** |
| **`uniservices-php`** | PHP | 983 tệp | 18.12s *(2 up)* | 16.45s *(2 up)* 🚨 | 4.81s *(983 up)* | **0.51s** *(0 up)* | **Builtin nhanh hơn 32.2×** |

### Benchmark `batch-reconcile` đồng thời 5 repos (4 workers song song):
- **Tập repos:** `9router`, `auth-net`, `cliproxyapi`, `dich-tai-lieu`, `sotgraph`
- **Tổng số tệp quét:** 4,563 tệp
- **Thời gian hoàn tất toàn bộ:** **35.09 giây** (Tốc độ xử lý: ~130 tệp/giây)
- **Đánh giá SQLite Concurrency:** 5/5 repos hoàn thành `[OK]`, cơ chế phân lập database theo thư mục `.sot/` hoạt động tốt, không phát sinh lỗi tranh chấp ghi `SQLITE_BUSY`.

---

## 2. BENCHMARK KHẢ NĂNG ĐÁP ỨNG CỦA 11 LỆNH HỖ TRỢ SAU RECONCILE

Đo lường thời gian phản hồi (Latency) sau khi cơ sở tri thức đã được đồng bộ hoàn tất:

| Lệnh CLI | `sotgraph` (Python) | `cliproxyapi` (Go) | `crm` (TS / PHP) | `flutter_laocrm` (Dart) | Đánh giá vận hành |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`doctor`** | **308ms** (OK) | **252ms** (OK) | **293ms** (OK) | **620ms** (OK) | ⚡ Kiểm tra schema, journal và page-stats cực nhanh. |
| **`verify`** | **2,478ms** (LỖI 🚨) | **2,069ms** (LỖI 🚨) | **&gt;30s** (TIMEOUT) | **12,901ms** (LỖI 🚨) | ❌ **Hỏng nghiêm trọng:** Luôn báo drift ảo do tệp nội bộ CBM. Trên repo lớn bị timeout do I/O đơn luồng. |
| **`search`** | **515ms** (OK) | **507ms** (OK) | **1,068ms** (OK) | **1,835ms** (OK) | ⚡ FTS5 + Trigram index đáp ứng sub-second rất tốt. |
| **`map`** | **2,137ms** (OK) | **1,676ms** (OK) | **5,879ms** (OK) | **3,994ms** (OK) | ⚡ Phân bổ token budget và PageRank ổn định. |
| **`explore`** | **1,484ms** (OK) | **1,210ms** (OK) | **1,265ms** (OK) | **1,439ms** (OK) | ⚡ Truy vết Inward/Outward call graph trong 1.5s. |
| **`usages`** | **754ms** (OK) | **680ms** (OK) | **1,216ms** (OK) | **1,396ms** (OK) | ⚡ Định vị chính xác các điểm gọi hàm (call-sites). |
| **`cluster`** | **13,797ms** (OK) | **&gt;30s** (TIMEOUT) | **&gt;30s** (TIMEOUT) | **13,863ms** (OK) | ⚠️ **Nghẽn CPU:** Louvain thuần Python bị treo/timeout trên đồ thị &gt;10,000 nodes. |
| **`report`** | **35,087ms** (OK) | **34,120ms** (OK) | **&gt;45s** (TIMEOUT) | **29,679ms** (OK) | ⚠️ Tính toán 2-hop blast radius cho God Nodes tốn nhiều thời gian. |
| **`viz`** | **23,823ms** (OK) | **22,100ms** (OK) | **&gt;30s** (TIMEOUT) | **20,898ms** (OK) | ⚠️ Tạo đồ thị HTML độc lập bị chậm khi đồ thị lớn. |
| **`bundle`** | **35,099ms** (OK) | **33,500ms** (OK) | **&gt;45s** (TIMEOUT) | **29,679ms** (OK) | ⚠️ Trích xuất 5 tập tệp fact bundle mất 30-40s. |
| **`diff-impact`** | **4,140ms** (CẢNH BÁO 🚨)| **5,120ms** (CẢNH BÁO 🚨)| **16,372ms** (CẢNH BÁO 🚨)| **31,493ms** (CẢNH BÁO 🚨)| ⚠️ Bị vấp `CbmContractError` trong auto-reconcile, mất thời gian fallback. |

---

## 3. DANH MỤC CHI TIẾT CÁC BUGS VÀ LỖ HỔNG HỆ THỐNG

### 🔴 BUG 1: Gap-Fill "False Update" Bug (Phá vỡ tính Idempotency)
- **Tệp liên quan:** `src/sot_graph/reconciler.py:564-566` và `src/sot_graph/cbm.py:515`
- **Mô tả:** Khi chạy lệnh `sotgraph reconcile` lần thứ 2, thứ 3 liên tiếp trên một repository sạch (không có thay đổi file), hệ thống vẫn thông báo cập nhật một số lượng file nhất định (ví dụ: `sotgraph` báo 30 updated, `flutter_laocrm` báo 7 updated, `crm` báo 5 updated, `cliproxyapi` báo 2 updated).
- **Nguyên nhân gốc rễ (Root Cause):**
  Trong `src/sot_graph/reconciler.py`:
  ```python
  # Dòng 564-566:
  for outcome in outcomes.values():
      if outcome not in ("error", "excluded"):
          published += 1  # ❌ LỖI: Khi outcome == "unchanged", biến published vẫn bị tăng lên 1!
  ```
  Hàm gap-fill gọi `reconciler.reconcile_paths(gap_paths)`. Dù file không hề thay đổi (`outcome == "unchanged"`), vòng lặp vẫn tính là `published`, dẫn đến `reconcile_dispatch` luôn cộng số lượng này vào `payload["updated"]`.
- **Hệ quả:** Mất tính bất biến (idempotency). Các hệ thống CI/CD hoặc Agent AI dựa vào `updated > 0` sẽ bị kích hoạt lặp vô hạn các bước sau reconcile.
- **Giải pháp khắc phục:**
  Đổi điều kiện thành:
  ```python
  for outcome in outcomes.values():
      if outcome in ("created", "updated", "rebuilt"):
          published += 1
  ```

---

### 🔴 BUG 2: Lệnh `sotgraph verify` luôn báo lỗi Drift ảo do tệp nội bộ của CBM
- **Tệp liên quan:** `src/sot_graph/cbm.py:488-506` và `src/sot_graph/reconciler.py:846-850`
- **Mô tả:** Chạy `sotgraph verify` trên bất kỳ repository nào được lập chỉ mục bởi `codebase-memory` đều kết thúc với Exit Code `1` (thất bại) kèm cảnh báo:
  ```text
  [WARN] DRIFT DETECTED: 3 files out of sync with disk:
    [missing] .codebase-memory/.semantic-input/git-context-v1
    [missing] .codebase-memory/.semantic-input/global-extension-config-v1
    [missing] .codebase-memory/.semantic-input/project-extension-config-v1
  Run 'sotgraph reconcile' to synchronize graph.
  ```
- **Nguyên nhân gốc rễ (Root Cause):**
  Bộ worker của `codebase-memory-mcp` tự động lưu vết các tệp cấu hình ngữ nghĩa nội bộ của nó vào bảng `file_hashes` trong `cbm/published.db`. Khi `sotgraph verify` truy vấn `db.all_journal_paths()`, nó đọc toàn bộ đường dẫn từ view hợp nhất này. Hàm `audit_drift()` kiểm tra `os.path.exists(path)` và kết luận 3 tệp nội bộ này bị "xóa khỏi đĩa".
- **Hệ quả:** Tính năng `sotgraph verify` mất hoàn toàn giá trị kiểm thử trong các kịch bản kiểm tra độ lệch (drift audit).
- **Giải pháp khắc phục:**
  Trong `src/sot_graph/reconciler.py` (hàm `audit_drift`):
  ```python
  # Bỏ qua các tệp ảo nội bộ của engine trích xuất
  if ".codebase-memory" in path or path.startswith(".sot/"):
      continue
  ```

---

### 🔴 BUG 3: Lỗi ngoại lệ `CbmContractError` trong `diff-impact` khi Auto-Reconcile
- **Tệp liên quan:** `src/sot_graph/cli.py:3363-3364` và `src/sot_graph/diff_impact.py`
- **Mô tả:** Khi chạy `sotgraph diff-impact` trên repo sử dụng CBM, terminal luôn bắn ra lỗi ngoại lệ:
  ```text
  ⚠️  auto_reconcile_failed:CbmContractError: CbmStore is read-only for graph shape: 
  the codebase-memory engine owns extraction (run sotgraph reconcile to reindex); 
  journal/ledger writes use a plain Database on .sot/sot.db
  ```
- **Nguyên nhân gốc rễ (Root Cause):**
  `diff-impact` cố gắng đồng bộ nhanh các file thay đổi trong git diff bằng cách gọi `Reconciler`. Tuy nhiên, nó truyền `qdb` (vốn là đối tượng `CbmStore` chỉ đọc đối với cấu trúc đồ thị) vào Reconciler. Khi Reconciler thực hiện ghi node vào đồ thị, `CbmStore` ném ngoại lệ bảo vệ hợp đồng `CbmContractError`.
- **Hệ quả:** Dù có khối `try/except` bắt lỗi nhưng lệnh bị trễ từ 5s - 15s để xử lý rollback/fallback.
- **Giải pháp khắc phục:**
  Trong `diff_impact.py`, khi thực hiện auto-reconcile, bắt buộc phải khởi tạo đối tượng `Database(db_path)` thuần của SQLite để ghi nhận thay đổi, không truyền `CbmStore` vào luồng ghi.

---

### 🔴 BUG 4: `batch-reconcile` báo cáo sai lệch gần như tuyệt đối số lượng Nodes/Edges
- **Tệp liên quan:** `src/sot_graph/cli.py:960-970`
- **Mô tả:** Trong bảng tổng kết `sotgraph batch-reconcile`:
  ```text
  Repository | Status | Scanned | Updated | Nodes | Edges | Time
  cliproxyapi| ✅ OK   | 1398    | 2       | 2     | 0     | 16.36s
  ```
  Số liệu báo cáo chỉ có **2 nodes, 0 edges**, trong khi thực tế đồ thị tri thức có tới **18,842 nodes** và **17,475 edges**!
- **Nguyên nhân gốc rễ (Root Cause):**
  Trong hàm `_reconcile_single_repo`:
  ```python
  db = Database(db_path)
  st = db.stats()
  ```
  Hàm này chỉ mở tệp SQLite `sot.db` thô (chỉ chứa các node gap-fill lẻ tẻ), hoàn toàn không mở qua `open_graph(abs_repo)` (để đọc `cbm/published.db` nơi lưu giữ 99.9% đồ thị khi CBM hoạt động).
- **Hệ quả:** Bảng báo cáo tổng hợp của `batch-reconcile` cung cấp thông tin sai lệch cho quản trị viên và kỹ sư.
- **Giải pháp khắc phục:**
  Sử dụng `qdb = open_graph(abs_repo)` và gọi `st = qdb.stats()` để lấy số liệu hợp nhất thực tế.

---

### 🔴 BUG 5: Lỗi phân tích cú pháp vị trí cờ tham số CLI (`argparse` Subcommand Ordering)
- **Tệp liên quan:** `src/sot_graph/cli.py`
- **Mô tả:**
  - Chạy `sotgraph --root /path/to/repo map` → Thành công.
  - Chạy `sotgraph map --root /path/to/repo` → Thất bại: `error: unrecognized arguments: --root`.
- **Nguyên nhân gốc rễ (Root Cause):**
  Các cờ `--root` và `--db` được định nghĩa ở parser gốc nhưng không được kế thừa qua `parents=[...]` ở các subparser con. Theo chuẩn POSIX thông thường, người dùng và các extension IDE thường đặt cờ sau tên lệnh con, dẫn đến việc bị từ chối tham số.
- **Giải pháp khắc phục:**
  Tạo `common_parser = argparse.ArgumentParser(add_help=False)` chứa `--root`, `--db`, `--json`, `--verbose`, và truyền `parents=[common_parser]` vào mọi `subparsers.add_parser(...)`.

---

### 🔴 BUG 6: Thắt nút cổ chai I/O và CPU đơn luồng trong `audit_drift` và `cluster`
- **Tệp liên quan:** `src/sot_graph/reconciler.py:846` và `src/sot_graph/analytics/louvain.py`
- **Mô tả:**
  - Lệnh `sotgraph verify` trên repo 7,000 files (`crm`) chạy vượt quá 30 giây (Timeout).
  - Lệnh `sotgraph cluster` trên repo &gt;10,000 nodes (`cliproxyapi`, `crm`) bị Timeout (&gt;30s).
- **Nguyên nhân gốc rễ (Root Cause):**
  1. `audit_drift()` duyệt tuần tự từng file bằng vòng lặp đơn luồng `for p in paths: os.stat(p)`.
  2. Thuật toán phân cụm Louvain viết bằng Python thuần, lặp ma trận cạnh với độ phức tạp $O(N \cdot K^2)$ trên bộ nhớ RAM, gây nghẽn nghiêm trọng khi số đỉnh lớn.
- **Giải pháp khắc phục:**
  1. Sử dụng `concurrent.futures.ThreadPoolExecutor(max_workers=8)` trong `audit_drift`.
  2. Thêm cờ giới hạn subgraph (capping / sampling) hoặc ngưỡng ngắt sớm khi modularity gain $\Delta Q &lt; 10^{-4}$ trong thuật toán Louvain.

---

## 4. ĐÁNH GIÁ SO SÁNH KIẾN TRÚC: CBM vs BUILTIN EXTRACTOR

### 1. Chi phí cơ sở (Fixed Overhead Floor)
- **`codebase-memory` (CBM):** Mất tối thiểu **15s – 18s** cho mỗi lần gọi, bất kể repo có 500 file hay 50,000 file, và bất kể có thay đổi hay không (zero-diff). Lý do: CBM phải khởi động runtime Node.js, khởi tạo socket IPC kết nối daemon nền, đồng bộ dữ liệu qua tiến trình con rồi export sang SQLite riêng.
- **`Builtin` (`tree-sitter-ast`):** Kiểm tra trực tiếp bảng `file_journal` trong SQLite qua kích thước file và mtime. Khi không có thay đổi (zero-diff), thời gian phản hồi chỉ là **0.42s** (nhanh hơn từ 14× đến 38× so với CBM).

### 2. Tiêu thụ tài nguyên bộ nhớ (Memory Footprint)
- Trên kho mã nguồn lớn (`flutter_laocrm`, 56,192 tệp), worker của CBM tiêu tốn đỉnh điểm tới **3.25 GB RAM**.
- Builtin Extractor duy trì mức tiêu thụ RAM ổn định dưới **350 MB** nhờ cơ chế streaming transaction batches (mặc định 64 files/batch).

---

## 5. LỘ TRÌNH HÀNH ĐỘNG CẢI TIẾN (ACTIONABLE ROADMAP)

### Giai đoạn 1 (P0 - Khắc phục ngay các lỗi sai lệch dữ liệu):
- [ ] **Sửa Bug 1:** Cập nhật `src/sot_graph/reconciler.py:564-566` chỉ tăng `published` khi `outcome in ("created", "updated", "rebuilt")`.
- [ ] **Sửa Bug 2:** Thêm điều kiện loại trừ `.codebase-memory/` trong `audit_drift` tại `src/sot_graph/reconciler.py:846`.
- [ ] **Sửa Bug 3:** Điều chỉnh `diff_impact.py` để dùng `Database(db_path)` thuần cho auto-reconcile thay vì `CbmStore`.
- [ ] **Sửa Bug 4:** Cập nhật `_reconcile_single_repo` trong `src/sot_graph/cli.py` sử dụng `open_graph(abs_repo)` để lấy đúng thống kê nodes/edges.

### Giai đoạn 2 (P1 - Tối ưu hóa hiệu năng và trải nghiệm CLI):
- [ ] **Đa luồng hóa `audit_drift`:** Dùng `ThreadPoolExecutor` để tăng tốc độ lệnh `sotgraph verify` lên gấp 8–10 lần.
- [ ] **Chuẩn hóa cú pháp CLI:** Thiết lập `common_parser` kế thừa `--root` và `--db` trên tất cả các lệnh con của `sotgraph`.
- [ ] **Short-circuit cho CBM:** Bổ sung bước kiểm tra nhanh `git status` và mtime cấp thư mục trước khi spawn daemon CBM ở chế độ incremental.

### Giai đoạn 3 (P2 - Nâng cấp thuật toán phân tích đồ thị lớn):
- [ ] **Tối ưu Louvain & Graph Traversal:** Thêm tham số `--max-nodes` và cơ chế ngắt sớm cho `sotgraph cluster` và `sotgraph report` trên các đồ thị quy mô lớn (&gt;10,000 nodes).
