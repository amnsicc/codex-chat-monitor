# C1 保守离线材料合同 v1

状态：开发候选，等待原验收聊天独立复验。原严格入口、120项旧测试、worker、GUI和预算策略不变；本入口没有自动调用链。

## 入口与来源

`python -B -m chat_monitor.conservative --spec SPEC --output NEW_DIRECTORY --zstd-python EXISTING_PYTHON314`

spec 是显式 JSON：`source_id`、绝对 `project`、`encoding`（可选，默认 cl100k_base）、`sources`。sources 每项必须有 `path`、预期 `sha256`、`bytes`。此列表是本次完整预期集合，缺失/变更报告 hard，不主动扫描目录或补来源。不能检测声明列表之外被遗忘的页，因此 coverage 只表示声明集合，不表示整个聊天历史。

输出目录必须不存在。先读取固定原始bytes，检查stat、预期长度/hash，再严格UTF-8读取。zst仅在显式传入已存在的Python3.14辅助解释器时，以标准库compression.zstd解压；辅助进程-I -B，不改PATH、不安装依赖。压缩失败不使用部分stdout。解压前后hash、辅助argv/退出码/stderr记入来源清单。原始与解压快照均保留；原始无效bytes不以替换字符进入材料。

每份来源所有session_meta的ID与项目必须符合spec；subagent来源、记录thread/session ID矛盾、turn_context项目矛盾整份隔离，不混入材料。生产严格解析使用固定bytes的JSONL副本，坏行留空以保留物理行号，原始坏行及不可解码bytes仍在snapshots证据中。无效行、非对象行、无最终LF、显式截断均报告hard。严格解析器遇到新结构异常时降级为hard诊断包，保留可判读候选，不将异常改为成功。

## 保留与排除单元

1. 严格解析器、身份去重、顺序协调均复用旧实现。已证明身份和正文一致的镜像仍安全合并。严格结果先作为正文；同ID不同版本、真实重复和难配对表示不取最长、不全局同文去重。
2. 只补入严格审计未纳入的位置。已支持消息的`payload.content[i]`/`payload.item.content[i]`是补入单元；单个已知文本part只有text/来源/截断字段时，精确保留text；来源缺失与显式来源矛盾有不同uncertainty标签。无法安全确定字段时保留JSON投影。补入单元之间不额外去重，允许压缩/普通重叠中仍未证实身份的候选冗余。
3. 严格合同已确认的配置、宿主、内部助手、工具和运行事件继续排除。配置high/max仅扩展原核实形状的effort枚举，额外未知字段会阻止此排除。显式可见/内部可见性矛盾保留待判读。来源核实的环境继续排除；新增skill/tool通知/中止注入仅在精确kind+provenance配对且part无矛盾时排除：skills/skills.selected_skill_instructions、tool/multi_agent.subagent_notification、harness/generic.turn_aborted。只有kind、缺少provenance的旧内容仍保留。
4. event_msg/item_completed的SubAgentActivity和ContextCompaction、inter_agent_communication_metadata是结构性协作/压缩事件。response_item/agent_message还必须同时有以`/`起始的author/recipient及metadata.client_authored=false才作为协作排除；只有名字不够。用户text中的这些词没有删除作用。
5. 新未知记录以完整对象的JSON投影为单元，不递归抽取字符串拼成聊天。已知消息part的未知额外字段、消息的未知字段、未知顶层字段、content旁并行text也有单独投影。已知路由/来源元数据（type、role、id、turn_id、client_id、channel、phase、recipient、provenance、internal_chat_message_metadata_passthrough、timestamp、ordinal、metadata及截断标记）不是正文，存于原始证据和审计，不自动当原话。
6. JSON投影按原对象顺序，以ensure_ascii=false、indent=2序列化，不声称与原始JSON字节相等。递归投影只在结构type明确为已知附件/工具/推理/协作，或role为system/developer/tool时替换子树；明确二进制键base64/b64_json/image_bytes/audio_bytes/file_bytes不纳入。每次剔除有field及reason，原始bytes始终可定位。未知字段的普通字符串不按关键词/base64外观猜删；未知字符串可能仍是非聊天或未识别附件数据，明确为待判读，不能保证材料纯净。
7. local_image及原已知图片/文件/音频附件本体排除，文字说明保留。未知记录的JSON是待判读内容，不叫纯聊天。快照中的命令、技能调用及指令只为证据，不执行。

## 状态与计数

- `complete`与`strict_complete`仍要求旧严格extract无issues且没有hard。即使新模式已安全排除某些旧未知类型，旧严格仍可为false；绝不因有文字而true。
- `source_coverage`只覆盖显式声明的来源集；`hard_issues`独立列读取/身份/解析/截断缺口；`soft_issues`记录旧严格疑点及新增待判读位置。soft可以导出并计数；hard可以导出诊断材料，禁止声称当前安全或完整。
- `included_material_preserved`仅指本次确定纳入单元已写入材料，不代表丢失来源、不可解码bytes和未识别正文都已还原。
- `quality`为strict_observed/conservative_unverified/partial_diagnostic；`safe_remaining_budget`恒为null，预算和目标tokenizer仍未校准，不接GUI与提醒。
- 只计最终material.md的严格UTF-8 bytes对应全文，包括前言、角色头、标签、分隔、JSON投影及缺口说明。内嵌CRLF/CR/LF及Unicode不归一化。原始JSON投影里的换行按JSON转义序列化，这是新格式的明确合同。
- manifest/coverage/strict-audit/input-spec和snapshots不是默认模型输入，不藏入正文预算；若后续额外读取，必须另计并预留。不存在正式迁移启动单元或索引。
- `count_valid`只表示本份已取得材料的全文计数成功且同hash；有hard时仍可能true，但不表示整个聊天计数有效。计数后再次核对原始来源，发生变化则count_valid=false，包仅作诊断，须在新目录重建，不能复用为有效读取包。所有来源有bytes截止点/hash；不声称这些截止点构成全聊天时间终点。

## 交付与边界

manifest列政策/状态/来源hash/计数/纳入排除数量/soft/hard；coverage逐物理有效记录列严格纳入、补入单元数量及排除理由；material的每个待判读头精确标source序号/物理line/field。snapshot序号映射manifest.sources；parse副本仅为旧解析器适配，不替代原始证据。

固定20样本是开发回放，不是独立全文真值。未增加留出样本读取、真实监听、GUI试用、模型调用、蒸馏、正式迁移、部署或GitHub同步。C1完成即停等原验收聊天；C2/C3与阶段4不自动启动。
