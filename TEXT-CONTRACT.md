# 正文、字节及读取合同 v1

本合同适用于阶段1纯聊天入口，标识为 `chat_utf8_preserve_v1`。`complete` 仍表示已通过当前机械来源/身份/顺序策略；任何已知来源、身份、顺序、解析或正文缺口均使其为 false，不改变含义来吸收反例。

## 来源快照

1. 每个显式传入的普通 JSONL 文件读取一次原始 bytes，保存该快照的 SHA-256、字节数、修改时刻和行数。不会改写原日志。
2. 对同一份 bytes 做严格 UTF-8 解码，传给复用的经典解析循环。非法字节使该来源提取失败，issues给出文件、行号和零基字节偏移，不使用U+FFFD替代。输入原本合法编码的U+FFFD是正常原话。
3. 物理 JSONL 的 LF/CRLF 属于容器分行。解析循环保留行尾，使 `line_text_sha256` 与该物理行原始 bytes 相符。末行缺LF仍按未完成边界报告，不把容器分行规则当成正文换行归一化。
4. JSON字符串解码得到的正文内 CRLF、单独CR、LF、空格、制表符、组合字符均保留；不做Unicode正规化，不去首尾空白。

## 规范正文

- 角色头为 `## user` 或 `## assistant`，后接两个LF。
- 一条消息中，按原始content下标保留经来源核查的text字段；块之间加入两个LF。空块、空白块和重复块仍占原位置。
- 消息之间加入两个LF；存在消息时全文最后追加一个LF。
- 这些格式字符共同属于最终正文，全部参与计数。正文中的现有换行不会被统一替换为LF。
- 外部图片、文件等附件本体不读取；正文里用户自己输入的路径、JSON、代码、引用、截断字样或旧命令保持字面含义。

## 全文计数和后续读取

输出文件用 `text.encode('utf-8')` 写入bytes，无BOM。hash是最终文件全部bytes的SHA-256。字符数为Python Unicode码点数，不是字节数或视觉字形数。

计数严格执行：

```python
raw = path.read_bytes()
text = raw.decode('utf-8', errors='strict')
tokens = len(tiktoken.get_encoding('cl100k_base').encode(text, disallowed_special=()))
```

可使用本阶段提供的 `chat_monitor.material.count_file(path, encoding)`。`count_text` 对传入字符串全文编码，不会分行相加，也不会正规化。

**后续读取必须使用原样bytes解码，或显式关闭文本换行转换。默认 `Path.read_text()`/`open(..., newline=None)` 会把内嵌CRLF/CR转为LF，不满足本合同。** 文件hash应直接对bytes核对，不能对已经经过换行转换的文本重编码后冒称同一文件。当前后续阶段草稿尚未按本合同完成接入，不属于本批交付。

计数字段保留 `calibrated=false`、`target=gpt-6.1-sol/xhigh`、`newline_policy=preserve_embedded_crlf_cr_lf`、`unicode_policy=no_normalization`。cl100k_base的精确全文计数不代表目标模型的原生tokenizer已校准，也不代表实际蒸馏入口窗口安全。

## 可见性、来源与顺序边界

- 原生助手可见channel为commentary/final，可见phase为commentary/final_answer；analysis/justify/confidence为内部元信息。未知channel/phase（含summary）报告未核实。没有可见性元信息的原生message报告未核实；已核对的完成态AgentMessage可作为桌面可见形式，但仍检查显式phase/channel。
- user逐块来源必须可核对。完成态UserMessage没有逐块元数据时沿用有client_id的既有桌面表示策略；一旦提供逐块元数据，就必须核对其完整性和矛盾，client_id不覆盖它。
- 只向后续分类器传递已核查的type/text；summary/output/content等额外字段不扩展正文，另在fields_excluded记录字段名。
- 来源引用指原始 `payload.content[i]` 或 `payload.item.content[i]`，text_fields进一步指向 `.text`。完成态原始内联text使用 `payload.item.text`，不编造content数组。
- 镜像只在既有身份/回合/形式策略成立时关联；唯一多块用户投影复用原helper，多个候选保留并报告不确定。
- 多日志先关联身份，再以每份来源里同一身份的首次出现建立消息次序约束。镜像的后续出现不创建新消息。只有互不约束的可选消息头需要比较时间，比较显式时区的RFC3339时刻（小数秒支持1—6位），不比较字符串。
- 等时或缺时且无来源约束，报告 `ambiguous_cross_source_order`；来源次序成环报告 `conflicting_source_message_order`；不支持的时间格式报告 `unsupported_message_timestamp`。失败时仍保留正文和来源供诊断，确定性展示顺序不被称作已验证顺序。
- 来源内顺序约束优先于时间戳；原始时间留在refs，归一化UTC时间用于跨页分支比较和activity。两个独立、同时间且没有重叠身份的文件不能凭文件名推断先后。
