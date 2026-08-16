# Model routing for Research OS agents

Research OS stores scientific state and enforces experiment integrity, but it
does not call an LLM or choose a provider model. Model selection belongs to the
Codex or Claude Code session that operates the control plane. This repository
ships quality-aware defaults and an explicit launcher so routine bookkeeping can
use a balanced model without lowering the quality of scientific decisions.

## Routes

| Route | Use for | Codex | Claude Code |
| --- | --- | --- | --- |
| `control` | `doctor`, `replay`, `status`, bounded context retrieval, formatting | GPT-5.6 Terra / medium | Sonnet / medium |
| `research` | hypotheses, candidates, terminal Diagnosis, graph action and parent selection | GPT-5.6 Sol / high | Opus / high |
| `audit` | evaluator certification, adversarial review, conflicting-evidence synthesis | GPT-5.6 Sol / xhigh | Opus / xhigh |

The checked-in project defaults are the `research` route. Opening a trusted
Codex or Claude Code session in this repository therefore preserves the
high-quality scientific default even when the launcher is not used.

Use the lower-cost route only for control-plane work that does not choose a
hypothesis, interpret a terminal result, or change scientific state:

```bash
scripts/research-agent codex control
scripts/research-agent claude control
```

Start an ordinary research cycle with:

```bash
scripts/research-agent codex research
scripts/research-agent claude research
```

Run an independent audit in a fresh session, separate from the implementation
conversation:

```bash
scripts/research-agent codex audit
scripts/research-agent claude audit
```

Arguments after `--` are forwarded unchanged. For example:

```bash
scripts/research-agent codex research -- \
  "Use Research OS for at most two experiments and diagnose every terminal result."

scripts/research-agent claude audit -- \
  "Independently audit the current evaluator-review subject. Do not modify the project."
```

Use `--dry-run` after the route to inspect the exact command without starting a
session:

```bash
scripts/research-agent codex research --dry-run
```

## Routing boundary

One agent session has one root model selection. The Research OS skill must not
pretend that it changed the active root model mid-session. Split mechanical
control work, scientific research, and independent audit into fresh sessions
when their routes differ. Canonical events, findings, Diagnosis records, and
`agent-context` make this handoff reproducible without carrying a long chat.

Multi-agent or maximum-compute modes are not the default research route. Use
them only when the work divides into genuinely independent workstreams or a
material final decision justifies the extra usage. Sequential experiment loops
remain on the single-agent `research` route.

Model aliases and availability can change with provider and account access. The
launcher deliberately keeps provider-specific choices at this thin session
boundary; it does not add provider SDKs, credentials, or model identity to the
Research OS evidence graph.
