---
name: playwright-tester
description: >
  Automated UI testing using Playwright's native test runner. Writes persistent .spec.ts test files,
  runs them for free via `npx playwright test`, and fixes failures automatically. Use this skill whenever
  the user wants to test a web app, check if a frontend works, run UI tests, verify form submissions,
  test browser interactions, do end-to-end testing, stress test a website, or validate that recent
  changes didn't break anything. Also triggers for "run my tests", "check the app in a browser",
  "does this page work", "test the happy path", or "find UI bugs". This skill is the go-to for any
  browser-based testing — prefer it over manually driving browsers or using screenshot-based approaches.
---

# Playwright Tester

Write Playwright test files, run them natively (zero AI tokens), and fix failures in an automated loop.

## Why This Approach

There are three ways to do browser testing with AI:

1. **AI drives the browser live** — burns tokens on every click, every page load, every assertion
2. **Screenshot-based** (Claude-in-Chrome) — even worse, images are token-heavy and it's single-threaded
3. **AI writes tests, Playwright runs them** — tokens spent once on authoring, execution is free forever

This skill uses approach 3. The test files persist, grow over time into a regression suite, and run
in parallel via Playwright's native worker system. You get the AI's intelligence for test design
without paying for execution.

## Prerequisites

Before first use, verify the project has Playwright installed. If not, install it:

```bash
npm install -D @playwright/test
npx playwright install chromium
```

Check for an existing `playwright.config.ts`. If missing, create a minimal one appropriate to the
project's framework (Next.js, Vite, static, etc.). Use `webServer` config to auto-start the dev
server when tests run.

## Workflow

### Phase 1: Assess

1. Read the project structure to understand the framework, entry points, and routing
2. Check for existing test files in `tests/`, `e2e/`, or `__tests__/` directories
3. Identify what the user wants tested — if vague, read the codebase and suggest the highest-value targets (forms, auth flows, critical user paths)
4. Check for an existing `playwright.config.ts` and understand its setup

### Phase 2: Author Tests

Write `.spec.ts` files organized by test strategy. Each file should be focused and independent.

**File organization:**
```
tests/
  e2e/
    happy-path.spec.ts      — core user journeys that must always work
    validation.spec.ts       — form validation, required fields, error states
    edge-cases.spec.ts       — empty inputs, special characters, boundary values
    accessibility.spec.ts    — keyboard nav, aria labels, screen reader basics
```

**Writing good tests:**

- Use Playwright's locator API — prefer `getByRole()`, `getByLabel()`, `getByText()` over CSS selectors, because they're resilient to markup changes and match how users actually find elements
- Each test should be independent — no shared state between tests, use `beforeEach` for setup
- Use descriptive test names that read like requirements: `test('submits contact form with valid data and shows success message')`
- Add `await expect()` assertions that verify outcomes, not implementation details
- For forms: test the complete flow (fill -> submit -> verify response), not just individual fields
- Keep tests focused — one behavior per test, multiple assertions are fine if they verify the same behavior

**When existing tests are found:**
- Read them first to understand coverage and patterns
- Add new tests for uncovered areas rather than rewriting what exists
- Update broken tests only if the breakage is due to intentional code changes
- Match the existing style and conventions

### Phase 3: Execute

Run the full test suite using Playwright's native runner:

```bash
npx playwright test --reporter=line 2>&1
```

Key flags to know:
- `--workers=auto` — parallel execution across CPU cores (this is the default, no need to set it)
- `--reporter=line` — clean, parseable output for reading results
- `--headed` — only if the user specifically asks to watch the tests run
- `--project=chromium` — single browser for speed during development; run all browsers before deploy

The test runner handles all parallelism natively. No sub-agents needed for execution.

### Phase 4: Fix Loop

When tests fail, enter the fix loop (max 3 attempts):

1. **Read the failure output** — Playwright's error messages include the expected vs actual values, the selector that failed, and a snippet of the page state
2. **Diagnose and categorize** — Label each failure explicitly:
   - **Test bug** — wrong selector, timing issue, incorrect expected value
   - **App bug** — actual broken behavior in the application
   - This categorization matters because it determines what gets fixed (test file vs app code)
3. **Fix the right thing:**
   - Test bug → update the test file
   - App bug → fix the application code, explain what was broken
   - Timing issue → add appropriate `waitFor` or increase timeout on that specific action
4. **Rerun and document** — Always rerun after fixing and document the command used:
   ```bash
   npx playwright test --reporter=line 2>&1
   ```
   Report the rerun results even if all tests pass — the user needs to see confirmation.
5. **If still failing after 3 attempts** — stop, report what's failing and why, ask the user for guidance. Don't keep burning cycles on something that might need architectural input.

When reporting results, always include:
- Total tests, passed, failed, skipped
- For each failure: the test name, what was expected, what happened, and whether it's a **test bug** or **app bug**
- The rerun command and its output
- Suggested fix if you didn't auto-fix

### Phase 5: Report

After all tests pass (or after the fix loop exhausts):

1. Summarize results in a clear table format
2. If any app bugs were found and fixed, list them explicitly
3. Suggest additional test coverage areas the user might want
4. Note any flaky tests that passed on retry (these need attention)

## Swarm Mode

When the user wants comprehensive testing from multiple angles simultaneously, use sub-agents
to **write** tests in parallel, then run them all natively.

Example swarm configuration — spawn 3 sub-agents:

- **Agent 1: Happy Path** — writes tests for core user journeys, success flows, standard inputs
- **Agent 2: Validation & Edge Cases** — writes tests for error states, empty inputs, boundary values, special characters, XSS attempts
- **Agent 3: Accessibility & UX** — writes tests for keyboard navigation, focus management, aria attributes, responsive behavior

Each agent writes its test files to the shared `tests/e2e/` directory. Once all agents complete,
run the full suite once with `npx playwright test`. Playwright's worker system handles parallel
execution of the combined test files.

The key insight: sub-agents spend tokens on test *design* (the creative, high-value part), while
execution uses zero tokens regardless of how many tests were written.

To invoke swarm mode, tell Claude: "Use the playwright-tester skill in swarm mode" or "Run parallel
test agents" or "Test from multiple angles."

## Tips

- **Start narrow, expand later.** Test the specific thing the user changed first, then broaden coverage.
- **Don't over-test.** A focused suite of 10-15 meaningful tests beats 100 trivial ones. Test behaviors users care about.
- **Use the config.** If the project has a `webServer` config in playwright.config.ts, the dev server starts automatically — no need to start it manually.
- **Trace on failure.** If a failure is confusing, rerun with `--trace on` to get a full trace file for debugging.
- **CI-ready.** The test files this skill creates are standard Playwright tests — they run in CI pipelines with zero modification.
