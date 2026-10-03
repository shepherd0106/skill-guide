# 本地索引操作

## 调用

使用宿主可用的 Python 3.11+；脚本只用标准库，不联网。下面的 `python`、脚本位置、工作区和根目录需要替换为当前环境中的真实值，不猜测路径。

```text
python <本技能>/scripts/skill_index.py query --workspace <当前工作区> --root <当前有效插件的skills目录> --terms "pdf document 报告" --limit 5
python <本技能>/scripts/skill_index.py list --workspace <当前工作区> --root <当前有效插件的skills目录>
python <本技能>/scripts/skill_index.py check --id <候选ID> --root <当前有效插件的skills目录>
python <本技能>/scripts/skill_index.py check --path <候选SKILL.md的路径> --root <当前有效插件的skills目录>
python <本技能>/scripts/skill_index.py refresh --full --workspace <当前工作区> --root <当前有效插件的skills目录>
```

`--root` 可重复，指技能集合根目录或一个含 SKILL.md 的技能目录。每轮从当前宿主技能路径推导有效插件根目录；不复用旧插件版本作为已启用证据。`--root` 只证明发现范围，不证明宿主已启用它。

默认根目录：`$CODEX_HOME/skills`（未设置则 `~/.codex/skills`）、其 `.system`、`~/.agents/skills`，以及当前工作区到最近 Git 根之间的 `.agents/skills`、`.codex/skills`。不在 Git 项目时只检查当前工作区。集合只枚举下一层技能目录，不递归扫描整包；系统目录另行枚举。当前宿主其他位置用 `--root` 补充。

默认缓存：`$CODEX_HOME/skills/.skill-guide-data/skills-index.json`（CODEX_HOME 未设置时使用 `~/.codex`）。隐藏数据目录独立于技能包，不含 SKILL.md，不作为技能安装；这样创建缓存只需个人技能目录的写权限。仅保存技能元数据，不保存任务、材料或聊天。`--cache-dir` 可以指定工作区内可写位置；不得为更新缓存自动修改权限。索引不可写或锁忙时保留旧缓存，并降级为内存刷新；首次也可在内存查询。`check` 只读。

未能持久化索引时，保留候选返回的 `content_hashes`，执行前用 `check --path` 返回当前哈希并比较。`content_changed=null` 表示没有缓存基线，不代表没有变化；配置和作用范围同时以当前检查结果核对。

可选 `preferences.json` 与索引独立：

```json
{"aliases":{"候选ID":["中文别名","英文检索词"]}}
```

只有用户明确要求才写入偏好。别名辅助检索，不替代技能能力说明。没有偏好文件也能工作。

## 结果与可信度

索引唯一 ID 来自规范化入口路径；同名不同路径保留，同一真实路径合并来源上下文。记录原始描述、可选检索别名、入口及 UI 元数据的 stat/hash、启用配置证据、有效范围和异常。初始列表缺失不能证明禁用。

脚本识别常见 YAML 字符串及折叠描述；复杂 YAML 标为待核验，不猜测。中文检索遇到主要英文描述时补英文能力词。结果排序只是字面命中，不表示胜任概率；零命中时换词或看清单。

`query/list/refresh` 每次枚举已知目录并检查入口和 openai.yaml 的时间/大小，只读取变化内容；首次建索引或七天后首次调用时检查所有入口哈希。`--full` 强制校验。正文外资源不全扫，实际选用时按需检查。执行前 `check` 对选中入口、UI、当前启用配置重新核验。

扫描异常保留相应旧条目并标为 stale，不按删除处理。根目录正常扫描后确认不存在的条目从当前索引移除；不删除磁盘文件。无关范围的旧条目不进入当前检索。

使用排他短锁和同目录临时文件原子替换。锁忙立即降级，不长时间等待；崩溃残留锁只在确认无刷新进程后手动清理。损坏缓存重新构建并报告，不把损坏当作无技能。

候选内容变化不必一律重新确认：读变化内容，只有任务能力、约束、可用性或范围受到实质影响才更新方案。`availability=unknown` 是待核验，不是不可用；依赖是否具备仍由实际任务检查。
