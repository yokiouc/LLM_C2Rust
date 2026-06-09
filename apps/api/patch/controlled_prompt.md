1. 接口签名保持完全不变
2. 仅允许最小化语义补丁，禁止全文件重写
3. 必须引用 Evidence Pack 中的具体条目（行号、函数名、切片）
4. 输出格式必须为统一 diff（unified diff），且只包含 `@@` 块
5. 若无法生成符合上述约束的补丁，返回空 diff 并给出原因

Output ONLY raw unified diff.
Do NOT use Markdown.
Do NOT wrap in ```diff.
Do NOT explain.
First line must be: --- a/<relative path>
Second line must be: +++ b/<relative path>
Use exactly the target file path.
Generate a single-file patch.
Generate a single hunk.
The hunk old_start must be inside the repair slice boundary.
Do not modify function signatures.
Do not modify forbidden regions.
Do not add unrelated marker lines such as _ptr_import_marker.
Do not modify imports.
The old hunk lines must match the target file exactly.
Only replace the unsafe block or target unsafe statement inside the repair slice.
{evidence}

{target_function}
