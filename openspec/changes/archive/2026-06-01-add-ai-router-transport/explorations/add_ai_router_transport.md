# Exploration: Adding `ai-router` Transport to Honcho

## Vấn đề hiện tại
Người dùng cần thêm transport `ai-router` vào Honcho để có thể kết nối với các Smart Router nội bộ như [9Router](https://github.com/decolua/9router) hoặc LiteLLM (giúp tiết kiệm token bằng RTK và fallback tự động). 
Các AI Router này sử dụng giao thức tương thích với OpenAI API (giống như LMStudio, vLLM, Nous...).
Cấu hình hiện tại bắt buộc phải override `base_url` và `api_key` cho từng cấu hình model nếu sử dụng `openai` transport (như đã phân tích trước đó). Việc thêm một transport `ai-router` độc lập là giải pháp tốt nhất vì:
1. Tách biệt mục đích (Intent) khỏi `openai` (vốn hướng tới OpenAI cloud).
2. Cho phép cấu hình Global biến môi trường riêng như `LLM_AI_ROUTER_API_KEY` và `LLM_AI_ROUTER_BASE_URL`.

## Sơ đồ tích hợp

```ascii
┌───────────────────┐          ┌───────────────────────┐          ┌───────────────┐
│   Honcho Client   │          │ AI Router (localhost) │          │ AI Providers  │
│                   │          │                       │          │               │
│ transport=ai-router├────────▶│ port: 20128/v1        ├─────────▶│ - Kiro AI     │
│                   │ (OpenAI) │                       │          │ - OpenCode    │
│                   │          │                       │          │ - Claude Code │
└───────────────────┘          └───────────────────────┘          └───────────────┘
```

## Các file cần thay đổi trong mã nguồn Honcho

Sau khi khảo sát kiến trúc của `oss/honcho`, đây là các điểm cần can thiệp để tích hợp `ai-router` y hệt như `lmstudio`:

### 1. Cấu hình (`src/config.py`)
- Mở rộng kiểu dữ liệu `ModelTransport`: Thêm `"ai-router"`.
- Bổ sung cấu hình toàn cục trong `LLMSettings`:
  ```python
  AI_ROUTER_API_KEY: str | None = None
  AI_ROUTER_BASE_URL: str | None = "http://localhost:20128/v1"
  ```

### 2. Xử lý thông tin đăng nhập (`src/llm/credentials.py`)
- Cập nhật hàm `default_transport_api_key(transport)` để trả về `settings.LLM.AI_ROUTER_API_KEY` khi `transport == "ai-router"`.

### 3. Đăng ký Backend (`src/llm/registry.py`)
- Trong phần nạp tĩnh `CLIENTS`:
  ```python
  if settings.LLM.AI_ROUTER_API_KEY:
      CLIENTS["ai-router"] = AsyncOpenAI(
          api_key=settings.LLM.AI_ROUTER_API_KEY,
          base_url=settings.LLM.AI_ROUTER_BASE_URL,
          timeout=settings.LLM.DEFAULT_TIMEOUT,
      )
  ```
- Cập nhật luồng tạo client động trong `client_for_model_config()`:
  ```python
  if provider == "ai-router":
      ai_base = base_url or settings.LLM.AI_ROUTER_BASE_URL
      return get_openai_override_client(ai_base, api_key)
  ```
- Cập nhật luồng wrap backend SDK trong `backend_for_provider()`:
  ```python
  if provider in ("openai", "lmstudio", "ai-router"):
      return OpenAIBackend(client)
  ```

### 4. File cấu hình mẫu (`.env`)
- Sau khi code hỗ trợ, người dùng chỉ cần thêm cấu hình sau vào `.env`:
  ```env
  LLM_AI_ROUTER_API_KEY=sk-b37783bb97a4cd8e-lnbecs-7a05d2bd
  LLM_AI_ROUTER_BASE_URL=http://192.168.100.110:20128/v1
  ```
- Thay đổi cấu hình model để sử dụng transport mới:
  ```env
  DIALECTIC_LEVELS__max__MODEL_CONFIG__TRANSPORT=ai-router
  ```

## Kết luận
Việc dùng tên gọi `ai-router` thay vì `9router` mang tính khái quát (generic) và tốt hơn rất nhiều về mặt thiết kế hệ thống. Bất kỳ OpenAI-compatible proxy nào (như 9Router, LiteLLM) đều có thể được sử dụng qua transport `ai-router` độc lập.

## Trạng thái
- Sẵn sàng để được đóng gói thành Proposal.
