# Codex 纯聊天监控

Windows 上的本地试用工具：从明确指定的 Codex JSONL 来源提取用户原话和可见助手回复，核对来源、身份、顺序及镜像，对同一份 UTF-8 正文做全文 token 计数，并显示悬浮窗及预算提醒。

**状态：实验版本。阶段3与有限3.5A已有本地独立验收，3.5B真实试用已完成但尚未放行。已知问题：有效计数恢复后，旧异常提醒可能仍显示并要求确认。真实模型窗口与材料预算未校准。**

## 能力和边界

- 可见聊天正文累计；工具调用/返回、宿主指令、内部推理按已核来源结构排除。原话中的代码、路径、引用与真正重复保留。
- 同一最终 bytes 的 SHA-256、Unicode码点和 `cl100k_base` 全文计数。未知来源、格式、身份或排序报告未核实。
- 多聊天发现、串行调度、排除恢复及提醒状态持久化。默认显示最近5个聊天。
- 50%/75%程序自有非激活提示卡，90%/超限需要确认；人工预算等号显示已到上限，不增加第五档。
- 不读取模型真实上下文占用，不承诺原生tokenizer兼容或安全容量；`.jsonl.zst`、真实DPI/登录自启动等边界尚未完成。
- 准备包/迁移入口仍受阶段门禁限制，GUI按钮禁用；仓库包含历史草稿模块，不代表已获准用于迁移。

## 本地运行

需要 Windows、Python 3.12（带Tk），建议新建项目虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/create_demo.py
.\.venv\Scripts\pythonw.exe -B -m chat_monitor --config .tmp/demo/config.json
```

窗口启动后，在另一个终端创建合成输入以触发发现：

```powershell
.\.venv\Scripts\python.exe scripts/create_demo.py --append
```

点击“退出”停止本实例；关闭标题栏只隐藏，后台仍监控。找回隐藏窗口可以在其独立runtime下创建`show.request`；`stop.request`用于明确停止。示例只用合成内容和1000 token人为预算。

真实接入前，请先明确唯一来源目录、项目白名单、累计范围及独立runtime。不要把含其他私人聊天的全量sessions目录直接用于试用。可选`publication_root`让输出留在独立目录，配置示例见`config.example.json`（请替换绝对路径，不要原样启动）。

## 验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest -v tests.test_extract tests.test_stage1_revision tests.test_stage1_report_cases tests.test_stage1_r1 tests.test_engine tests.test_resilience tests.test_stage2 tests.test_stage2_review tests.test_stage35_real_schema tests.test_medium_config tests.test_publication_scope
```

本地完整检查为103个方法；公开导出中2个依赖授权真实聊天的测试明确跳过，预期101项执行通过、2项skip。原真实样本、预期正文、截图和运行回执均不上传，不使用合成数据冒充原真实证据。公开合成夹具的本机路径已替换，但保留非法UTF-8反例的原故障字节。GUI/F3历史单测需要桌面环境，不包含在上述命令中。

## 历史与贡献日期

本地原项目没有Git历史。此仓库按保存的开发冻结重建13个**脱敏快照导入**，不是原开发提交；标签保留版本名称，日期依据批次标签，原manifest hash留作本地来源校验依据。详见`HISTORY.json`。

依用户要求，旧源码导入的author和committer均使用未关联用户账号的`Historical snapshot import <snapshot-import@invalid>`，提交时间为实际导入时间，不伪造旧Git提交日期，不将旧版本导入计为用户今天的代码贡献。仓库创建/首次公开本身仍真实发生于导入当天。未来正常开发可使用仓库配置的用户身份提交。

历史标签里的启动脚本统一使用本项目`.venv`，导出不带旧机器Python路径。历史版本可能包含当时尚未修复的问题，不能把标签名称当“每版均通过”的证明。辅助验收工具、失败半成品及私人证据仅本地保留，未冒充公开源历史。

## 第三方及数据

`vendor/codex-exporter`基于[lowestprime/codex-exporter](https://github.com/lowestprime/codex-exporter)，原MIT许可证保留；本项目对其提取策略有本地修改。`vendor/watcher`包含watchexec 2.8.0 Windows发布二进制及其Apache-2.0许可证。tokenizer cache为`cl100k_base`公开编码缓存。上游来源见`vendor/provenance.json`。

仅公开仓库不自动赋予本项目自有代码新许可证；此导入未替作者选择额外开源许可。各第三方组件继续适用其自身许可证。

不要将真实日志、材料、截图、密钥、cookie或本机配置加入本仓库。公开导出保留所有本地冻结原件，不覆盖开发主工程。
