# Sotgraph: benchmark sử dụng thực tế

Bản đánh giá lại • 07/09/2026 • Mục tiêu: giúp tác giả dùng công cụ hiệu quả trong công việc lập trình.

## 1. Kết luận sau khi thực sự chạy công cụ

**Giá trị rõ nhất của Sotgraph trong bộ thử này là ngăn dùng ngữ cảnh đã cũ, rồi hỗ trợ lần theo code và chuẩn bị thay đổi. Chất lượng tìm đúng nơi sửa từ mô tả lỗi còn hạn chế; graph vẫn có cạnh nối sai.** Vì vậy, tôi sẽ dùng Sotgraph làm trợ lý điều hướng và kiểm tra trước khi sửa, đồng thời giữ đọc source và chạy test trong quy trình làm việc.

Bản này thay thế phần đánh giá chính của báo cáo trước. Kết luận dựa trên chương trình đã chạy, kết quả CLI, test, trace runtime và bản sửa có kiểm chứng. Không dùng benchmark do tác giả dự án công bố để xếp hạng. Không đánh giá khả năng bán hàng, thị trường hay mô hình kinh doanh.

| Phép thử mới | Sotgraph | GitNexus | CodeGraph |
|---|---|---|---|
| Tìm lại quan hệ gọi hàm đã chạy | 66/72 | 64/72 | 62/72 |
| Cạnh sai trong 5 đối chứng dict.get | 5/5 | 0/5 | 0/5 |
| Đúng hàm trong 5 kết quả, 24 mô tả lỗi | 10/24 | Chưa đo được FTS | 4/24 bằng query; 2/24 bằng context |
| Ngữ cảnh có dòng lỗi, khi đã biết target | 7/8 ở 1.500 token; 8/8 ở 4.000 | 8/8 trong 4.000 token | 8/8 trong 4.000 token |
| Đọc sau sửa file, trước đồng bộ | Từ chối pack vì stale | Trả source cũ | Trả source cũ |
| Gợi ý test: quan hệ task–test file đã chạy | 6/7; trả 44 lượt file | Detect-changes trả flow; không chấm thành test selector | 7/7 sau cấu hình filter; trả 72 lượt file |

Các dòng đo những việc khác nhau, không cộng thành “điểm tổng”. 66/72 là recall trên luồng quan sát được, không phải precision. Năm đối chứng được chọn để xác nhận một họ lỗi cụ thể, không phải mẫu ngẫu nhiên để suy ra tỷ lệ lỗi toàn graph. Số token là stdout mã hóa bằng cl100k_base, không phải token tính tiền của một phiên AI.

**Đối chiếu với cách làm đơn giản:** baseline ripgrep tìm lại 63/72 quan hệ dưới dạng ứng viên; ripgrep cộng xếp hạng từ khóa tìm đúng hàm trong 8/24 mô tả lỗi. Sotgraph tốt hơn nhẹ trên hai phép thử này, nhưng chưa tạo khoảng cách lớn. Khi đã biết chính xác hàm cần sửa, đọc riêng source hàm là đủ cho cả tám lỗi thử nghiệm.

## 2. Tôi đã làm những việc gì

### Thiết lập và đáp án độc lập

Ba công cụ được build từ commit cố định và chạy trên cùng mã nguồn Requests. Chọn Requests vì có code thật, class, kế thừa, xử lý request/response, hook, cookie, proxy và test có sẵn. Mỗi lỗi chạy trên một bản sao riêng. Toàn bộ benchmark mới sử dụng Python; chưa khái quát sang TypeScript, Java hay repo của bạn.

| Thành phần | Phiên bản khóa |
|---|---|
| Sotgraph | 21cdd1e7dd22469557dd6283cb02c82e66f0d011 |
| GitNexus — abhigyanpatwari/GitNexus | f48bf812566ed06300eb969df9fed5a64d0f66d3 |
| CodeGraph — colbymchenry/codegraph | b9ca4b7981116909900368cc1686a1074cd4d4c1 |
| Requests — psf/requests | dae7ef63b4df6eded86637f251fc4e3a06c3b479 |

“CodeGraph” có nhiều dự án trùng tên; kết quả ở đây chỉ nói về repository nêu trên. Môi trường là Linux x86_64, Python 3.12.13, Node 24.19.0. Sotgraph dùng parser Python builtin; CodeGraph dùng WASM, tắt Rust kernel; GitNexus không dùng embeddings/PDG. Không có đồng bộ nền khi đo freshness.

Đã chạy 244 test upstream thành công và 12 test workflow độc lập thành công: tổng 256 passed, 13 skipped. Các test mới nằm ngoài cây code được index. Chúng xác nhận tám tình huống lỗi và bốn workflow: pipeline Session với adapter trong bộ nhớ, JSON/encoding, đổi HTTP method khi redirect và cookie roundtrip. Không cần gọi dịch vụ HTTP bên ngoài.

Profiler ghi 1.598 lượt gọi trong source Requests, thu được 114 cặp caller–callee khác nhau. Sau khi loại 42 cặp liên quan đến dunder/comprehension hoặc tên nội bộ dạng góc nhọn, còn 72 cặp để đối chiếu trên 57 target. Giữ property access trong mẫu để nhìn thấy khoảng trống khi người dùng muốn hiểu luồng thực thi. Không lấy đồ thị của bất kỳ công cụ nào làm đáp án.

### Tám lỗi có test và patch

Tôi chủ động tạo mutation nhỏ trong code Requests để biết chính xác nguyên nhân và đáp án sửa. Đây là lỗi được cài vào một repo thật, không phải tám issue lịch sử được giải mù. Mỗi test tương ứng thất bại trên bản có lỗi; patch được áp dụng bằng git apply; test tương ứng và toàn bộ bộ thử 256 test đều qua sau sửa.

| Mã | Triệu chứng và chỗ sửa | Kết quả thực chạy |
|---|---|---|
| B1 | Proxy theo host mất ưu tiên; select_proxy duyệt danh sách ngược | Test fail → sửa thứ tự → pass |
| B2 | Authorization còn khi chuyển sang host khác; should_strip_auth trả sai | Test fail → sửa điều kiện → pass |
| B3 | Content-Length tính cả phần stream đã đọc; super_len không trừ vị trí hiện tại | Test fail → trừ current_position → pass |
| B4 | Header None không xóa giá trị của session; merge_setting bỏ bước lọc | Test fail → phục hồi lọc None → pass |
| B5 | Header phân biệt hoa/thường; __getitem__ không chuẩn hóa key | Test fail → lower key → pass |
| B6 | Response do hook trả về bị bỏ qua; dispatch_hook không cập nhật dữ liệu | Test fail → phục hồi nhánh cập nhật → pass |
| B7 | HTTP method bị đổi thành chữ thường; prepare_method dùng lower | Test fail → dùng upper → pass |
| B8 | HTTP 404 không raise; raise_for_status dùng ngưỡng 4000 | Test fail → sửa ngưỡng 400 → pass |

Tám patch và log trước/sau có trong gói bằng chứng. **Không ghi công “8/8 sửa đúng” cho bất kỳ công cụ nào:** tôi biết mutation và tạo patch, chưa chạy ba coding agent độc lập, mù đáp án. Điểm công cụ đo ở các bước thực sự giao cho chúng: tìm target, trả source, chỉ caller, phân tích thay đổi và kiểm tra ngữ cảnh cũ.

### Cách giữ phép so sánh có thể kiểm tra lại

- Mô tả lỗi được khóa trong tasks.json trước khi chạy truy vấn; mỗi lỗi có hai truy vấn tiếng Anh và một tiếng Việt. Không sửa câu hỏi để nâng điểm sau khi xem kết quả.
- Truy vấn caller được cung cấp danh tính target. Sotgraph dùng usages; GitNexus dùng context và UID khi trùng tên. CodeGraph dùng API getCallers với node ID chính xác vì CLI callers gộp hoặc xử lý không ổn định tên method đầy đủ. Do đó bảng recall đo graph sau xác định danh tính, không đo cùng một trải nghiệm CLI.
- Baseline caller dùng ripgrep rồi ánh xạ dòng trùng về hàm chứa nó. Baseline tìm lỗi nhóm các dòng ripgrep theo hàm, xếp hạng số từ khóa khác nhau rồi thứ tự tên. Đây là baseline có script, không phải phép đo tốc độ của con người.
- Phần sửa lỗi đo trên index của bản có mutation. Gói Sotgraph dùng trần 1.500 và 4.000 token; GitNexus context, CodeGraph node và source read được xét trong trần stdout 4.000 token. Các payload chứa thông tin khác nhau.
- Khi một index rỗng hoặc chưa hoàn tất được phát hiện trong bản sao B2/Sotgraph và B1/CodeGraph, tôi phục hồi và đo lại truy vấn liên quan. Log ban đầu và log recovery đều giữ lại. Chưa xác định được nguyên nhân nên không quy thành lỗi thuật toán hay dùng kết quả index hỏng để hạ điểm.
- GitNexus đã được thử cài FTS nhưng không tải được extension từ máy chủ LadybugDB. Vì thế không xếp hạng tìm kiếm ngôn ngữ tự nhiên của GitNexus. Các phép đo graph/context vẫn chạy được.

## 3. Hiểu kiến trúc và lần theo luồng: tốt đến đâu?

### Recall trên quan hệ đã chạy

| Cách lấy caller | Tìm lại được | Recall | Ứng viên production ngoài trace |
|---|---|---|---|
| Sotgraph usages | 66/72 | 91,7% | 56 |
| GitNexus context + UID | 64/72 | 88,9% | 44 |
| CodeGraph API theo node ID | 62/72 | 86,1% | 77 |
| Ripgrep + ánh xạ vị trí | 63/72 | 87,5% | 95 |

Ứng viên ngoài trace có thể đúng ở nhánh chưa chạy; không gọi chúng là false positive. Mẫu nhỏ và các cặp có phụ thuộc lẫn nhau nên chênh lệch 2–4 cặp không đủ để tuyên bố công cụ thắng trên mọi repo.

Sotgraph giúp nối được các bước quan trọng như Session.request, Session.prepare_request và PreparedRequest.prepare. Tuy nhiên, nó bỏ sót Request.prepare gọi PreparedRequest.prepare. GitNexus tìm thấy cặp đó nhưng bỏ sót hai lời gọi đến method kế thừa _encode_params trong lượt đo. Cả ba bỏ sót quan hệ runtime merge_cookies → RequestsCookieJar.update và bốn quan hệ property: path_url, content và is_redirect.

**Ý nghĩa khi tìm hiểu kiến trúc:** graph có ích để bắt đầu đi qua các module và đặt câu hỏi. Một đường bị đứt trên hình chưa chứng minh code không chạy qua đó. Với Python, property, dynamic receiver, kế thừa và dispatch cần kiểm tra bằng source hoặc trace.

### Đối chứng cạnh nối sai

Năm test độc lập thay requests.api.get bằng hàm báo lỗi nếu bị gọi. Các workflow dict.get vẫn chạy thành công. Kết hợp với source của năm hàm, đây là đối chứng cho các cạnh không được nối đến API HTTP get.

| Caller được kiểm tra | Sotgraph nối sang API get | GitNexus | CodeGraph |
|---|---|---|---|
| select_proxy | Có — sai | Không nối | Không nối |
| merge_hooks | Có — sai | Không nối | Không nối |
| dispatch_hook | Có — sai | Không nối | Không nối |
| should_strip_auth | Có — sai | Không nối | Không nối |
| get_encoding_from_headers | Có — sai | Không nối | Không nối |

Đây là lỗi có giá trị sửa cao đối với chính Sotgraph: phép đo vừa cho thấy recall khá tốt, vừa cho thấy một cách tăng độ phủ bằng suy đoán tên có thể tạo cạnh không đúng. Năm đối chứng được chọn sau khi phát hiện vấn đề, nên kết quả chỉ xác nhận họ lỗi này. CodeGraph cũng có những cạnh đáng nghi khác ngoài năm đối chứng; báo cáo không suy ra rằng graph của GitNexus hoặc CodeGraph hoàn toàn chính xác.

Trong kết quả usages get của Sotgraph, trạng thái COMPLETE xuất hiện cùng các cạnh này. Trạng thái đó không thể được dùng như bằng chứng rằng mọi quan hệ có nghĩa ngữ nghĩa đúng. Đối với người dùng, nên nhìn rõ cạnh được suy ra từ receiver nào và với độ chắc chắn nào.

## 4. Tìm bug từ triệu chứng: chưa mạnh như cần thiết

| Truy vấn cố định | Sotgraph search | CodeGraph query | Ripgrep + xếp hạng |
|---|---|---|---|
| Hai mô tả tiếng Anh/lỗi | 9/16 Hit@5 | 4/16 | 7/16 |
| Một mô tả tiếng Việt/lỗi | 1/8 Hit@5 | 0/8 | 1/8 |
| Tổng | 10/24 | 4/24 | 8/24 |
| Đúng ngay kết quả đầu | 3/24 | 1/24 | 2/24 |

Đã chạy thêm lệnh CodeGraph context dành cho mô tả tác vụ: đúng target trong năm node ở 2/24 truy vấn. Một số kết quả chỉ đến class chứa hàm; bảng chỉ chấm đúng hàm, nên không đồng nghĩa mọi lần trượt đều vô dụng. GitNexus không có điểm vì thiếu FTS trong môi trường này.

Ví dụ: các mô tả về proxy thường giúp Sotgraph tìm select_proxy. Nhưng mô tả “partially read stream length” không đưa super_len vào năm kết quả đầu. Lỗi header hoa/thường yêu cầu đi từ cấu trúc dữ liệu đến __getitem__, không chỉ tìm từ “header”.

**Nhận xét thực dụng:** với Sotgraph hiện tại, tôi sẽ để AI rút ra từ khóa code bằng tiếng Anh, xem một vài ứng viên rồi đọc source. Chưa nên kỳ vọng một câu mô tả tiếng Việt tự đi thẳng đến nguyên nhân. Việc AI chuyển ngôn ngữ/từ khóa là quy trình đề xuất từ kết quả, chưa được chấm điểm trong bộ thử này.

## 5. Context cho AI: đủ dòng sửa, nhưng không mặc nhiên ít token

| Cách lấy source khi đã biết target | Có đúng dòng lỗi | Median token stdout |
|---|---|---|
| Sotgraph pack 1.500 token | 7/8 | 1.469,5 |
| Sotgraph pack 4.000 token | 8/8 | 2.364,5 |
| GitNexus context --content | 8/8 | 478 |
| CodeGraph node | 8/8 | 372,5 |
| Đọc riêng hàm bằng sed | 8/8 | 205 |

“Có dòng lỗi” là tiêu chí tối thiểu, chưa phải “đủ mọi contract để sửa an toàn”. Sotgraph cung cấp thêm metadata, caller, callee và stub; các cách khác có payload hẹp hơn. Không dùng tỷ lệ token này để tính ROI hoặc kết luận công cụ nào tiết kiệm chi phí một phiên coding.

Ca B3 là điểm quyết định: source super_len dài, dòng tính kết quả ở cuối. Pack 1.500 token không chứa dòng mutation; pack 4.000 có. Một agent chỉ đọc pack nhỏ có thể thiếu đúng bằng chứng cần sửa dù gói trả về hợp lệ và trong budget.

**Cách tôi sẽ dùng:** lấy đủ source target trước; mở rộng callers/contracts khi thay đổi ảnh hưởng giao diện hoặc hành vi chung. Nếu pack báo cắt source, đọc phần còn lại ngay. Với thay đổi nhỏ đã biết hàm, source read đơn giản hiệu quả hơn việc luôn lấy gói graph nhiều metadata.

## 6. Sửa code rồi đọc lại: lợi thế rõ nhất của Sotgraph

Tôi sửa docstring của select_proxy để có marker nhận diện và thêm một caller mới, sau khi cả ba index đã được xây. Sau đó đọc context mà không chạy đồng bộ.

| Thời điểm | Sotgraph pack | GitNexus context | CodeGraph node |
|---|---|---|---|
| Trước sync | Exit 2, từ chối vì stale | Trả source cũ, thiếu caller mới | Trả source cũ, thiếu caller mới |
| Sau sync | Có marker và caller mới | Có marker và caller mới | Có marker và caller mới |

Không thấy cảnh báo stale trong output đọc context của hai công cụ còn lại ở ca này. Sotgraph đã chặn một tình huống có thể khiến agent tiếp tục suy luận trên code không còn đúng với ổ đĩa. Đây là giá trị thực tế đã quan sát, không chỉ là tuyên bố trong tài liệu.

Lợi ích này có điều kiện: đang nói về các lệnh và cấu hình cụ thể, không suy rộng sang MCP, watcher hoặc mọi chế độ của mỗi dự án. Lượt thử cũ đã cho thấy search mặc định của Sotgraph có thể JIT-reconcile; pack trong thử nghiệm mới chọn từ chối và đòi sync. Người dùng cần hiểu hai hành vi khác nhau này.

## 7. Phân tích thay đổi và chọn test

Tôi đưa từng mutation vào working tree rồi chạy Sotgraph diff-impact ở depth 3, GitNexus detect-changes và CodeGraph affected. Các thư mục index được loại khỏi git diff để chỉ còn đúng file source thay đổi.

Đáp án tối thiểu là các test file upstream thực sự đã chạy vào hàm bị sửa, lấy từ profiler. Trong bộ offline đã chạy có bảy cặp task–test file thuộc diện này; các test mới nằm ngoài index không được tính vào đáp án. B2, B4 và B8 không có test upstream phù hợp trong phần suite đã chạy, nên không tạo thêm mẫu recall.

| Đầu ra dùng để chọn test | Tìm lại cặp đã quan sát | Tổng lượt file được trả |
|---|---|---|
| Lọc test file từ Sotgraph caller_impacts | 6/7 | 44 |
| CodeGraph affected với filter tests/test_*.py | 7/7 | 72 |

Sotgraph bỏ tests/test_adapters.py ở B7, dù test đó thực sự chạy vào prepare_method. CodeGraph sau cấu hình filter trả cả chín test file cho mỗi thay đổi, nên recall cao nhưng độ chọn lọc thấp. Các file ngoài trace chưa chắc thừa; không tính precision từ một suite offline chưa đầy đủ.

CodeGraph affected mặc định trả danh sách test rỗng trong cả tám lượt ban đầu. Kiểm tra cho thấy pattern mặc định tìm đường dẫn dạng /tests/ không nhận tests/ ngay đầu đường dẫn. Truyền filter đúng cho repo Python khắc phục được phần nhận diện test. Tôi đã chấm kết quả sau khắc phục, đồng thời giữ log mặc định để người dùng biết việc cần cấu hình.

GitNexus detect-changes trả symbol và flow bị ảnh hưởng; ví dụ B1 có select_proxy và flow “Send → Select_proxy”. Đây là đầu ra hữu ích cho lập kế hoạch/review, nhưng không coi nó là danh sách test tương đương với affected.

**Hệ quả:** có thể dùng graph để gợi ý nơi cần kiểm tra; chưa nên dùng một danh sách rỗng hoặc danh sách ngắn để quyết định bỏ regression. Tám bản sửa trong thử nghiệm đều đã chạy lại toàn bộ 256 test thành công, thay vì chỉ tin danh sách gợi ý.

## 8. Giá trị cho toàn bộ hành trình lập trình viên

Bảng dưới nối công việc thực tế với những gì đã đo. “Chưa đo trực tiếp” nghĩa là chưa có bằng chứng hiệu quả ở giai đoạn đó, không có nghĩa dự án chắc chắn không hỗ trợ.

| Công việc | Giá trị có thể dùng ngay | Bằng chứng hoặc giới hạn |
|---|---|---|
| Làm rõ yêu cầu và domain | Tìm code hiện thực hành vi để hỏi đúng câu | Không thay đặc tả; chưa đo trực tiếp |
| Dựng môi trường, onboarding | Kết hợp entry code với lệnh chạy/test | Đã build cả ba và chạy Requests |
| Khảo sát repo | Tìm module, class và target để bắt đầu đọc | Search 10/24; cần đổi truy vấn khi trượt |
| Hiểu kiến trúc và luồng | Nối request → chuẩn bị → gửi → xử lý response | 66/72 quan hệ; vẫn có đoạn đứt |
| Tìm code tái sử dụng | Caller/source cho biết chỗ đang dùng hàm | Đã đo caller; chưa đo chất lượng thiết kế mới |
| Thiết kế thay đổi | Lấy contract target, đối chiếu caller | 4.000 token chứa dòng lỗi 8/8 |
| Chia việc, lập kế hoạch | Tách target, caller, test và rủi ro cần kiểm tra | Đã chạy diff; chưa có ước lượng giờ được kiểm chứng |
| Viết tính năng mới | Tìm điểm gắn vào pipeline | Chưa có feature benchmark độc lập |
| Tái hiện và khoanh vùng bug | Dùng triệu chứng để tìm candidate, rồi chạy repro | 8 repro; search vẫn yếu ở nhiều mô tả |
| Sửa bug | Source target + patch + test trước/sau | Đã làm 8 patch; không chấm AI tự sửa |
| Viết/chọn test | Dùng quan hệ gọi và diff để gợi ý test | Sotgraph 6/7 cặp quan sát; có bỏ sót |
| Refactor và đổi API | Kiểm tra caller và những nơi chưa resolve | Receiver/dunder/property cần kiểm tra thêm |
| Review thay đổi | Diff được nối với symbol, caller và flow | Cả ba đã được gọi trên mutation thật |
| Bảo mật | Hỗ trợ lần theo code xử lý credentials | B2 kiểm thử hành vi; chưa phải audit bảo mật |
| Tối ưu hiệu năng | Chọn vị trí đặt profiler từ luồng code | Chưa đo CPU/memory hay load production |
| CI và release | Đặt gate test, freshness và khả năng đọc index | Freshness pack đã có bằng chứng trực tiếp |
| Điều tra sự cố | Graph để định vị; telemetry/repro để xác nhận | Trace offline đã chạy; chưa có incident thật |
| Migration dependency/schema | Liệt kê khu vực cần đổi và kiểm thử | Chưa đo migration nhiều dịch vụ |
| Tài liệu và bàn giao | Ghi lại đường đi có source và giới hạn rõ | Không được biến cạnh suy đoán thành kiến trúc chắc chắn |
| Bảo trì qua nhiều phiên | Đồng bộ index, kiểm tra lại source trước khi dùng | Ca stale cho thấy lợi thế cụ thể của Sotgraph |

Đối với con người, tôi ưu tiên Sotgraph ở onboarding vào một vùng code, phân tích ảnh hưởng và review. Với việc tìm nguyên nhân từ triệu chứng chưa biết tên hàm, vẫn nên mở đồng thời ripgrep, source và test. Với ước lượng thời gian, thiết kế nghiệp vụ hoặc quyết định release, kết quả graph là dữ kiện đầu vào chứ chưa phải đáp án.

## 9. Tôi sẽ dùng và cải thiện Sotgraph như thế nào

### Quy trình sử dụng cho chính công việc của bạn

Bắt đầu bằng repro hoặc mục tiêu thay đổi rõ ràng. Dùng search để lấy vài ứng viên; nếu trượt, chuyển sang từ khóa trong code hoặc ripgrep. Xác nhận danh tính target bằng file và FQN. Lấy source đủ dài; chỉ thêm graph context khi cần caller/contract. Kiểm tra các cạnh receiver phổ biến như get, update, prepare thay vì mặc định tin chúng. Sau sửa, reconcile rồi lấy diff-impact; dùng danh sách test làm gợi ý và chạy regression thích hợp.

Trong quy trình này, AI làm phần đọc/tổng hợp và đề xuất patch; Sotgraph giữ kết nối với source và cung cấp dấu hiệu khi thông tin không còn mới. Test xác nhận hành vi. Đây là cách tận dụng điểm mạnh đã thấy mà không phụ thuộc vào những phần chưa đủ chính xác.

### Thứ tự cải thiện theo tác động quan sát được

| Ưu tiên | Việc cần cải thiện | Điều kiện kiểm tra cụ thể |
|---|---|---|
| 1 | Phân biệt receiver của get, update và method trùng tên | Năm đối chứng không còn nối vào requests.api.get; giữ các cạnh đúng |
| 2 | Ưu tiên source đầy đủ của target trong pack | B3 phải có dòng return; nếu không đủ budget thì chỉ rõ phần thiếu và cách lấy tiếp |
| 3 | Tìm lỗi theo triệu chứng, kể cả tiếng Việt | Theo dõi 24 truy vấn cố định, đồng thời thêm tập giữ lại mới để tránh tối ưu theo đề |
| 4 | Giữ cạnh kế thừa/constructor/property có nhãn rõ | Theo dõi sáu cặp Sotgraph bỏ sót trong graph-results.json |
| 5 | Tách ảnh hưởng do import file và do call vào symbol | Giảm số file phải đọc mà vẫn giữ test thực sự liên quan; đặc biệt B7 |
| 6 | Kiểm tra sức khỏe index ngay sau build | Không tiếp tục benchmark khi node/journal rỗng hoặc resolution chưa hoàn tất |

Tôi không khuyên mở rộng thêm nhiều tính năng trước khi cải thiện các điểm trên. Với mục tiêu tự dùng, một graph bớt gây hiểu nhầm và một pack luôn cho thấy phần source cần sửa có giá trị hơn thêm loại báo cáo nhưng vẫn dựa trên cạnh sai.

## 10. Những kết luận chưa được phép rút ra

Chưa có căn cứ nói Sotgraph làm AI sửa issue thành công hơn GitNexus/CodeGraph, giảm thời gian thực của lập trình viên, hay tiết kiệm tổng chi phí AI. Muốn có các con số đó cần các lượt agent độc lập cùng model/budget và chấm bằng test ẩn. Bản này không thay phép đo đó bằng lời quảng bá; nó hoàn thành các phép thử chức năng và workflow có thể kiểm chứng trong môi trường hiện có.

Cũng chưa có căn cứ nói một công cụ thắng toàn diện: chỉ một repo Python, tám mutation nhỏ, 24 truy vấn do người đánh giá viết, năm đối chứng được chọn có chủ đích, và một cấu hình parser mỗi tool. FTS của GitNexus chưa chạy; MCP/warm server, embeddings, compiler provider và watcher chưa được so sánh. Các phần ngoài trace không được tự động coi là sai.

Kết quả tốc độ ở lượt trước vẫn được giữ trong phụ lục dữ liệu: fresh index median 0,536 giây / 7,272 giây / 0,983 giây và caller CLI median 144,7 / 475,9 / 263,9 ms, theo thứ tự Sotgraph/GitNexus/CodeGraph. Chúng chỉ là thời gian process trên mẫu sáu hàm, không phải thời gian sửa bug. Báo cáo mới không dùng chúng để thay thế chất lượng đầu ra hoặc suy ra năng suất.

## 11. Bằng chứng và cách tái lập

Gói Sotgraph_benchmark_evidence.zip chứa mã benchmark mới, tám patch, test độc lập, dữ liệu runtime và stdout/stderr. Chạy trong một thư mục thử nghiệm mới; hướng dẫn đầy đủ nằm trong build/practical/REPRODUCE.txt. Không cần thay đổi repo làm việc của bạn hoặc cấu hình MCP toàn cục.

| Dữ liệu trong gói | Dùng để kiểm tra |
|---|---|
| evidence/practical/summary.json | Các số liệu tổng hợp cuối cùng |
| runtime-oracle.json và baseline-tests.txt | Trace, coverage theo test và kết quả baseline |
| graph-results.json và graph/ | 72 cặp oracle, dự đoán, cặp thiếu, lệnh và log |
| task-results-final.json và tasks/ | 24 mô tả, context, recovery và patch từng lỗi |
| negative-control-tests.txt | Năm workflow dict.get không gọi API HTTP get |
| freshness/results.json và log cùng thư mục | Source cũ/mới và caller trước/sau đồng bộ |
| test-selection.json | Test file kỳ vọng, được trả và bị bỏ sót |
| build/practical/test_workflows.py | Mười hai test hành vi tự viết, ngoài index |
| build/practical/tasks.json | Mutation và truy vấn được khóa trước khi đo |

Nguồn mã cố định phục vụ tái lập: [Sotgraph](https://github.com/minhgv/sotgraph/tree/21cdd1e7dd22469557dd6283cb02c82e66f0d011), [GitNexus](https://github.com/abhigyanpatwari/GitNexus/tree/f48bf812566ed06300eb969df9fed5a64d0f66d3), [CodeGraph](https://github.com/colbymchenry/codegraph/tree/b9ca4b7981116909900368cc1686a1074cd4d4c1), [Requests](https://github.com/psf/requests/tree/dae7ef63b4df6eded86637f251fc4e3a06c3b479).

Các nhận xét về thuật toán được kiểm tra khi cần để giải thích kết quả thực chạy; README và benchmark tự công bố không được dùng làm đáp án chấm điểm của bản này.
