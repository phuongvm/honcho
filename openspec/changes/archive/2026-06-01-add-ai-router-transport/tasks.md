## 1. Cấu hình & Types

- [x] 1.1 Thêm `"ai-router"` vào `ModelTransport` Enum trong `src/config.py`
- [x] 1.2 Thêm biến `AI_ROUTER_API_KEY` và `AI_ROUTER_BASE_URL` vào class `LLMSettings` trong `src/config.py`

## 2. LLM Backend Registry

- [x] 2.1 Cập nhật `default_transport_api_key` trong `src/llm/credentials.py` để xử lý `ai-router`
- [x] 2.2 Đăng ký client `ai-router` mặc định trong dict `CLIENTS` ở `src/llm/registry.py`
- [x] 2.3 Cập nhật `client_for_model_config` để hỗ trợ custom logic fallback base_url cho `ai-router` trong `src/llm/registry.py`
- [x] 2.4 Bổ sung `"ai-router"` vào điều kiện bọc `OpenAIBackend` trong `backend_for_provider` ở `src/llm/registry.py`

## 3. Cập nhật .env file

- [x] 3.1 Sửa đổi file `/home/ubuntu/workspaces/docker-compose/honcho/.env` để cấu hình `DIALECTIC_LEVELS__max__MODEL_CONFIG__TRANSPORT=ai-router`
- [x] 3.2 Xóa các biến `OVERRIDES` trong `.env` và thiết lập biến global `LLM_AI_ROUTER_BASE_URL` & `LLM_AI_ROUTER_API_KEY`

## 4. Kiểm thử

- [x] 4.1 Chạy quy trình kiểm tra syntax và khởi động thử Backend Client
