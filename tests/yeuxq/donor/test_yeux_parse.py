from yeuxq.intel.yeux_client import _extract_tool_text, _parse_sse_jsonrpc


def test_parse_sse_jsonrpc():
    text = (
        "data: \n"
        "id: 0\n"
        "\n"
        'data: {"jsonrpc":"2.0","id":3,"result":{"content":'
        '[{"type":"text","text":"hello"}]}}\n'
        "\n"
    )
    msgs = _parse_sse_jsonrpc(text)
    assert msgs
    assert msgs[0]["id"] == 3
    assert "result" in msgs[0]


def test_extract_tool_text():
    result = {"content": [{"type": "text", "text": "abc"}], "isError": False}
    assert _extract_tool_text(result) == "abc"


def test_secrets_load_smoke():
    from yeuxq.intel.secrets import load_intel_config, mask_secret

    cfg = load_intel_config()
    assert "llm_model" in cfg
    assert "yeux_mcp_url" in cfg
    assert mask_secret("abcdefghij") == "****"
