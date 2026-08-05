# Design provenance

Every core contract in Research OS traces to one or more of these clean-room principles.

| Principle | Implementation contract |
| --- | --- |
| Bounded mutable surface | Project constitution, resolved-path validation, disposable workspace, protected-path verification |
| Immutable evaluation | Sealed evaluator/data/mutable-seed fingerprints, compatibility-bound baselines, and post-run drift checks |
| Fixed experiment budget | Wall-clock timeout, output and artifact limits |
| Reversible ratchet | Source checkout remains untouched; candidates run in disposable snapshots |
| Experiment DAG | Explicit scientific parent IDs, explicit retry-attempt edges, and durable terminal nodes for every outcome |
| Typed provenance | Result envelope plus code, data, environment, evaluator, candidate, artifact, and policy digests |
| Durable graph memory | Hash-chained events, append-only findings, validated lineage projections, and crash recovery |
| Artifact evidence | Pre-cleanup SHA-256 capture plus canonical event-to-manifest-to-blob verification during queries and replay |
| Safe authority boundary | Empty side-effect declaration and `authorized_action: null` on research outputs |
| Incremental complexity | Single local worker and deterministic adapter protocol before parallel or distributed execution |

The event log is canonical because research history must remain auditable even when query projections or user interfaces change. The SQLite database is deliberately rebuildable from the event stream. Replay also revalidates experiment/retry relationships and every referenced baseline or candidate artifact; it is an integrity operation, not merely a database import.
