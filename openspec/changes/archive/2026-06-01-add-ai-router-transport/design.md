## Context

Honcho codebase hiện hỗ trợ kết nối tới OpenAI, Anthropic, Gemini, LMStudio, và Nous. Các proxy nội bộ tương thích OpenAI như `9Router` hay `LiteLLM` có thể sử dụng transport `openai`, tuy nhiên người dùng không có cách nào đặt cấu hình global `BASE_URL` cho chúng. Việc dùng biến môi trường OVERRIDES làm cấu hình trở nên rối rắm. Chúng ta cần một transport mới tên là `ai-router` có chức năng hoạt động chính xác như `lmstudio`, nhưng dùng biến số và Enum riêng.

## Goals / Non-Goals

**Goals:**
- Cung cấp transport `ai-router` giúp người dùng cấu hình proxy tương thích OpenAI.
- Cấu hình global API key và Base URL thông qua biến `LLM_AI_ROUTER_API_KEY` và `LLM_AI_ROUTER_BASE_URL`.

**Non-Goals:**
- Không thay đổi hành vi của transport `openai` chuẩn.
- Không viết lại backend client mới (sẽ tái sử dụng `OpenAIBackend`).

## Decisions

**1. Tái sử dụng `OpenAIBackend`:**
Vì các hệ thống AI Router (như 9Router, LiteLLM) cung cấp endpoint tương thích với OpenAI API, ta chỉ cần sử dụng thư viện `AsyncOpenAI` và bọc trong lớp `OpenAIBackend` của hệ thống. Đây là pattern đã được ứng dụng cho `lmstudio`.

**2. Đặt tên biến môi trường:**
Sử dụng `AI_ROUTER_API_KEY` và `AI_ROUTER_BASE_URL` trong `LLMSettings`. Chúng sẽ tự động được load bởi `pydantic-settings` với tiền tố `LLM_` ở đầu, tạo thành `LLM_AI_ROUTER_API_KEY` và `LLM_AI_ROUTER_BASE_URL` trong file `.env`.

**3. Khởi tạo Client mặc định:**
Trong `src/llm/registry.py`, ta khởi tạo `CLIENTS["ai-router"]` để caching client khi có khai báo toàn cục (Global fallback). Quá trình này hoàn toàn tương tự `lmstudio`.

## Risks / Trade-offs

- **[Risk]** Transport `ai-router` trùng lặp chức năng cơ bản với transport `lmstudio` và `openai`.
  - **Mitigation**: Việc này nhằm tách bạch mục đích cấu hình (Intent) ở tầng người dùng. Các hệ thống phía dưới (`get_openai_override_client` và `OpenAIBackend`) đã được tái sử dụng toàn bộ nên không sinh ra thêm bugs và không gây nợ kỹ thuật lớn.
