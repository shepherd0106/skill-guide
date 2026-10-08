# skill-guide · Personal Skill Navigator

[简体中文](README.md) | **English**

**Turn your task into a skill selection and execution plan you can review.**

Installed many Skills but unsure which one to use, whether to combine them, or how to write the invocation prompt? `skill-guide` uses your task and locally available skills to recommend a single skill, a complementary combination, or a plan that needs no skill. It drafts an execution prompt, then carries out the version you have reviewed or revised and approved.

By default, it prioritizes **local Skills + a task-specific prompt + existing tools**. It suggests extending your capabilities only when a critical gap remains or the added capability has clear value.

Each recommendation maps critical task requirements to the responsible capabilities, their evidence, and any conditions still needing verification. Selection habits you explicitly ask it to remember can be saved as scoped local preferences for future matching tasks.

Combination plans also check whether each skill is necessary and whether stages can exchange their outputs. With your explicit request, confirmed or used workflows can be saved and reused to draft a new plan for review when their conditions match.

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

The navigator returns a **recommended plan, key requirement mappings, applied preferences, an execution prompt, and any essential points requiring confirmation**. The preference section is omitted when none are relevant. The prompt specifies the goal, input locations, deliverables, actual skill names, and invocation method. A combination also specifies the order, each stage's responsibilities, and handoff outputs.

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

## Traceable selection evidence

Recommendations map critical requirements to a skill, prompt, or existing tool. Simple tasks get a short explanation; complex tasks may use a table:

| Task requirement | Responsible approach | Evidence | Coverage and verification |
| --- | --- | --- | --- |
| Read local PDFs | Candidate skill A | The actual reading section in SKILL.md | Documented support; tool readiness needs checking |
| Compare methods, evidence, and limitations | A + the task prompt | Reading workflow + the user's comparison dimensions | Prompt adds dimensions; sources checked after execution |
| Chinese Markdown notes | The task prompt | General output capability and the requested format | No extra skill required |

A is an illustrative placeholder. Actual plans use real skill names and verified references. Documented support, pending conditions, verified behavior, and uncovered requirements are distinguished. Keyword matches, preferences, and a skill's own claims do not establish successful execution.

Similar skills are compared only on differences affecting the current deliverable. When a plan changes, its mappings and execution prompt are updated together. See [Requirement mappings](skill-guide/references/mapping.md).

## Inspect combinations and reuse workflows

| Feature | What it does | When it is used |
| --- | --- | --- |
| Combination necessity checks | Remove each skill in turn to see which critical requirements or downstream inputs lose support; reduce overlapping roles | When recommending multiple skills |
| Stage handoff checks | Compare formats, required fields, and source requirements; optionally check actual files, JSON top-level keys, or CSV headers without modifying them | When stages exchange artifacts or have explicit acceptance criteria |
| Authorized workflow records | Save conditions, stage roles, and file fingerprints for confirmed or used workflows; check them before reuse | After you explicitly ask to remember a workflow |
| Clarification based on actual differences | Ask one deciding question only when a verified difference between candidates changes the plan | When missing information affects the primary choice or combination |

For example, a reading skill may extract sources and claims before a task prompt builds a comparison table. The navigator checks whether those required fields are available and explains why the reading skill is needed. If a general prompt can reasonably satisfy the deliverable, the combination is reduced. Removal candidates are considered one at a time, with another check after each removal, so interchangeable alternatives are not all removed together.

A passed handoff check establishes the checked structural conditions; citations and conclusions still need specialist validation. The checks depend on the supplied mappings and contracts, and do not establish semantic correctness or an optimal plan. Simple tasks use short explanations; scripts are used on demand for complex plans, without creating check files for every message. See [Combination and handoffs](skill-guide/references/composition.md).

Example workflow requests:

```text
Remember the paper comparison workflow we just completed, for this project only:
PDF input, Markdown output, and preserved source references.
Show my saved workflows.
For these new papers, check for a suitable workflow and draft a fresh execution prompt.
Disable the paper comparison workflow; keep the other records.
```

Workflows and preferences are stored separately in local workflows.json and preferences.json files. Workflow records contain general summaries and necessary conditions, excluding full prompts, conversations, task materials, and material paths. Current requirements and applicable preferences take precedence. Mismatched types or conditions lead to a different plan; unknown conditions or changed files require checks of affected stages. Same-named skills do not automatically replace a binding. Reuse still requires review of the current prompt, and one successful use is not a guarantee of future results.

Workflow queries check at most five matching records' bound files by default, expanding only when needed. They do not automatically learn, save, or execute new tasks. See [Workflow reuse](skill-guide/references/workflows.md).

## Preferences saved with your authorization

Supported rules include prefer, avoid where possible, explicitly exclude, and output or workflow preferences. They can be scoped to a project or a task category:

```text
Remember: prefer skill A for close-reading papers.
Remember: in this project, use Markdown tables for comparison notes by default.
Show my saved navigation preferences.
Disable the rule we just saved; keep the other rules.
```

The actual skill and scope are checked before saving. Ambiguous scope is submitted for review. “Use A this time” affects the current task only; “Prefer A in this conversation” stays in the conversation. A single failure does not automatically become a lasting exclusion. Clear authorization to save a rule is acted on without repeated confirmation, and the result is reported.

Current explicit instructions take precedence over historical preferences; project rules take precedence over applicable personal rules. Substantive conflicts at the same level require review. Preferences can nominate candidates, but candidates must still meet task requirements and actual conditions. Rules bind exact skill paths; updates and migrations are checked rather than automatically transferring rules to same-named skills.

Rules remain in a local preferences.json separate from the index. You can view, revise, disable, or remove specific rules. Only minimal rules and brief reasons are stored, excluding full conversations and task materials; personal data is not published with the repository. Write failures are reported and preserve the original file. See [Preference management](skill-guide/references/preferences.md) for commands and scope matching.

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
├── scripts/skill_preferences.py # Scoped preference management
├── scripts/skill_plan.py    # Removal analysis and read-only artifact checks
├── scripts/skill_workflows.py # Authorized workflow storage and retrieval
└── references/
    ├── index.md             # Index commands, scope, and fallback handling
    ├── mapping.md           # Requirement-to-capability mappings
    ├── preferences.md       # Preference authorization, scope, and changes
    ├── composition.md       # Necessity, stage contracts, and deciding questions
    ├── workflows.md         # Workflow records, conditions, and reuse
    └── extension.md         # External capability evaluation and packaging scope
```

[`SKILL.md`](skill-guide/SKILL.md) defines the full behavior. The skill instructions and reference documents are currently written in Chinese. Users' index caches, preferences, and workflow records remain local and are excluded from the published skill package.

Development checks: run `python -m unittest discover -s tests -p "test_skill*.py" -q` from the repository root. Tests verify helper behavior; actual task content still needs acceptance checks.
