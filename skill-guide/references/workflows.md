# 经授权保存的流程复用

流程记录描述“哪些阶段怎样衔接、在什么条件下适用”。偏好描述“通常更喜欢什么”。两者独立；当前任务要求优先，适用偏好可能使旧流程不再适合。创建此功能不授权自动收集历史或写入每次执行。

## 使用顺序与开销

1. 新导航增量刷新技能索引后，只读查看流程。文件缺失即无记录，不创建空文件。仅管理流程时不刷新无关索引。
2. 从当前任务提取标签、输入输出类型和确定的条件；匹配后只核对少量流程绑定的技能、配置与已跟踪资源。标签/类型是检索条件，不是语义适配证明；先核对硬约束，再看偏好。不读取全部技能正文。
3. 确认角色、工具可用性和材料适用性，替换本次材料及参数，说明复用来源与待检查事项，提交本次执行 Prompt。仍需用户确认。
4. 文件变化只核对受影响阶段；实质影响时更新对应关系和 Prompt。无关目录变化不要求全流程重做。同名技能、插件新目录不自动替代原绑定。

`query` 先用范围、标签、输入输出及已知条件排除不适用记录，再对一批最多 5 个候选核对绑定文件。已知条件冲突不占名额，也不读取绑定文件；重复的完整绑定指纹在同次查询中只检查一次。当前宿主明确不可用的技能不读取其文件。此限制控制文件核验量；流程 JSON 仍须读取并过滤，不能声称处理任意数量记录都耗时不变。

返回的 `query` 汇报匹配数、条件排除数、实际核验数及 `has_more/next_offset`。存在后续候选时，当前批次没有可用流程不等于没有适用流程：确有必要时用 `--offset <next_offset>` 再查一批；默认最多追加一批，仍未找到则说明检索范围，转入本地普通导航，用户要求后才扩大。翻页沿用同一份条件与技能集合；记录或条件变化时从头查询，不将偏移量当作稳定游标。可用 `--limit` 调整每批数量（1–20）。

历史 `confirmed` 仅表示方案确认过，`used` 表示实际使用过；两者都不证明本次任务一定成功。工具状态、数据质量及未跟踪资源仍需按需核验。

## 保存与最小数据

仅响应用户明确的“记住/更新这个流程”，保存已经确认或实际使用过的版本。范围含糊时先提出具体内容，清楚授权不重复问。只保存任务类别、范围、输入输出类型、必要约束/环境、阶段职责、精确技能指纹、已检查事项及局限。

不保存完整执行 Prompt、材料路径或内容、聊天、产物内容和失败日志。字符串字段只填通用流程摘要；结构校验不能自动识别写进摘要的隐私，调用者必须先检查最小化内容。任务确认、单次反馈或成功不自动授权持久化。

默认文件：`$CODEX_HOME/skills/.skill-guide-data/workflows.json`，未设置时使用 `~/.codex`。独立于索引缓存和 `preferences.json`，`--file` 指定唯一存储位置。损坏、不兼容版本、锁忙或不可写时保留原记录并报告，不改权限、不静默另存。查询失败继续普通导航，说明未能参考历史流程。

## 命令与数据

从技能目录运行，路径中的空格按当前 shell 引号规则处理：

```text
python scripts/skill_workflows.py list
python scripts/skill_workflows.py bind --path <已选SKILL.md> --resource references/相关说明.md
python scripts/skill_workflows.py query --context-file <本次查询JSON>
python scripts/skill_workflows.py query --context-file <同一本次查询JSON> --offset <next_offset>
python scripts/skill_workflows.py apply --recipe-file <已授权流程JSON> --authorized
python scripts/skill_workflows.py disable --id <流程ID> --authorized
python scripts/skill_workflows.py enable --id <流程ID> --authorized
python scripts/skill_workflows.py remove --id <流程ID> --authorized
```

`bind` 是只读快照，输出 target 对象；**在用户确认/实际使用时保留该快照**，保存时原样使用。不要先给旧流程换成新哈希再声称仍已确认。`--resource` 可重复，只跟踪会影响选择/交接的具体技能内文件；不全量哈希大型资源。SKILL.md 和存在的 agents/openai.yaml 自动跟踪。缺少配置以 null 绑定，后来新增配置同样算变化。

保存输入结构示例（把 target 替换为已核对的 bind 输出对象；只为实际已确认/使用的流程填写）：

```json
{
  "id":"paper-comparison",
  "name":"论文对比笔记",
  "scope":{"kind":"personal"},
  "task_tags":["paper-comparison"],
  "input_type":"pdf",
  "output_type":"markdown",
  "constraints":{"citations":"required"},
  "environment":{"pdf_tool":"available"},
  "stages":[
    {"kind":"skill","role":"读取论文并保留方法与结论来源",
     "input_type":"pdf","output_type":"markdown","target":"替换为bind输出的对象"},
    {"kind":"prompt","role":"按研究问题、方法与局限生成对比表并核对来源",
     "input_type":"markdown","output_type":"markdown","target":null}
  ],
  "evidence":{"status":"used","checked":"来源与输出结构已核对","limits":"本次新论文仍需检查证据与内容"}
}
```

项目范围改为 `{"kind":"project","path":"项目绝对路径"}`，适用范围含项目子目录，不能只靠字符串前缀判断。skill 阶段 target 必须含 `id/path/name/skill_hash/config_hash/resources`；由 bind 提供。prompt/tool 的 target 为 null，role 写实际职责和必要工具名称，其可用性由当前环境核验。

`id` 可省略以生成新记录；指定已有 ID 更新同一流程，保留创建时间和停用状态。记录只接受 `confirmed/used`；脚本仅校验调用者声明的状态，确认事实须由对话/执行证据建立。`--authorized` 表示调用者已获得相应用户授权，不绕过文件系统权限。apply 会拒绝与确认快照不一致的当前文件。

本次 query 输入所有字段如下：

```json
{
  "workspace":"当前工作区绝对路径",
  "task_tags":["paper-comparison"],
  "input_type":"pdf",
  "output_type":"markdown",
  "constraints":{"citations":"required"},
  "environment":{"pdf_tool":"available"},
  "active_skill_ids":["当前宿主可用且处于本次范围的实际技能ID"]
}
```

所有流程标签须匹配当前标签；输入输出类型和条件值精确匹配，不擅自补充无关标签。新任务额外硬约束仍须模型检查，不能因记录没写该约束就认定覆盖。active_skill_ids 从当前宿主与索引核对，不把文件存在当作启用证明；未知时设 null，返回待核验。

| 返回状态 | 使用方式 |
| --- | --- |
| eligible_for_review | 声明条件与绑定一致，仍检查实际适配并提交 Prompt |
| needs_review | 条件未知或文件变化，只核验相关阶段 |
| blocked | 对象缺失或不在当前可用集合；检查后续候选或另选方案 |

已知条件冲突在文件核验前排除，计入 `query.filtered_conditions`；`rejected_conditions` 仅返回至多一批数量的摘要，不能将其长度当作排除总数。未知条件保留为待核验，不自动视为满足。`semantic_validation=false` 适用于所有返回候选。

查询不改写记录、迁移绑定或执行任务。停用记录不参与检索，删除只影响指定记录。保存、更新和恢复启用不会替用户确认新的任务方案。
