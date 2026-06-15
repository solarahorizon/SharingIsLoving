# Incident NNN — [Short Title] (YYYY-MM-DD)

> **About this template.** Incident reports are **lazy-load knowledge** — they sit silently until a future Claude session greps for matching keywords. The gold field is `trigger-keywords` in the frontmatter: exact phrases an agent would type when blocked, which grep-match this file. Pairs with a slim `INDEX.md` listing all incidents by tag.
>
> See the README for the memory-vs-incident-log architecture in full.

---

```yaml
---
id: NNN
date: YYYY-MM-DD
title: Short descriptive title
tags: [keyword1, keyword2, language-or-tool, fallback]
trigger-keywords: ["exact phrase an agent would hit", "another symptom phrase"]
projects: [project-name, other-project-where-it-recurred]
related-incidents: [NNN, NNN]
---
```

**Date:** YYYY-MM-DD HH:MM TZ
**Impact:** [What was blocked, for how long, what was the blast radius]
**Duration:** [Start → resolution time]
**Verified fixed:** [Date/time + how verified]

---

## Symptom

- [What the agent/user observed — error codes, crash dialogs, test output patterns]
- [Be specific: exit codes, timing patterns, error messages]
- [Include the EXACT error message or crash signature where applicable]

## Investigation Steps

[What SHOULD be done to diagnose — write as a procedure for future agents]

1. **Step 1:** [First diagnostic action]
2. **Step 2:** [Second action]
3. **Step 3:** [Third action]
4. [Continue as needed]

## Root Cause

[The actual technical cause — file:line if code bug, system state if infra issue]

[Include code snippets showing the broken code if applicable]

## Resolution

[The fix — code change, config change, or workaround]

[Include code snippets showing the fix if applicable]

## Lessons Learned

1. [Key takeaway #1 — what to do differently next time]
2. [Key takeaway #2 — what signal to look for first]
3. [Key takeaway #3 — what assumption was wrong]

## How a future agent finds this

Symptoms: [exact phrases an agent would hit]. Search:

```sh
grep -lir "tag1\|tag2" docs/knowledge_base/incidents/
```

## Related conventions

- [Skill / rule / convention this incident codified into]
- [Other related incidents or docs]
