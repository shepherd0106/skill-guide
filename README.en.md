# skill-guide · Personal Skill Navigator

[简体中文](README.md) | **English**

**Turn your task into a skill selection and execution plan you can review.**

Installed many Skills but unsure which one to use, whether to combine them, or how to write the invocation prompt? `skill-guide` uses your task and locally available skills to recommend a single skill, a complementary combination, or a plan that needs no skill. It drafts an execution prompt, then carries out the version you have reviewed or revised and approved.

By default, it prioritizes **local Skills + a task-specific prompt + existing tools**. It suggests extending your capabilities only when a critical gap remains or the added capability has clear value.

## Quick start

### 1. Install

In a Codex environment with `skill-installer`, send:

```text
Please use $skill-installer to install the skill from the skill-guide directory
in https://github.com/shepherd0106/skill-guide.
```

Alternatively, download this repository and copy the entire inner [`skill-guide/`](https://github.com/shepherd0106/skill-guide/tree/main/skill-guide) folder into your environment's personal skills directory. Keep the script, `agents/`, and `references/`; copying only `SKILL.md` is insufficient. If a skill with the same name already exists, compare versions before updating it.

The index helper requires **Python 3.11+** and uses only the standard library. No additional Python packages are needed. After installation, check that your host recognizes `skill-guide`.

### 2. Describe your task

Explicitly invoke `$skill-guide` and provide the goal, inputs, and expected output where possible:

```text
Please use $skill-guide to recommend suitable local skills or a direct approach
for the following task.

Goal: [The problem to solve]
Inputs: [File locations, links, or content already provided]
Deliverable: [Expected output and acceptance criteria]
Constraints: [Time, environment, format, or scope; omit if none]

Explain the recommendation and draft an executable prompt.
Wait for my review before executing it.
```

For example:

```text
Please use $skill-guide.
I have three local PDF papers. Compare their research questions, methods,
evidence, and limitations in a Chinese-language note, citing the source
for each conclusion.
Select suitable local skills and draft an execution prompt first.
Wait for my confirmation.
```

### 3. Review, then execute

The navigator returns a **recommended plan, an execution prompt, and any essential points requiring confirmation**. The prompt specifies the goal, input locations, deliverables, actual skill names, and invocation method. A combination also specifies the order, each stage's responsibilities, and handoff outputs.

| Your reply | What happens next |
| --- | --- |
| “Confirm execution” or “Execute this version” | Execute the clearly identified current plan |
| Revision feedback only | Update the prompt and wait for review |
| “Execute the following revised version” with your changes | Execute the revised version directly |

After an explicit navigation request, even a recommendation to use no skill is submitted as a prompt for review. Once approved, the actual task is executed. Only substantive changes to the goal, scope, skill combination, or critical availability conditions require review of the affected parts.

## How Skills are selected

| Task situation | Recommendation |
| --- | --- |
| General capabilities and existing tools are sufficient | Explain that no skill is needed and provide a prompt for direct execution |
| One skill meets the main deliverable requirements | Recommend one primary skill |
| Different stages require distinct essential capabilities | Recommend a complementary combination with clear responsibilities |
| Several skills have similar functions | Select one primary option; offer a few alternatives only when meaningful tradeoffs exist |
| The local approach has a critical capability gap | Explain the gap and propose a bounded extension |

Selection considers task fit, input/output compatibility, current availability, preparation costs, and your stated preferences. Small differences are handled in the task prompt where possible, avoiding combinations of skills with overlapping responsibilities.

Skills and products you explicitly specify are preserved. If they are unsuitable or unavailable, the navigator explains why and proposes alternatives. A skill being unselected is not evidence that it should be deleted.

## Lightweight indexing and directory changes

Each new navigation request checks the current skill directories and maintains a local index mapping skill names to descriptions and entry locations:

1. **Incremental refresh:** Check known directories and entry files for changes, usually rereading only changed entry metadata.
2. **Read on demand:** Retrieve a small shortlist, then read the full instructions for the primary option and necessary alternatives. Supporting resources are checked as needed.
3. **Verify before execution:** Recheck the selected skills' current content and configuration to avoid executing from outdated instructions.

All entry files are verified when the index is first built, on the first invocation after seven days, or when a full refresh is requested manually. Plugin discovery uses the active versions supplied by the current host, avoiding historical cache versions.

The default cache is `$CODEX_HOME/skills/.skill-guide-data/`, or `~/.codex/skills/.skill-guide-data/` when `CODEX_HOME` is unset. The cache is separate from the skill package and stores skill metadata only, excluding task materials and conversations. A writable workspace cache location can be specified. If the cache is unwritable or its lock is busy, the helper falls back to an in-memory refresh.

Retrieval uses keywords; final selection depends on the skill instructions and current environment. With no matches, the navigator tries other terms or a concise listing. Discovering a file does not establish that the host has enabled it or that its tools and dependencies are ready. Indexing reduces repeated reads; actual time still depends on directory size, the environment, and task complexity.

See [Index operations](skill-guide/references/index.md) for commands, scan scope, and error handling.

## When to consider a new skill

First try existing Skills, prompts, complementary combinations, and available tools. An extension is worth proposing when:

- A critical requirement cannot reasonably be met by the local approach.
- The new capability clearly eliminates substantial repetitive work, justifying discovery, adaptation, installation, validation, and maintenance costs.
- A stable, recurring workflow is worth packaging for reuse.

Candidates may be existing Skills or GitHub projects that have not yet been packaged as skills. Their capabilities and dependencies are reviewed before proposing direct use, limited adaptation, or packaging. Unverified candidates are not labeled ready to use.

External searches, downloads, installations, or skill creation require the corresponding authorization. Missing tools, dependencies, data, or permissions are identified separately; adding a Skill does not automatically supply them. See [External capabilities and packaging](skill-guide/references/extension.md) for the detailed rules.

## Invocation and scope

Explicitly specify `$skill-guide` when you want navigation reliably included in the workflow. Description-based matching may trigger it automatically, but cannot guarantee that every professional task starts with navigation.

To reduce the chance of forgetting it, you can add a conversation-specific instruction at the start of a chat:

```text
In this conversation, when a task needs a professional workflow selected first,
use $skill-guide to draft a plan and execution prompt, then wait for my review.
Handle simple tasks directly. Reuse the current plan for additional materials,
confirmation, and continued execution.
```

This is an agreement within the conversation; its effectiveness depends on the host and context. The skill does not modify global instructions, create a persistent background process, or run extra navigation for every message.

Navigation plans follow current host instructions, specialist skill requirements, and user authorization. Approving a task does not automatically expand permission to install, delete, publish, or change configuration.

## Repository structure

```text
skill-guide/
├── SKILL.md                 # Navigation rules and review workflow
├── agents/openai.yaml       # Host display and invocation metadata
├── scripts/skill_index.py   # Local indexing and candidate retrieval
└── references/
    ├── index.md             # Index commands, scope, and fallback handling
    └── extension.md         # External capability evaluation and packaging scope
```

[`SKILL.md`](skill-guide/SKILL.md) defines the full behavior. The skill instructions and reference documents are currently written in Chinese. Users' index caches and personal preferences remain local and are excluded from the published skill package.
