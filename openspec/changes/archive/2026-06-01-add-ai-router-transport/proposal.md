## Why

Hiện tại Honcho chỉ hỗ trợ các cấu hình chung cho các transport như `lmstudio`, `nous` nhưng không có cách định nghĩa biến môi trường toàn cục (global environment variables) cho proxy tương thích OpenAI API (như 9Router, LiteLLM). Người dùng buộc phải override cấu hình `base_url` và `api_key` cho từng cấu hình model bằng `openai` transport. Việc thêm transport `ai-router` sẽ tách biệt logic của OpenAI Cloud và Local/Proxy Routers, đồng thời cải thiện đáng kể Developer Experience bằng cách cho phép cấu hình `AI_ROUTER_BASE_URL`.

## What Changes

- Thêm transport mới `ai-router` vào danh sách `ModelTransport`.
- Bổ sung `AI_ROUTER_API_KEY` và `AI_ROUTER_BASE_URL` vào cấu hình global của `LLMSettings`.
- Cập nhật quá trình nạp thông tin đăng nhập trong `credentials.py` và backend registry trong `registry.py` để hỗ trợ transport này giống hệt như `lmstudio`.

## Capabilities

### New Capabilities
- `ai-router-transport`: Tính năng hỗ trợ transport mới dành cho các OpenAI-compatible AI routers.

### Modified Capabilities


## Impact

- `src/config.py`: Mở rộng `ModelTransport` Enum, cập nhật `LLMSettings`.
- `src/llm/credentials.py`: Phân giải khóa API mặc định cho transport mới.
- `src/llm/registry.py`: Đăng ký và khởi tạo client `AsyncOpenAI` với `base_url` mới.
- Tương thích ngược hoàn toàn với các transport hiện hữu.
