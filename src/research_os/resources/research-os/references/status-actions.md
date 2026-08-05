# Terminal status actions

Use the exact durable status and reason code. Never convert operational failure
into scientific evidence.

| Status | Required action |
| --- | --- |
| `VALIDATED` | Report the measured improvement and constraints. Retain the node as a frontier candidate. Consider bounded confirmation, ablation, or exploitation. Never deploy. |
| `REJECTED` | Treat as negative scientific evidence. Do not retry. Prune the branch or choose a defensible alternative hypothesis. |
| `INVALID_EXPERIMENT` | Explain the stable reason. A corrected object is a new budgeted candidate. Switch to setup mode if the adapter or schema is defective. |
| `INSUFFICIENT_EVIDENCE` | Draw no scientific conclusion. Stop the branch and use change-control to review evidence or evaluator design. |
| `INFRA_FAILED` | Report the error and `retryable` value. Retry only the latest eligible attempt, within explicit retry budget. Otherwise stop or repair in setup mode. |
| `TIMED_OUT` | Apply the explicit retry rule. Default to at most one bounded retry when the user authorized retries. Repeated timeout requires change-control. |
| `CANCELLED` | Run `replay` once to reconcile durable state, report it, and stop the loop. Retry only when explicitly allowed. |
| `UNTRUSTED` | Hard-stop immediately. Preserve any marked workspace, draw no scientific conclusion, and request human inspection. |

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
