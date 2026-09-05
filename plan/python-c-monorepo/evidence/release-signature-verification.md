# Release signature verification — CBM v0.10.8 (2026-09-06)

Đóng hard-gate từ `provenance-upstream.md` §8: sigstore bundle từ trước chỉ được ghi nhận **presence**; bản này **verify thật** bằng công cụ độc lập, pin identity/issuer từ workflow upstream đọc **tại đúng release commit**, và kiểm kê Rekor inclusion + digest artifact. Receipt máy-đọc: `sig-verify-v0.10.8-receipt.json` + transcript lệnh/thoát đầy đủ `sig-verify-v0.10.8-transcript.json` (cùng thư mục).

## 0. Verdict

**VERIFIED (2/49 assets bundle-verified + 1 SLSA attestation cross-check).** `checksums.txt` và `codebase-memory-mcp-darwin-arm64.tar.gz` của release v0.10.8 (DeusData/codebase-memory-mcp, tag → commit `46ae198fc11cda80e817acbc5f5908d7c2de7032`) mang chữ ký keyless Sigstore **hợp lệ**, gắn workflow identity đã pin, có Rekor transparency, digest trùng đúng bytes artifact cục bộ. Trust anchor độc lập với kênh tải (không còn phụ thuộc "same-channel checksum" như §8 cũ).

## 0.5. Verify policy (chính xác từng chuỗi, không mở rộng)

| Trường | Giá trị pin (so khớp exact, không regexp nới lỏng) |
| :--- | :--- |
| Distribution repo | `DeusData/codebase-memory-mcp` |
| Release tag | `v0.10.8` |
| Release tag commit (verified) | `46ae198fc11cda80e817acbc5f5908d7c2de7032` |
| `--cert-oidc-issuer` (issuer string) | `https://token.actions.githubusercontent.com` |
| `--cert-identity` (signing identity) | `https://github.com/DeusData/codebase-memory-mcp/.github/workflows/release.yml@refs/heads/main` |
| Cert OIDC ext `1.3.6.1.4.1.57264.1.3` (sha claim) | `46ae198fc11cda80e817acbc5f5908d7c2de7032` (= tag commit; receipt ghi nhận ext `.3`) |
| Trust root | embedded prod `trusted_root.json` sha256 `6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`; Fulcio root `3ba7b6cc…a54680c1`, intermediate `15d79534…87efe47`; Rekor key `wNI9atQG…gB0=` (sha256 `45c9dc64…b023c`) — logId bundle khớp key prod này |

Quy tắc: (1) workflow nguồn pin đọc bằng `git show` tại đúng tag commit, KHÔNG tại main trôi; (2) SAN + issuer phải exact-match; (3) sha claim trong cert phải = release tag commit; (4) Fulcio chain phải mọc từ trust root prod (digest trên); (5) Rekor inclusion verify online, logId bundle ∈ trusted tlog keys; (6) chữ ký phải verify trên đúng bytes artifact local và artifact digest phải = dòng tương ứng trong checksums.txt; (7) **mỗi release mới: đọc lại workflow tại commit mới, re-pin, re-verify** — không tái sử dụng pin cũ.

## 1. Identity/issuer pin — nguồn: workflow tại release commit (không phải HEAD)

`git show 46ae198f…:.github/workflows/release.yml` (643 dòng, đã lưu `/tmp/sot-p0-scratch/release-yml-at-tag.yml`):
- Sign job permissions: `contents: write`, `id-token: write`, `attestations: write`.
- `sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6` # v4.1.2 → `cosign sign-blob --yes --bundle "${f}.bundle" "$f"` cho `*.tar.gz *.zip *.mcpb`, `release-candidates.tsv`, `virustotal-candidate-results.tsv`, `release-selection.tsv`, `checksums.txt` (dòng 229–240).
- `actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373` # v4.1.1; `actions/attest-sbom@c604332985a26aa8cf1bdc465b92731239ec6b9e` # v4.1.0.
- Workflow **tag đúng `$GITHUB_SHA` được dispatch** làm release tag ⇒ chứng chỉ ký phải khai đúng commit `46ae198f…` nếu signing gắn với build thật.

Expected identity (pin cứng cho verify): SAN = `https://github.com/DeusData/codebase-memory-mcp/.github/workflows/release.yml@refs/heads/main`; OIDC issuer = `https://token.actions.githubusercontent.com`.

## 2. Bằng chứng từ certificate + Rekor (bundle v0.3)

Bundle tải từ release: `checksums.txt.bundle` — 10,619 B, sha256 `b92dc7e429a5662063469bddf8449a0f73a19a3eea0dca0438593c0be50a5b5d` (khớp API digest đã ghi `provenance-upstream.md` §2). `mediaType: application/vnd.dev.sigstore.bundle.v0.3+json`.

Certificate (leaf, extract bằng python json/base64, inspect bằng `openssl x509 -text`):
- SAN (critical): `URI:https://github.com/DeusData/codebase-memory-mcp/.github/workflows/release.yml@refs/heads/main` — **khớp pin**, subject rỗng (chuẩn Fulcio keyless).
- Issuer: `O=sigstore.dev, CN=sigstore-intermediate`; validity 2026-08-19 02:34:29→02:44:29 GMT (10 phút, short-lived Fulcio) — bao quanh thời điểm publish 02:42:10Z.
- OIDC claims nhúng trong extension `1.3.6.1.4.1.57264.1.*`: issuer = token.actions.githubusercontent.com; event = `workflow_dispatch`; **sha = `46ae198fc11cda80e817acbc5f5908d7c2de7032`** (ext **`.3`** — claim được receipt ghi nhận; các ext .10/.13 quan sát được cùng giá trị nhưng không được ghi nhận riêng trong receipt); repo = `DeusData/codebase-memory-mcp`; ref = `refs/heads/main`; runner = `github-hosted`; owner = `https://github.com/DeusData`. ⇒ **chứng chỉ tự khẳng định signing workflow chạy tại đúng commit của release tag.**

Rekor transparency: 1 tlog entry, kind `hashedrekord` v0.0.1, **logIndex 2511622896**, integratedTime 2026-08-19T02:34:30Z, có cả `inclusionPromise` lẫn `inclusionProof` trong bundle; `canonicalizedBody` ghi digest = `9d2e33bdf9c9dc8662079d5b9a1bbf716aa2e62e2ed6cc51cf4ae06d42498787` = **đúng sha256 local của checksums.txt (2,658 B)** ⇒ log gắn chặt với đúng bytes artifact.

## 3. Cryptographic verification (công cụ độc lập)

Tool: **sigstore-python 4.5.0**, cài cách ly `python3 -m venv /tmp/sot-p0-scratch/sigstore-venv && …/pip install sigstore` (chạm /tmp, không đụng env user; cosign binary không có sẵn trên máy — dùng path này thay thế). Verify online (Fulcio chain → sigstore roots, SAN+issuer pin, chữ ký trên đúng bytes, Rekor inclusion):

```
/tmp/sot-p0-scratch/sigstore-venv/bin/sigstore verify identity \
  --bundle checksums-v0.10.8.txt.bundle \
  --cert-identity 'https://github.com/DeusData/codebase-memory-mcp/.github/workflows/release.yml@refs/heads/main' \
  --cert-oidc-issuer 'https://token.actions.githubusercontent.com' \
  checksums-v0.10.8.txt
# → stderr "OK: checksums-v0.10.8.txt", exit 0 (transcript: sig-verify-v0.10.8-transcript.json)
```

Transcript receipt (cùng thư mục) lưu đủ: lệnh, stdout (rỗng — sigstore CLI in kết quả ra stderr), stderr, **exit code thực (0/0)**, verifier version (sigstore 4.5.0, CPython 3.14 venv), digests bundle/artifact, digests trust root (mục 0.5). Chạy lần đầu và chạy capture-receipt cho cùng verdict; không có rerun khác.

Artifact darwin-arm64 (đóng vòng chain tới binary đã đối chiếu ở `provenance-upstream.md` §3):
- tar.gz local sha256 = `9bd840dfb3ec7eaef4f310382057adaa5b0e904df883104d03ffcf39836afd07` = dòng darwin-arm64 trong checksums.txt = digest API.
- `codebase-memory-mcp-darwin-arm64.tar.gz.bundle` sha256 `4c0715a7979e5e19cd434a0bd6312f3fb00b094cbf640341f1a521061284f1a6`; verify cùng lệnh trên → **OK**.

Cross-check kênh độc lập thứ hai (GitHub attestation store, khác Rekor bundle):
```
gh attestation verify cbm-darwin-arm64-v0.10.8.tar.gz --repo DeusData/codebase-memory-mcp
# → exit 0; 1 attestation; predicateType https://slsa.dev/provenance/v1;
#   workflow .github/workflows/release.yml@refs/heads/main; repository DeusData/codebase-memory-mcp
```

## 4. Giới hạn (nói thẳng)

1. **Phạm vi:** 2/49 assets verify bundle + 1 attestation. Các asset khác có `.bundle` cùng cơ chế (workflow sign toàn bộ trong 1 loop) nhưng chưa verify từng cái — sweep đủ 49 là follow-up cơ học nếu cần release managed.
2. **Trust anchor:** Sigstore Fulcio/Rekor + GitHub Actions OIDC của org DeusData. Đây là publisher identity độc lập với kênh download TLS, nhưng không bảo vệ trước org/workflow compromise ở release **tương lai** (mỗi release mới phải re-pin + re-verify tại commit mới).
3. Workflow file được đọc tại tag `46ae198f` (content pin đúng), KHÔNG tại main đang trôi (main đã bump attest-build-provenance lên v4.2.2).
4. Không chạy binary, không execute install.sh/workflow — toàn bộ verify là offline-crypto + network API/download tĩnh.
5. File verify-local (`checksums.txt` 9d2e33bd…, `tar.gz` 9bd840df…) là bản copy scratch; digest khớp API + checksums.txt nên chain không phụ thuộc copy.

## 5. Kết luận cho P0/P4

Gate §8 (`provenance-upstream.md`) đã đóng: kênh phân phối có **independent authenticated publisher identity** (Sigstore keyless, Rekor-log, SLSA provenance) cho checksums manifest và artifact darwin-arm64; kết hợp byte-identity §3 cho phép managed artifact release dùng release binary làm reference. Recommendation budget vẫn theo `native-source-inventory.md` §6 (minimal host, không phụ thuộc kết quả này).
