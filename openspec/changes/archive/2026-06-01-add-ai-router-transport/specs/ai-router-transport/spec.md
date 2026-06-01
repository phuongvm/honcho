## ADDED Requirements

### Requirement: Global configuration for AI Router
Hệ thống SHALL cho phép cấu hình API Key và Base URL cho transport `ai-router` thông qua biến môi trường.

#### Scenario: User provides global AI Router environment variables
- **WHEN** file `.env` có thiết lập `LLM_AI_ROUTER_API_KEY` và `LLM_AI_ROUTER_BASE_URL`
- **THEN** cấu hình `LLMSettings` sẽ tự động load các biến này vào `AI_ROUTER_API_KEY` và `AI_ROUTER_BASE_URL`

### Requirement: AI Router transport declaration
Hệ thống SHALL hỗ trợ khai báo `"ai-router"` trong danh sách `ModelTransport`.

#### Scenario: User sets model transport to ai-router
- **WHEN** một dialectic/model config sử dụng thuộc tính `TRANSPORT=ai-router`
- **THEN** hệ thống xác nhận cấu hình hợp lệ (validation success)

### Requirement: Client resolution for AI Router
Hệ thống SHALL sử dụng cấu hình global khi khởi tạo Backend Client cho `ai-router` nếu cấu hình `base_url` cụ thể trên model bị khuyết.

#### Scenario: Default client resolution
- **WHEN** model config dùng `transport="ai-router"` không override `base_url`
- **THEN** BackendRegistry sử dụng `settings.LLM.AI_ROUTER_BASE_URL` và `settings.LLM.AI_ROUTER_API_KEY` để khởi tạo `AsyncOpenAI` client

#### Scenario: Override client resolution
- **WHEN** model config dùng `transport="ai-router"` có override `base_url` cụ thể
- **THEN** BackendRegistry ưu tiên sử dụng override `base_url` kết hợp với global API key (hoặc override API key nếu có)
