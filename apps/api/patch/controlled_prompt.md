1. 接口签名保持完全不变
2. 仅允许最小化语义补丁，禁止全文件重写
3. 必须引用 Evidence Pack 中的具体条目（行号、函数名、切片）
4. 输出格式必须为统一 diff（unified diff），且只包含 `@@` 块
5. 若无法生成符合上述约束的补丁，返回空 diff 并给出原因

{evidence}

{target_function}
