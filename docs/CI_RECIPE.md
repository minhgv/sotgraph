# CI recipe — theo dõi chất lượng commit sau khi merge

Ba chốt của quy trình: scope receipt (trước code) → diff receipt + safe_commit
(trước commit) → outcome verdict (sau commit). Tài liệu này là đoạn chốt 3:
giám sát commit theo rủi ro và kiểm chứng commit rủi ro đã xử lý xong chưa.

## 1. Quét định kỳ theo tag/release

```bash
# Tất cả commit kể từ tag release gần nhất, kèm verdict outcome
sotgraph log --since v0.3.5 --outcomes --json > outcomes.json

# Hoặc theo mốc thời gian
sotgraph log --since "2.weeks" --outcomes
```

Cột `verdict`: `clear-fault` (đóng sạch), `still-hot` (bị revert hoặc cần
commit vá), `unknown` (chưa đủ cửa sổ quan sát 14 ngày — fail-closed, không
đoán). Footer `Verdict calibration` in tỉ lệ still-hot đo được theo từng
mức rủi ro ngay trên slice đang xem.

## 2. Fail CI khi commit rủi ro còn nóng

```bash
# Lấy danh sách sha có verdict still-hot (verdicts nằm ở map riêng)
sotgraph log --since v0.3.5 --outcomes --json \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
risk = {c['commit_hash']: c['risk_level'] for c in d['commits']}
hot = [sha for sha, v in d['verdicts'].items()
       if v['verdict'] == 'still-hot' and risk.get(sha) == 'HIGH']
print('\n'.join(hot))
sys.exit(1 if hot else 0)
"
```

`--outcomes` không chặn — nó là lớp giám sát. Muốn chặn thật thì chốt 2
đã có `--gate-strict` (exit 2 khi `safe_commit` block) chạy trước commit.

## 3. Dossier cho một commit cụ thể

```bash
# Chuỗi đầy đủ: scope receipt → diff receipt → commit → verdict
sotgraph receipt chain <sha-or-receipt-digest>
sotgraph receipt chain <sha> --json
```

`chain` báo từng mắt xích (scope→diff, diff→commit, commit→outcome) và liệt
kê mắt nào còn thiếu — `complete` chỉ true khi cả ba link resolve được.
Commit anchor tìm ngược các diff receipt đã sinh ra nó (con trực tiếp của
`head_sha` lúc mint = độ tin cậy cao; trùng tập file = trung bình — luôn
ghi `matched_via`).

## 4. Quy trình đầy đủ cho một task

```bash
sotgraph scope-receipt <symbol>            # chốt 1: phạm vi trước code
# ... viết code ...
sotgraph diff-impact --working-tree \
  --pre-receipt <scope-digest> \
  --test-report results.json \
  --gate-strict                            # chốt 2: an toàn trước commit
git commit -am "..."
sotgraph receipt chain <new-sha>           # chốt 3: dossier + verdict
```
