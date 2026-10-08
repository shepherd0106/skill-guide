# 组合必要性与阶段交接

仅为多技能组合、有真实交接疑问或明确验收要求的任务展开；简单单技能任务用短句即可，不强制建立 JSON 文件。先读真实技能，再填写对应关系和契约。脚本只核对调用者填写的数据，不推断技能能力。

## 去掉一个技能会怎样

对当前小规模方案逐项检查：去掉这个技能后，关键要求是否仍有充分负责方式？其下游阶段是否会因缺少输入而失效？普通 Prompt 或现有工具能否合理替代？

- 有独特关键支持或必要上游产物时保留，写清损失的要求。
- 没有损失时作为删除候选，由模型核对证据后调整方案。**一次只去掉一个再重新检查**，不能同时删除互为备选的全部技能。
- 仅剩待核验支持时先核验，不称为充分覆盖。已经存在的缺口单独列出，不归因于刚删除的技能。
- 必要性只针对已检查的当前方案，不证明全局最优。不把补充要求虚构成“关键要求”来保留技能。
- 用户指定技能而建议减少它时，说明原因并保留待复核版本，不静默替换。

较复杂方案可用 `skill_plan.py review --plan <本地JSON>`。以下是完整的最小输入示例，阶段顺序就是执行顺序：

```json
{
  "stages": [
    {"id":"read","kind":"skill","name":"实际技能名称",
     "inputs":[{"from":"$material","contract":{"format":"pdf","fields":[]},"adapter":null}],
     "output":{"format":"json","fields":["source","claim","limitations"]}},
    {"id":"compare","kind":"prompt","name":"按任务维度对比",
     "inputs":[{"from":"read","contract":{"format":"json","fields":["source","claim"]},"adapter":null}],
     "output":{"format":"markdown","fields":["comparison","citations"]}}
  ],
  "requirements": [
    {"id":"来源可追溯","critical":true,"providers":[
      {"stage":"compare","evidence":"本次Prompt保留读取阶段的来源字段","status":"documented"}]}
  ]
}
```

示例不是任何实际技能的能力声明。正式方案的 evidence 写实际文件、章节或工具依据。providers 中多项表示**替代负责方式**；需要协同才能满足的要求，应拆成各项必要要求，或用一个依赖所需上游阶段的最终负责阶段表达，不能把协同误写成替代。

`kind` 为 `skill/prompt/tool`；证据状态为 `documented/verified/pending`。每个 input 是必要输入，只能引用 `$material` 或此前的阶段，不能用可选输入虚构依赖；分支替代方案分别检查。最多 12 阶段，不做全量组合枚举。

返回 `uncovered/pending` 及逐技能删除结果：`necessary_in_matrix` 是矩阵内必要、`removal_candidate` 待核对后精简、`needs_review` 涉及未核验支持。检查命令成功只表示输入合法并完成结构分析；`ok:true` 不表示方案可执行。

## 输入输出契约

只记录会影响交接的格式、字段及其语义、来源/单位/粒度、材料位置、工具前提和验收条件。正式执行 Prompt 必须说明语义条件；脚本只处理 format 与 fields。

交接结果：

| 状态 | 含义与动作 |
| --- | --- |
| direct | 声明的格式相同、所需字段齐全；还需检查实际内容与来源 |
| adapter_required | 声明不兼容但提出了适配；先验证适配是否保留必要信息 |
| unknown | 用户材料或契约未知；核对实际输入，不推断可用 |
| incompatible | 格式/字段不满足且无适配；调整方案后复核 |

格式字符串和字段名精确匹配；`unknown` 表示未知格式，不能以空字段伪装已知支持。适配只允许本次授权范围内的小规模转换；脚本不执行 adapter 文本或任意命令。写“转换一下”不会自动消除能力缺口。

执行到交接点，按需使用只读检查：

```text
python scripts/skill_plan.py check --path <产物路径> --format file
python scripts/skill_plan.py check --path <产物路径> --format json --field source --field claim
python scripts/skill_plan.py check --path <产物路径> --format csv --field source --field claim
```

JSON 要求顶层对象与指定顶层键；CSV 检查表头；file 仅检查普通文件存在与大小。最大读取 2 MB，超限返回 `size_limit`，按需另用现有工具做有界检查。不会上传文件或保存内容。字段齐全不证明非空、类型/单位正确、引用真实或结论可靠；这些由专业流程验收。

## 基于真实差异的关键追问

先比较候选实际支持的输入、交付和前提。只有缺失答案会改变首选、组合、成本或授权范围时才问；优先问一个能分开候选的问题，并说明选择如何改变方案。例如已核实 A 输出可编辑演示文稿、B 只输出 PDF，此时询问是否必须编辑，答案将决定首选。

若用户已要求可编辑输出，或适用偏好已明确这一点，直接使用，不重复问。答案不影响选择时省略问题。未知关键前提保留待核验，不用一串一般性问题代替调查，也不编造量化“信息增益”。
