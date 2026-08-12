# claude-code-vendor-swap

Point **one** Claude Code project at an Anthropic-compatible vendor endpoint (Alibaba Qwen, Moonshot Kimi) while every other project stays on your Claude subscription. Three settings in that project's `.claude/settings.local.json`, one key script outside any repo. No logout, no shell exports, nothing global.

## Why it exists

Two days after a weekly Claude quota reset, the account was already 65% through it. The fix was to move one project onto a vendor plan, in a way that touched nothing else.

The first two obvious homes for the credential are both wrong:

- **Shell export** (`export ANTHROPIC_AUTH_TOKEN=...`): follows you into every project you open from that terminal. Wrong scope.
- **Token pasted into `settings.local.json`**: right scope, but now a secret sits in a file inside the repo. Gitignored, until somebody runs `git add -f` or clones onto a machine without that ignore rule.

`apiKeyHelper` closes the gap: the settings file names an executable and Claude Code uses whatever it prints. The repo holds a path; the secret lives in a `chmod 700` script outside any repo.

This works because your Pro or Max login is the lowest-priority credential Claude Code has. Anthropic's documented precedence puts cloud-provider auth, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY` and `apiKeyHelper` all above the subscription login, so whatever you supply wins without signing out. That ordering is a property of the CLI rather than of your account, so check it against the settings documentation for the version you are running (confirmed here on v2.1.226).

## The recipe

1. Put your vendor key in a script outside any git repo, `chmod 700` (template: [`vendor-key.example.sh`](vendor-key.example.sh)).
2. In the one project you're moving, add `apiKeyHelper`, `ANTHROPIC_BASE_URL` and `ANTHROPIC_MODEL` to `.claude/settings.local.json` (working examples below).
3. Restart Claude Code inside that project, then verify (see below).

## Working examples

Both files in this folder are real configs in production use, with only the username and key genericised.

Alibaba Qwen ([`settings.local.qwen.json`](settings.local.qwen.json)):

```json
{
  "apiKeyHelper": "/Users/you/.claude/qwen-key.sh",
  "env": {
    "ANTHROPIC_BASE_URL": "https://token-plan.<region>.maas.aliyuncs.com/apps/anthropic",
    "ANTHROPIC_MODEL": "qwen3.8-max"
  }
}
```

Moonshot Kimi ([`settings.local.kimi.json`](settings.local.kimi.json)):

```json
{
  "apiKeyHelper": "/Users/you/.claude/kimi-key.sh",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding",
    "ANTHROPIC_MODEL": "kimi-k3"
  }
}
```

Nothing here is vendor-specific: the same three settings moved the same project from Qwen to Kimi by changing their values.

## Verify it, properly

Do not ask the model what it is. Asked directly, Qwen answered "I'm Claude, made by Anthropic"; Kimi named itself correctly, then admitted it was repeating what the harness told it. Neither answer is evidence.

Do not trust the status line either. It shows the model the session is **configured** with, not what answered. We have a screenshot of a status line proudly reading `qwen3.8-max` while every single request was failing with a 429.

Instead, make one non-interactive call and read the answer's metadata:

```bash
claude -p "hi" --output-format json | jq -r '.modelUsage | keys[]'
```

(Needs [`jq`](https://jqlang.github.io/jq/); without it, drop the pipe and read
the raw JSON.)

There is no top-level `model` field. The model that served the request is the
**key of `modelUsage`**, sitting next to the tokens and cost it actually billed:

```json
"modelUsage": {
  "kimi-k3": {
    "inputTokens": 29496,
    "outputTokens": 370,
    "costUSD": 0.160058,
    "contextWindow": 200000,
    "canonicalModel": "kimi-k3",
    "provider": "firstParty"
  }
}
```

Two details that bite when you run it:

- The connectors warning from trap 3 prints on **stderr, ahead of the JSON**, so
  a parser fed both streams chokes. Pipe stdout alone.
- The call is billed to the vendor like any other, and it pays for a full
  session context, not the three tokens you sent.

Verified against the Kimi config above on Claude Code v2.1.226. The field name is
a CLI detail; if a later version moves it, `--output-format json` still carries
the answer's own metadata somewhere, and the model's self-report still does not.

## Traps, each one hit for real

1. **The endpoint has to match the key type.** Moonshot sells two products with two key types and two endpoints, and swapping them returns `401 Invalid Authentication`, which reads like a bad key rather than a wrong URL. A **Kimi for Coding** subscription key works only against `https://api.kimi.com/coding`; a **pay-as-you-go platform** key (from `platform.moonshot.ai`) works only against `https://api.moonshot.ai/anthropic`. The official Claude Code guide documents the pay-as-you-go path only, so a subscription key following it fails.
2. **`settings.local.json` is read at startup.** Restart Claude Code in that project after editing it.
3. **Expect a warning that your claude.ai connectors are disabled.** Any non-subscription credential triggers it. It is accurate, not a bug.
4. **There is no fallback.** If the vendor endpoint goes down, Claude Code raises a hard error rather than quietly falling back to your subscription. That is the behaviour you want: an outage costs you a visible error, not a silent drain on the quota you were protecting.
5. **`/usage` still shows your Claude plan.** Claude Code's usage panel is an OAuth call scoped to the Anthropic subscription; it ignores `ANTHROPIC_BASE_URL`. Reading it mid-session and taking the figures for the vendor's is exactly the mistake it invites. Vendor plans have their own quotas, and they run out too.
6. **Requests go to the vendor, not Anthropic.** Whatever the session reads goes with them, under their terms. Pick which projects you swap accordingly.

## If background work starts failing

The three settings above cover the session you type into. Title generation,
summarisation and subagents are separate requests, and they can ask for Claude
tier names the vendor does not publish. Both configs in this folder have run in
production without anything extra, so this is the first thing to check rather
than a required step: point the tier variables at the same model.

```json
"ANTHROPIC_DEFAULT_OPUS_MODEL":   "<vendor-model-id>",
"ANTHROPIC_DEFAULT_SONNET_MODEL": "<vendor-model-id>",
"ANTHROPIC_DEFAULT_HAIKU_MODEL":  "<vendor-model-id>",
"CLAUDE_CODE_SUBAGENT_MODEL":     "<vendor-model-id>"
```

## Day to day

Hooks and skills still fire; they are client-side. For a glanceable (configured, see above) model name plus real per-provider usage in the status line, see [llmeter](https://github.com/solarahorizon/llmeter), which keeps each provider's usage in its own file so one account's quota is never displayed under another's model name.
