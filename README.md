# skill-guide · 个人技能导航

根据任务和本地已有技能，推荐单个技能、互补组合或无需技能的方案，生成执行 Prompt，经过用户复核后再执行。

## 工作方式

- 优先使用本地 Skill、任务 Prompt 和现有工具。
- 相似技能选择一个首选；只有不同的必要能力才组合。
- 不需要 Skill 时直接说明，并提供直接处理的 Prompt。
- 仅在存在关键能力缺口或明确值得准备成本时，提出外部检索、项目适配或新增 Skill 建议。
- 使用本地增量索引，只读取变化的入口元数据，按需检查候选说明。
- 不修改全局指引，不建立常驻进程，不自动联网或安装技能。

## 安装与调用

技能目录为 [`skill-guide/`](skill-guide/SKILL.md)。可使用 Codex 的 `skill-installer`，指定本仓库及 `skill-guide` 路径安装；也可以将该目录复制到个人技能目录。

```text
请使用 $skill-guide，为下面的任务选择合适的本地技能或直接处理方案：
【任务说明、已有材料、期望输出】
先生成执行 Prompt，等我确认后再执行。
```

确认执行当前方案时回复“确认执行”；仅提出修改意见时会先更新 Prompt。“按以下修改版执行”会直接执行修改版本。

索引助手需要 Python 3.11+，仅使用标准库，无需额外 Python 包。缓存独立于技能包，默认保存在 `$CODEX_HOME/skills/.skill-guide-data/`（未设置 CODEX_HOME 时使用 `~/.codex`）。当前有效插件根目录由调用方提供，不能把所有历史插件版本当作可用技能。

## 文件

```text
skill-guide/
├── SKILL.md
├── agents/openai.yaml
├── scripts/skill_index.py
└── references/
    ├── index.md
    └── extension.md
```

索引操作和缓存降级见 [index.md](skill-guide/references/index.md)；外部能力扩展规则见 [extension.md](skill-guide/references/extension.md)。

自动匹配不能保证每次触发；需要稳定经过导航时请主动指定。索引加速不代表整个任务具有固定耗时，实际推荐质量仍需通过使用验证。
