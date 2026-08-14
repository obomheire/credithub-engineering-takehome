---
name: handoff
description: "Write a comprehensive handoff document to .claude/handoffs/ so a fresh conversation can continue the current implementation without losing any context — requirements, what was implemented, what was verified, what was found broken, and exactly what to do next. Use when the conversation is running low on context, when work must pause and resume later, or when the user explicitly asks to hand off, continue elsewhere, or start a new thread."
argument-hint: "[optional: short slug or focus note for the handoff filename/topic]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
---

<objective>
Capture everything a fresh Claude Code conversation — with zero memory of this one — would need to
pick up the current implementation and finish it correctly, without re-deriving context, re-reading
the whole codebase from scratch, or repeating mistakes already made and corrected in this
conversation.

The output is a single self-contained Markdown file written to `.claude/handoffs/` (relative to the
repo root). It is not a changelog and not a status update — it is a briefing document for another
agent that has never seen this conversation.

Output directory: `.claude/handoffs/` (relative to the repo root)
</objective>

<context>
Project: Loopscribe V2 API — NestJS monorepo at the repo root.
- `apps/api` — REST API (Fastify, port 9000), global prefix `api/v1`
- `apps/realtime` — WebSocket service (Socket.io, port 9001)
- `apps/workers` — BullMQ background job processor
- `libs/shared` — Drizzle ORM schema + queue constants
- `libs/config` — Zod-validated env schema
- `libs/redis` — ioredis client
- `libs/ai` — multi-provider LLM abstraction (`ScriptProviderRegistry`, `LlmProvider`)
- Database: DigitalOcean-managed Postgres via `DATABASE_URL` in `.env` — never the local Postgres
  instance, which only has migration 1 applied and does not reflect real data
- Handoff directory: `.claude/handoffs/`

This skill is destination-agnostic. The fresh conversation reading a handoff document might be
continuing implementation, running an independent review (this project has a `qa-verify` skill for
that, among others), picking up a plan that was approved but not executed, or doing something else
entirely. Do not write the document assuming any particular next skill, agent, or workflow will be
used — describe the current state and what needs to happen, and let the next thread (human or
model) decide how to approach it.

Argument: $ARGUMENTS (optional short slug or focus note — if empty, derive the filename and scope
from the conversation itself)
</context>

<process>

## Step 0 — Confirm this is actually a handoff moment

A handoff document is for continuing work in a **different conversation**, not for summarizing
work that is already finished and needs no further action. Before writing anything, confirm with
the conversation history that there is real unfinished or unverified work to hand off: an
implementation in progress, a QA pass that found issues still needing fixes, a plan that was
approved but not (fully) executed, or context too large to safely continue in this thread.

If the work is actually complete and fully verified with nothing left to do, say so plainly and
ask the user whether a handoff is still wanted (e.g. purely for audit-trail purposes) rather than
silently producing a document implying there's unfinished work.

---

## Step 1 — Reconstruct the full picture from the conversation

Before writing the file, synthesize the following from the entire conversation, not just the most
recent turns. Prior context in a long conversation is just as load-bearing as recent context —
re-read/recall the original request, not just where things ended up.

### 1a. Original requirement

What did the user actually ask for, in their own terms? Include:
- The business/product need this addresses, not just the technical task
- Any explicit constraints stated during the conversation (e.g. "don't use provider X", "must not
  touch table Y", specific naming/scoping rules)
- Any sub-requests folded into the original ask over the course of the conversation
- Links to any design docs, plan files, or prior handoff documents that were treated as
  authoritative during this conversation — cite their paths so the next thread can load them too,
  but do not assume they will still exist unchanged; note that as a caveat where relevant

### 1b. Current state of version control

Run and record:
```bash
git log --oneline -15
git status --short
git branch -vv
```
Note the exact branch, the exact commit(s) that contain this work, whether it's pushed to a
remote, and whether the working tree is clean. If commits were made in a specific order that
matters (e.g. a merge that resolved conflicts between parallel work), record that order and why.

Flag anything unusual discovered about the repo/tooling during this conversation that the next
thread needs to know to avoid repeating wasted effort — e.g. a gitignore rule that silently
excluded files from version control, an isolation/worktree mechanism that behaved unexpectedly, a
build or migration quirk. State these as concrete, confirmed facts with how they were diagnosed,
not vague warnings.

### 1c. What was implemented

For each distinct piece of work (phase, feature slice, bug fix):
- What it does and why it exists
- Exact files created/modified, with a one-line description of what changed in each — do not just
  list paths, say what's actually in them
- Key design/architecture decisions made and the reasoning behind them (especially any decision
  that took real back-and-forth or investigation to reach — a fresh thread should not have to
  rediscover it)
- Any known limitations or deliberate scope exclusions, and why they were excluded

### 1d. What was actually verified, and how

Distinguish sharply between "written" and "verified." For each claim of working functionality:
- What was actually tested (a specific curl command, a specific DB query, a specific live job run)
- What the actual observed result was — quote real output/log lines where they were captured in
  the conversation, not a paraphrase
- Whether verification exercised the **real** code path (e.g. the actual API endpoint a user would
  call) or a **shortcut** path (e.g. manually enqueueing an internal job that a real endpoint
  would normally enqueue automatically) — this distinction matters enormously and must be explicit,
  since shortcut-verified functionality can look done while not actually working end-to-end
- Any bugs found and fixed during implementation, including ones that were discovered
  serendipitously (e.g. a real external-API failure that happened to prove a retry path works)

### 1e. What was found broken, incomplete, or unverified

This is the most important section for a handoff — be exhaustive and precise, not vague:
- Every issue found by manual testing or an independent review (e.g. a `qa-verify` pass), with:
  - Exact file and line/location
  - A concrete failure scenario (specific inputs/state → specific wrong outcome), not an abstract
    description
  - Severity/priority relative to other issues, and why (e.g. "this blocks the feature from
    working through its real entry point" vs. "this is a latent race that needs multiple replicas
    to trigger")
  - Whether it was confirmed live/empirically or only identified by code reading
- Anything explicitly deferred or left for "later" during the conversation, and why
- Any place where the implementation's own claims of success turned out to be based on incomplete
  or shortcut testing (name this plainly if it happened — the point of the handoff is to prevent
  the next thread from repeating the same false-positive verification)

### 1f. Constraints that still apply

Re-state any hard constraint discovered or imposed during this conversation that the next thread
must continue to honor — e.g. an unavailable/revoked credential requiring a specific fallback
provider, a "must not auto-publish" business rule, a required test-account/JWT flow. State these
as absolute requirements, not suggestions, and explain briefly why (what breaks if ignored).

### 1g. Useful existing state

If prior testing left behind useful real data (test records, IDs, accounts) that the next thread
can reuse instead of recreating from scratch, list it — but flag it as "useful if still present,
not load-bearing" rather than something the next thread should assume unconditionally exists.

---

## Step 2 — Choose the filename

Generate a kebab-case slug describing the feature/work being handed off. If `$ARGUMENTS` provides
one, use it (normalized to kebab-case); otherwise derive one from the conversation's subject.

Pattern: `.claude/handoffs/<kebab-case-topic>-handoff.md`

If a handoff file already exists for this exact topic (e.g. this is a second handoff continuing
from a first), do not silently overwrite it — read it first, and either append a new dated section
noting what's changed since, or write a new file with a version/date suffix, whichever keeps the
history clearer. Use judgment; ask the user if genuinely ambiguous.

---

## Step 3 — Write the file

Ensure `.claude/handoffs/` exists (create it if not). Write a single Markdown file using the
template below. Fill every section with real, specific content — no placeholders, no "TBD," no
section left as a stub. If a section genuinely doesn't apply (e.g. no known limitations), say so
explicitly rather than omitting the heading, so the next reader knows it wasn't forgotten.

---

### Handoff document template

```markdown
# Handoff: <Feature/Work Name>

**Purpose of this document:** This is a continuation handoff for a fresh conversation thread.
<One or two sentences on why this handoff exists — e.g. "the prior thread implemented X and ran
an independent QA pass that found real issues; this document contains everything needed to
resume without re-deriving context.">

**What the next thread should do:** <One or two sentences of the single clearest next action —
e.g. "fix the issues in §4, prioritized in the order listed" or "continue implementing step 3 of
the plan referenced below" or "review the approach in §3 before writing any more code.">

---

## 1. Original Requirement

<What the user asked for, in enough detail that intent is unambiguous. Include explicit
constraints stated during the conversation. Reference any design docs/plans treated as
authoritative, with paths, and a caveat that they may not exist unchanged in a fresh environment.>

---

## 2. Current Git State

Branch `<branch>`, <pushed/not pushed> to `<remote>`. Relevant commits, in order:

\`\`\`
<git log output or hand-curated list of relevant commits with one-line descriptions>
\`\`\`

<Any merge/conflict-resolution notes, migration state, or infra quirks discovered — stated as
confirmed facts with how they were diagnosed.>

---

## 3. What Was Implemented

<One subsection per distinct piece of work — phase, slice, or fix. For each: what it does, exact
files touched with what changed, key decisions and reasoning, known limitations.>

### <Piece of work 1>
- Files: ...
- Decisions: ...
- **Verified working**: <what was actually tested and the real observed result — quote real
  output where available>

### <Piece of work 2>
...

---

## 4. What Was Found Broken, Incomplete, or Unverified

<Ordered by severity. For each: exact location, concrete failure scenario, why it matters, and
whether it was confirmed live or only identified by reading code.>

### <Severity> — <short title>
- Location: `path/to/file.ts`, line ~N
- Failure scenario: <specific>
- Status: <CONFIRMED live / CONFIRMED by code read / suspected, not yet verified>

<repeat>

### Final verdict from the last review pass (if applicable)
<e.g. APPROVED / APPROVED WITH RECOMMENDATIONS / CHANGES REQUIRED, and why>

---

## 5. Constraints That Still Apply

<Absolute requirements the next thread must continue honoring, with brief "why" for each.>

---

## 6. What The Next Thread Should Do

<Concrete, ordered action list, whatever form the remaining work actually takes — implementing a
feature, fixing bugs, running a review, writing docs, or something else. For each item, include a
specific definition of done: not just "fix it" or "build it" but "do X, then prove it by doing Y
and observing Z." If the remaining work includes fixing issues found during this conversation,
explicitly instruct re-verifying from scratch afterward, not just spot-checking what was touched —
state why, if this conversation learned that lesson the hard way (e.g. a prior claim of "verified"
turned out to rest on incomplete testing).>

---

## 7. Useful Existing State (if any)

<Test accounts, IDs, records left over from prior testing that can be reused — flagged as
"useful if still present" not "guaranteed to exist.">

---

## 8. Key File Reference

<Quick-navigation list of the most important files this work touches, not exhaustive — grouped
by area/layer.>
```

---

## Step 4 — Confirm and report

After writing the file, output a short confirmation to the user. Do not restate the whole document
content — just confirm where it was written and what to do with it:

```
Handoff saved: .claude/handoffs/<filename>.md

Open a new conversation in this project and point it at that file (or paste its path) to continue.
```

If the user also wants a ready-to-paste prompt for starting the new conversation, offer to write
one — a short paragraph instructing the fresh thread to read the handoff file first, then follow
its "What The Next Thread Should Do" section. Keep that prompt separate from the handoff document
itself; the document is the context, the prompt is the instruction to load it.

---

## Quality checklist — verify before writing

Before writing the file, confirm every item:

- [ ] The original requirement section captures the actual product/business need, not just a
      technical restatement
- [ ] Every implemented piece of work lists its exact files and real decisions, not vague summaries
- [ ] "What was verified" is sharply distinguished from "what was implemented" — and shortcut
      verification (e.g. manually enqueueing a job a real endpoint should trigger) is called out
      explicitly wherever it happened, not glossed over
- [ ] Every known issue has an exact file/line, a concrete failure scenario, and a severity — no
      vague "might be an issue somewhere" entries
- [ ] Constraints section states requirements as absolute, with the "why" for each
- [ ] The "what to do next" section includes a concrete acceptance test for the top-priority item,
      not just an instruction to "fix it"
- [ ] A model with zero memory of this conversation could read only this file and continue
      correctly, without needing to ask clarifying questions about what was already decided
- [ ] Nothing in the document is invented or guessed to fill a gap — if something is genuinely
      unknown, it says so explicitly rather than presenting a guess as fact

If any item fails, fix the content before writing the file.

</process>
