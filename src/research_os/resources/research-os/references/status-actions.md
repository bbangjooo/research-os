# Terminal status actions

Use the exact durable status and reason code. Never convert operational failure
into scientific evidence.

Apply these actions only after the no-experiment diagnosis step in
[scientific-protocol.md](scientific-protocol.md). A single `VALIDATED` node is
promising evidence, not a replicated branch conclusion.

| Status | Required action |
| --- | --- |
| `VALIDATED` | Report the measured improvement and constraints. Retain the node as a frontier candidate. Consider bounded confirmation, ablation, or exploitation. Never deploy. |
| `REJECTED` | Treat as negative scientific evidence. Do not retry. Prune the branch or choose a defensible alternative hypothesis. |
| `INVALID_EXPERIMENT` | Explain the stable reason. A corrected object is a new budgeted candidate. Switch to setup mode if the adapter or schema is defective. |
| `INSUFFICIENT_EVIDENCE` | Draw no scientific conclusion. Retry only when the adapter marked the latest eligible attempt `retryable: true`, the retry is exact, and explicit retry budget remains. Otherwise stop the branch; use change-control when the evidence or evaluator design itself is inadequate. |
| `INFRA_FAILED` | Report the error and `retryable` value. Retry only the latest eligible attempt, within explicit retry budget. Otherwise stop or repair in setup mode. |
| `TIMED_OUT` | Apply the explicit retry rule. Default to at most one bounded retry when the user authorized retries. Repeated timeout requires change-control. |
| `CANCELLED` | Run `replay` once to reconcile durable state, report it, and stop the loop. Retry only when explicitly allowed. |
| `UNTRUSTED` | Hard-stop immediately. Preserve any marked workspace, draw no scientific conclusion, and request human inspection. |

After a materially supported replicated branch, or when conclusive `REJECTED`
nodes reach the pre-registered class-closure threshold, use `conclude-branch` as
specified in `scientific-protocol.md`. Do not create a conclusion for an
operational or insufficient-evidence outcome alone.

Handle structured CLI errors as follows:

- Correct `CLI_USAGE` once without consuming scientific budget.
- On `STALE_AGENT_CONTEXT`, refresh context and reconsider the proposal once;
  no experiment has been registered and no scientific budget was consumed.
- Treat `NOT_CONFIGURED`, configuration, and protocol errors as setup mode.
- On duplicate candidate refusal, choose a genuinely distinct hypothesis; never
  make a cosmetic change.
- On replay, artifact, hash-chain, or integrity errors, hard-stop.
- On a non-reproducible baseline or cleanup failure, do not loosen policy.
  Report the evidence and ask for a change-control decision.
