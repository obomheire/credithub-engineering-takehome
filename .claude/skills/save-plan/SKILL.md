---
name: save-plan
description: "Save an implementation plan (single or split into multiple independent plans) to .claude/plans/ so it can be implemented in a separate conversation. Each plan carries enough context for a fresh model to implement it without prior discussion."
argument-hint: "[split] — omit for a single plan, pass 'split' to break the plan into multiple independent plans"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
---

<objective>
Capture the current implementation plan — including all context from the conversation that produced it — and write it to `.claude/plans/` (repo-local) as one or more Markdown files. Each saved plan must be fully self-contained: a fresh model that has never seen this conversation must be able to open the file and implement the task without needing to ask any follow-up questions about requirements, decisions, or architecture.

If `$ARGUMENTS` is `split`, decompose the plan into multiple independent sub-plans that can be implemented in parallel by separate models. Otherwise, save a single consolidated plan.

There are two plan locations involved, and they play different roles:

- **`~/.claude/plans/`** (home directory, global) — where Claude Code's own plan mode (`ExitPlanMode`) already saved the **original full plan** when the user approved it in this conversation. This skill does not create this file — it already exists by the time this skill runs.
- **`.claude/plans/`** (repo-local) — where this skill writes the **implementation file(s)**: one self-contained plan (single mode) or several independent sub-plans (split mode), derived from the original full plan plus everything discussed since.

Every repo-local file this skill writes must reference the original full plan's path in `~/.claude/plans/`. The original full plan, in turn, gets a **Completion tracker** checklist appended to it (or updated, if one already exists) — one checkbox per repo-local plan/part — which each implementing model checks off with an implementation status note after it finishes and verifies its piece. The feature is done when every box in the original full plan is checked.

Output directories: `.claude/plans/` (repo-local, new files) and `~/.claude/plans/` (home directory, in-place edit to append/update the completion tracker on the existing original plan file)
</objective>

<context>
Argument: $ARGUMENTS

Project: Loopscribe V2 API — NestJS monorepo at the repo root.
- `apps/api` — REST API (Fastify, port 9000), global prefix `api/v1`
- `apps/realtime` — WebSocket service (Socket.io, port 9001)
- `apps/workers` — BullMQ background job processor
- `libs/shared` — Drizzle ORM schema + queue constants
- `libs/config` — Zod-validated env schema
- `libs/redis` — ioredis client
- `libs/ai` — Gemini script provider (`SCRIPT_PROVIDER` token)
- Repo-local plans directory: `.claude/plans/`
- Global plan-mode directory: `~/.claude/plans/`
</context>

<process>

## Step 0 — Determine mode

Read `$ARGUMENTS`:
- If empty or absent → **single plan mode**: write one `.claude/plans/<slug>.md` file.
- If `split` → **split mode**: decompose into 2–5 independent sub-plans, each written as a separate file.

---

## Step 0.5 — Locate the original full plan in `~/.claude/plans/`

Before writing anything, find the original plan file that Claude Code's plan mode saved for this conversation:

```bash
ls -t ~/.claude/plans/*.md | head -5
```

The most recently modified file is almost always the one for the current conversation (plan mode writes it at the moment the user approves the plan, immediately before this skill runs). Sanity-check it by reading its title/opening section and confirming it matches the feature being saved right now.

- If the most recent file's content clearly matches the current conversation's plan → use it.
- If it's ambiguous (e.g. its content doesn't match what was just discussed, or the file is stale/old) → ask the user which file in `~/.claude/plans/` is the original plan for this task before proceeding. Do not guess.
- If no plan-mode file exists at all (e.g. this skill is being run without having gone through plan mode) → tell the user no original plan was found in `~/.claude/plans/` and ask whether to proceed without a back-reference or point to the correct file.

Record this file's absolute path (e.g. `~/.claude/plans/glimmering-mixing-gray.md`) — every repo-local file written in Step 2/3 must reference it, and it is the file that receives the Completion tracker in Step 3.5.

---

## Step 1 — Synthesise the plan from the conversation

Before writing anything, synthesise the following from the current conversation:

### 1a. What was built / decided

Reconstruct the full picture of what needs to be implemented:
- The feature or change being made
- Why it is being made (the user need or product requirement it addresses)
- Every endpoint, job, schema change, DTO, or service method that is new, modified, or removed
- Any alternatives that were considered and rejected (and why)

### 1b. Key decisions and their rationale

List every non-obvious decision that was made during the conversation:
- Data model choices (e.g. flat array vs. JSONB, which table to use)
- API shape choices (e.g. 201 vs. 202, optional vs. required fields)
- Integration choices (e.g. reuse existing job type vs. new type, WebSocket vs. polling)
- Anything the user explicitly chose between two options

For each decision, record: **what** was chosen and **why** (the reason the user gave, or the agreed rationale).

### 1c. Exact files to change

List every file that needs to be created, modified, or deleted. For each:
- Full path from repo root
- Whether it is new, modified, or deleted
- What specifically changes (new method, new field, removed route, etc.)

### 1d. Implementation order

Identify the dependency order. List steps sequentially so each step's inputs exist before it is needed. Flag steps that can be done in parallel.

### 1e. Verification

List the exact curl commands, DB queries, or test steps that confirm the implementation is correct. Include expected outputs.

---

## Step 2 — Single plan mode

Write **one file** to `.claude/plans/<kebab-case-feature-name>.md` using the template below. Fill every section — do not leave placeholders.

---

### Single plan template

```markdown
# Plan: <Feature Name>

## For the implementing model — read this first

This plan was produced in a prior conversation. You were not part of that conversation.
Read this entire file before touching any code. Every decision has already been made —
your job is to implement, not re-design.

**Original full plan:** `~/.claude/plans/<original-plan-filename>.md` — this file is a
self-contained implementation plan derived from that original. If you want the full
narrative context behind a decision, that file has it. It also has this task's entry in
its Completion tracker.

If anything in this plan contradicts what you observe in the current codebase (e.g. a
file was renamed, a method was removed), use what you observe in the codebase and note
the discrepancy — do not fail silently.

**When you finish implementing and have verified the work (see Verification section),
open `~/.claude/plans/<original-plan-filename>.md` and check this task's box in its
Completion tracker section by changing `[ ]` to `[x]`. That file — not this one — is the
source of truth for whether the feature is complete.**

## Why this change is being made

<1–3 sentences explaining the product need or user problem this solves.>

## What was discussed and decided

<Narrative summary of the conversation: what options were on the table, what the user
chose, and why. Written as prose so the implementing model understands intent, not just
mechanics. 100–300 words.>

## Key decisions (non-obvious choices made during the conversation)

| Decision | Choice made | Reason |
|---|---|---|
| <topic> | <what was chosen> | <why — the user's reasoning or agreed rationale> |

## Architecture overview

<Brief description of how the new code fits into the existing system. Mention which
existing services, queues, DTOs, or DB tables are involved and how they connect.>

## Files to create / modify / delete

| File | Action | What changes |
|---|---|---|
| `path/to/file.ts` | CREATE / MODIFY / DELETE | <specific description> |

## Implementation steps (in order)

### Step N — <title>

**File:** `path/to/file.ts`

<What to do. Be specific enough that no design decisions remain. Include field names,
method signatures, validation rules, error messages, DB operations, and queue job names.
Reference existing patterns in the codebase where they apply.>

Code sketch (where helpful):
\`\`\`typescript
// key types / method signatures / DTO shape
\`\`\`

*(Repeat for each step)*

## Steps that can be done in parallel

<List any steps that have no dependency on each other and can be implemented simultaneously.>

## Verification

### <scenario name>
\`\`\`bash
# command
# expected output
\`\`\`

*(Cover: happy path, error cases, removed endpoints returning 404, services starting cleanly)*

## Known gotchas

<Any non-obvious things the implementing model should watch out for: DI registration
requirements, NestJS route ordering issues, Drizzle migration rules, etc.>
```

---

## Step 3 — Split plan mode

Only enter this mode when `$ARGUMENTS` is `split`.

### 3a — Identify split boundaries

Decompose the plan into 2–5 independent sub-plans. A valid split boundary exists when:
- The work involves different files/services with no shared write conflict
- Sub-plan A does not need the output of sub-plan B to compile or run
- Each sub-plan can be implemented, verified, and merged independently

Common valid splits for this codebase:
- **API layer** (controller + service + DTOs) vs. **Worker layer** (processor changes)
- **Realtime gateway** changes vs. **REST API** changes
- **DB schema + migration** vs. **application code that uses the schema**
- **New feature** vs. **removal of deprecated endpoints**

Do not split if the pieces are too tightly coupled — a single plan is better than two plans that must be merged simultaneously to compile.

### 3b — Write an index file

Write `.claude/plans/<feature>-index.md`. This is a short routing file — it lists all sub-plans, their order/parallelism, and any integration notes (e.g. "sub-plan B depends on the DB migration from sub-plan A being applied first"), and points to the original full plan. It is **not** where completion is tracked — that lives in the original full plan in `~/.claude/plans/` (Step 3.5).

```markdown
# Index: <Feature Name>

**Original full plan:** `~/.claude/plans/<original-plan-filename>.md` — read this for full
narrative context and to check off completion. This index just lists and orders the parts.

This feature is split into <total> independently implementable sub-plans:

| Part | File | Scope | Dependencies | Can run in parallel with |
|---|---|---|---|---|
| 1 | `.claude/plans/<feature>-part-1-<slug>.md` | <what it covers> | none | Part 2 |
| 2 | `.claude/plans/<feature>-part-2-<slug>.md` | <what it covers> | Part 1 migration applied | Part 1 |

## Integration notes

<Anything a part needs to know about how it connects to the others: shared types, queue
names, DB columns another part will read, etc.>

## Completion

Tracked in `~/.claude/plans/<original-plan-filename>.md` under "Completion tracker" — one
box per part. The feature is done when every box there is checked.
```

### 3c — Write each sub-plan

Write each sub-plan as `.claude/plans/<feature>-part-<N>-<slug>.md` using the same single-plan template from Step 2, with these additions in the header (in place of the single-plan template's "Original full plan" line):

```markdown
## Part <N> of <total> — <Sub-plan title>

**Original full plan:** `~/.claude/plans/<original-plan-filename>.md` — read for full
narrative context; this task's box in its Completion tracker is what you check off below.
**Index:** `.claude/plans/<feature>-index.md`
**Dependencies:** <list other sub-plan files this depends on, or "none">
**Can run in parallel with:** <list other sub-plan files, or "none">

**When you finish implementing and verifying this part (see Verification section below),
open `~/.claude/plans/<original-plan-filename>.md` and check the box for Part <N> in its
Completion tracker section by changing `[ ]` to `[x]`. Do not mark any other part's box.
The feature is complete only when all boxes in that file are checked.**
```

Each sub-plan must be fully self-contained — do not write "see sub-plan A for context" for requirements or design. Repeat any shared context that the implementing model needs. The only things a sub-plan defers elsewhere for are: full narrative context (original plan) and the cross-part completion checklist (also the original plan).

---

## Step 3.5 — Append the Completion tracker to the original full plan

This step applies to both modes (single and split) and is what makes completion trackable at all — do not skip it.

Open the original full plan file located in Step 0.5 (`~/.claude/plans/<original-plan-filename>.md`) and:

1. Check whether it already has a `## Completion tracker` section (e.g. from a prior run of this skill on the same plan, such as when new phases were added later). If so, update it — add any new entries, don't duplicate existing ones, and never uncheck a box that's already `[x]`.
2. If it doesn't have one, append a new section at the end of the file:

**Single plan mode:**
```markdown

## Completion tracker

Implementation plan: `.claude/plans/<filename>.md`

- [ ] **<Feature Name>** — implemented and verified
```

**Split plan mode:**
```markdown

## Completion tracker

Index: `.claude/plans/<feature>-index.md`

- [ ] Part 1 — <Sub-plan 1 title> (`.claude/plans/<feature>-part-1-<slug>.md`)
- [ ] Part 2 — <Sub-plan 2 title> (`.claude/plans/<feature>-part-2-<slug>.md`)
<!-- one line per sub-plan -->

The feature is complete only when every box above is checked. Each implementing model
checks off its own part after implementing and verifying it — never another part's box.
```

Use the Edit tool (not Write) so the rest of the original plan file is preserved untouched.

---

## Step 4 — Choose a filename

Generate a kebab-case slug from the feature name. Keep it short and descriptive.

Examples:
- `semi-automated-show-creation.md`
- `reading-progress-websocket.md`
- `author-ingestion-webhook.md`

For split plans:
- `semi-automated-show-creation-index.md`
- `semi-automated-show-creation-part-1-api-layer.md`
- `semi-automated-show-creation-part-2-worker-layer.md`

---

## Step 5 — Write the file(s)

Ensure `.claude/plans/` exists (create it if not). Write the repo-local plan file(s) there. Then perform Step 3.5 (Edit, not Write) against the original file in `~/.claude/plans/`. Do not write new files anywhere else.

After writing, output a short confirmation to the user:

**Single plan:**
```
Plan saved: .claude/plans/<filename>.md
Original full plan updated: ~/.claude/plans/<original-plan-filename>.md (Completion tracker added)

Open the repo-local file in a new conversation and tell the model to implement it.
When done and verified, it checks off its box in the original plan's Completion tracker.
```

**Split plan:**
```
Plans saved:
  .claude/plans/<feature>-index.md          (read this first — order & dependencies)
  .claude/plans/<feature>-part-1-<slug>.md
  .claude/plans/<feature>-part-2-<slug>.md
  ...
Original full plan updated: ~/.claude/plans/<original-plan-filename>.md (Completion tracker added)

Each part can be implemented independently in a separate conversation.
Each implementing model checks off its part's box in the original plan's
Completion tracker once that part is implemented and verified.
The feature is done when every box there is checked.
```

---

## Quality checklist — verify before writing

Before writing the file, confirm every item:

- [ ] The original full plan file in `~/.claude/plans/` was located (Step 0.5) and confirmed to match this task, or the user was asked to disambiguate
- [ ] The "Why this change is being made" section answers the product need, not just the technical task
- [ ] Every decision from the conversation is captured in the decisions table with a reason
- [ ] Every file to be changed is listed with a specific description of what changes
- [ ] No step says "implement X" without specifying field names, method signatures, validation rules, or error messages
- [ ] The verification section has runnable curl commands with expected outputs
- [ ] The "Known gotchas" section captures anything that tripped up the conversation (e.g. NestJS DI registration, route ordering, Drizzle migration rules)
- [ ] A fresh model reading only this file could implement the task without asking any clarifying questions
- [ ] Every repo-local file (single plan, or each sub-plan + index) references the original full plan's path in `~/.claude/plans/`
- [ ] The original full plan in `~/.claude/plans/` has been updated (via Edit, preserving its existing content) with a "Completion tracker" checklist — one box per phase/part, not duplicated if one already existed
- [ ] Every repo-local file explicitly instructs the implementing model to check its box in the original plan's Completion tracker after implementing and verifying — never another part's box

If any item fails, fix the plan content before writing the file.

</process>
