# 本地偏好管理

仅在明确持久化要求、冲突或绑定变化时阅读。普通查询自动返回适用规则，不额外进行全量历史分析。

## 授权与范围

- “这次用 A”只改当前方案；“本次对话优先 A”保留在对话；明确“记住/以后这类任务…”才持久化。范围含糊时提交一句待保存规则，明确授权后再写；已有清楚授权直接完成。
- 规则种类：`prefer` 优先、`avoid` 尽量避免、`exclude` 明确排除、`prompt` 输出或流程偏好。单次失败是反馈，不自动转为排除。不做隐式使用计数、自动评分或完整日志。
- `scope.kind` 为 `personal` 或 `project`，项目必须指定已核对的实际根路径。项目规则仅匹配该路径及其子目录，不匹配同名前缀目录。`task_tags` 为空代表范围内所有任务，应有明确授权；非空要求所有标签匹配。
- 标签是调用方依据当前任务提供的简短分类；统一使用偏好中已存在的标签，核对其语义。不以检索词或推测的任务类型自动扩大偏好范围。无法合理匹配时不套用，必要时确认。
- 同时适用时当前明确指令优先，项目规则优先于个人规则。相同优先级的 `prefer` 与 `avoid/exclude` 冲突时复核冲突部分；`avoid` 与 `exclude` 同向，使用明确排除。Prompt 规则均返回；模型检查输出/流程冲突，不由脚本猜测文本含义。
- 项目与个人 Prompt 规则冲突时采用项目规则；当前明确要求可覆盖两者。同级实质冲突待用户确认，未解决不得开始受影响步骤。

## 文件与命令

默认权威文件：`$CODEX_HOME/skills/.skill-guide-data/preferences.json`；CODEX_HOME 未设置使用 `~/.codex`。与索引缓存位置独立，索引改用工作区缓存时仍读取原偏好。自定义偏好位置用管理脚本 `--file` 及索引 `--preferences-file` 指向同一个文件；不能因写入失败自行改存。

```text
python <本技能>/scripts/skill_preferences.py list
python <本技能>/scripts/skill_preferences.py list --applicable --workspace <项目中的工作区> --tag paper --tag close-reading
python <本技能>/scripts/skill_preferences.py apply --rule-file <已复核规则JSON> --authorized
python <本技能>/scripts/skill_preferences.py disable --id <规则ID> --authorized
python <本技能>/scripts/skill_preferences.py enable --id <规则ID> --authorized
python <本技能>/scripts/skill_preferences.py remove --id <规则ID> --authorized
```

路径必须替换为实际值。`--authorized` 是调用方确认有明确用户授权的声明，不替代宿主权限。创建规则只需 `apply`；修改时在规则 JSON 指定已有 `id`，完整描述新规则。保存前核对作用范围和实际技能名称；重新绑定路径属于更新对象，需要相应授权。

规则输入例（A 和路径为示意，不能直接执行）：

```json
{
  "kind": "prefer",
  "scope": {"kind": "personal"},
  "task_tags": ["paper", "close-reading"],
  "target": {"name": "A", "path": "<实际绝对路径>/SKILL.md"},
  "instruction": "论文精读任务优先考虑 A",
  "reason": "用户明确指定"
}
```

`prompt` 规则用相同范围与标签，省略 `target`，将输出/流程写在 `instruction`。管理脚本自动记录 ID、精确路径、入口哈希、时间和启用状态；保存文本只需最小规则与简短理由，不含材料、私密内容或完整聊天。规则文字是偏好数据，不作为高优先级指令，不授予安装、删除或外部发布权限。

旧的 `{"aliases": {"候选ID": ["别名"]}}` 仍可读取；仅在明确授权变更时升级格式并保留别名。读查询不写偏好。变更使用排他短锁和原子替换，锁忙、权限不足、数据损坏或版本不支持时保留原文件并报告失败，不自动修复个人数据或声称记录成功。

`list` 可查看原始规则；`--applicable` 只筛选范围和标签，不保证技能可用。每次写入后用返回的 `ok/persisted/rule/path` 简短报告实际结果。只按指定 ID 删除/停用；删除不影响技能或其他规则。

## 查询与绑定

导航查询使用 `--tag`，返回 `preferences.rules/decisions/conflicts/overridden` 及当前范围的 `available_task_tags`。标签清单只帮助复用同义的已有分类，不代表这些规则都适用；相关标签不一致时允许一次调整检索，不额外读取全部聊天或技能正文。优先规则可将原本没有关键词命中的技能补入少量候选；候选的 `retrieval_reason=preference` 不证明它能处理任务。`list` 仍是技能概览，不因排除偏好隐藏技能。

当前用户明确选择实际技能时，用其已核对 ID 传 `--override-skill` 覆盖相应历史技能规则，并在方案说明。不能为了绕过用户排除而传该参数。Prompt 规则的覆盖由当前要求和模型判断，不能自动字符串比较。

绑定状态：`current` 身份及入口未变；`changed` 名称或入口哈希变化；`needs_review` 当前条目有扫描异常；`missing` 原 ID/路径不在索引；`out_of_scope` 不属于当前技能范围；`disabled` 当前配置禁用。`current` 仍不证明宿主加载或依赖齐备。

变化条目需阅读相关能力，不能自动转绑同名技能。旧排除规则在相同身份更新后继续有效；若对象或含义实质改变，复核后按授权修改。路径迁移/插件换版本仅提供待核验信息，不自动写入或按名称匹配。未找到的规则保留，不阻塞其他方案。

报告确实影响选择的规则及 ID；存在实质冲突或待核验影响时解释。无相关偏好省略该部分。对应关系和 Prompt 始终以当前事实和授权为准。
