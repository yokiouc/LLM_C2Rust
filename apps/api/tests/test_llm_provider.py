from patch.llm_provider import OpenAIProvider, TemplateEditProvider, TemplateProvider, provider_from_env


def test_provider_from_env_defaults_to_template(monkeypatch):
    monkeypatch.delenv("PATCH_BACKEND", raising=False)
    p = provider_from_env()
    assert isinstance(p, TemplateProvider)

def test_provider_from_env_template_edit(monkeypatch):
    monkeypatch.setenv("PATCH_BACKEND", "template_edit")
    p = provider_from_env()
    assert isinstance(p, TemplateEditProvider)


def test_template_provider_returns_unified_diff():
    prompt = "\n".join(
        [
            "1. 接口签名保持完全不变",
            "2. 仅允许最小化语义补丁，禁止全文件重写",
            "3. 必须引用 Evidence Pack 中的具体条目（行号、函数名、切片）",
            "4. 输出格式必须为统一 diff（unified diff），且只包含 `@@` 块",
            "5. 若无法生成符合上述约束的补丁，返回空 diff 并给出原因",
            "",
            '{"file":"src/lib.rs","slice":"line1"}',
            "",
            "f",
        ]
    )
    diff = TemplateProvider().generate(prompt)
    assert diff.startswith("--- a/")
    assert "+++ b/" in diff
    assert "@@ " in diff


def test_template_edit_provider_changes_line():
    prompt = "\n".join(
        [
            "1. 接口签名保持完全不变",
            "2. 仅允许最小化语义补丁，禁止全文件重写",
            "3. 必须引用 Evidence Pack 中的具体条目（行号、函数名、切片）",
            "4. 输出格式必须为统一 diff（unified diff），且只包含 `@@` 块",
            "5. 若无法生成符合上述约束的补丁，返回空 diff 并给出原因",
            "",
            '{"file":"src/lib.rs","slice":"pub fn demo() {\\n    let x = 1;\\n}"}',
            "",
            "f",
        ]
    )
    diff = TemplateEditProvider().generate(prompt)
    assert "-    let x = 1;" in diff
    assert "+    let x = 1; // patched" in diff


def test_openai_provider_without_key_returns_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PATCH_BACKEND", "openai")
    p = OpenAIProvider()
    assert p.generate("x") == ""
