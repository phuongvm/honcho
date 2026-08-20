from pathlib import Path


def test_9router_translator_baseline_response_format_drop_assertion() -> None:
    """Baseline documentation and static inspection assertion for 9Router's openai-to-gemini.js translator.

    Directly inspects the checked-in 9Router translator source code at:
    `oss/9router/open-sse/translator/request/openai-to-gemini.js`

    Verified facts:
    1. The translator converts OpenAI `temperature`, `top_p`, `top_k`, `max_tokens` into Gemini `generationConfig`.
    2. The translator does NOT read `body.response_format` or emit `responseSchema` / `responseMimeType`.
    3. Honcho's `structured_output_mode="json_object"` compensates for this limitation by injecting the Pydantic
       JSON schema instruction directly into the prompt messages.
    """
    translator_path = Path("/home/ubuntu/workspaces/oss/9router/open-sse/translator/request/openai-to-gemini.js")
    assert translator_path.exists(), f"9Router translator source must exist at {translator_path}"

    content = translator_path.read_text(encoding="utf-8")

    # 1. Verify generationConfig mapping exists for basic parameters
    assert "result.generationConfig.temperature = body.temperature" in content
    assert "result.generationConfig.maxOutputTokens = body.max_tokens" in content

    # 2. Verify response_format is NOT handled in openaiToGeminiBase
    assert "body.response_format" not in content
    assert "responseSchema" not in content
    assert "responseMimeType" not in content
