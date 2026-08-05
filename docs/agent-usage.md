# Using Research OS through Codex or Claude Code

## Interface contract

The user talks only to Codex or Claude Code. The coding agent is the researcher
and conversational interface; Research OS is a headless local control plane.
It does not contain an LLM SDK, model API key, chat session, or autonomous
provider loop.

```text
user conversation
      |
Codex or Claude Code
      |  shared research-os Agent Skill
      |  strict JSON CLI
Research OS
      |  isolated workspace + project adapter
project evaluator
      |
canonical events, artifacts, findings, DAG
      |
Codex or Claude Code explains the evidence
```

This split lets the user change coding agents without changing experimental
history or domain adapters.

## One-time installation

From the Research OS checkout:

```bash
~/research-os/.venv/bin/research-os install-agent-skill --target all
```

The command copies one packaged Agent Skills-standard workflow to:

- `~/.agents/skills/research-os` for Codex;
- `~/.claude/skills/research-os` for Claude Code.

It accepts an existing byte-identical installation and refuses symlinks,
special files, or different content rather than overwriting local work.

Codex may invoke the skill implicitly or through `$research-os`. Claude Code
may invoke it implicitly or through `/research-os`.

## Normal conversation

Start Codex or Claude Code at the target project and ask for the scientific
outcome, not an OS command:

```text
Set this repository up to search for a lower validation-loss architecture.
Keep the evaluator and split fixed. Ask me before starting expensive training.
```

```text
Use at most six experiments. Explore two independent signal hypotheses, then
spend the remaining budget on the more informative branch. No retries and no
live trading.
```

```text
Summarize what the graph has established, including negative evidence. Do not
run a new experiment.
```

The skill makes the agent resolve the project, run the required gates, call the
CLI, parse JSON, and report in natural language. Raw JSON is shown only on
request.

## Agent context and stale-proposal protection

`agent-context` is a bounded read model containing:

- the resolved scientific contract and authority boundary;
- the research brief and candidate JSON Schema;
- canonical status and event cursor;
- recent experiments and current graph frontier;
- only the latest retry-eligible attempts;
- recent durable findings and verified artifact metadata;
- counts showing whether each section was truncated.

Large values are replaced by deterministic digest handles and the complete
packet has a 2 MiB ceiling. The packet contains `snapshot.context_token`. The
agent writes its one candidate to the excluded transient inbox, then supplies
the token to `run-once`. A changed event graph, evaluator compatibility input,
brief, or schema makes the token stale and prevents registration.

## Mode separation

The shared skill enforces three modes:

1. **Status:** query and explain only; no experiment.
2. **Setup/change-control:** configure or deliberately revise the adapter,
   evaluator, evidence, metric, candidate schema, constitution, and baseline.
3. **Research:** change only the candidate inbox and execute bounded graph
   iterations.

The agent cannot silently revise the evaluator or policy after seeing a result.
Any such request leaves research mode and goes through a new compatibility and
baseline gate.

## Authority

`VALIDATED` means that one sealed experiment met the research constitution. It
does not authorize a merge, deployment, model release, allocation of capital,
or live order. Codex or Claude Code must report `authorized_action: null` and
handle any production proposal as a separate reviewed workflow.
