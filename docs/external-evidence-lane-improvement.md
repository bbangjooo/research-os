# External evidence in the discovery lane

## Problem

A frame jump needs research about the destination, and that research usually
lives outside the project: papers, practitioner write-ups, domain references.
The OS deliberately never fetches anything — `discovery-analogies` reads only
the local claim store — so external surveying is the agent's job. But the
journal had no place to put the result. A literature finding had to be
shoehorned into an `observation` or `idea` note as free text, with no source
locator, no snapshot digest, and no way for a later reader to check that the
cited source is still the cited source.

The enforcement gap was worse than the representation gap. Projects that adopt
a literature-before-jump rule have been encoding it in agent memory and skill
prompts, and both channels fail the same way: anything that depends on the
agent noticing is dropped under working momentum, while anything encoded as a
deterministic gate fires every time. The rule that "new frames need a prior
survey" was itself un-gated.

## Change

**`external_evidence` note kind.** A sealed record of one outside source:
`source_locator` (URL, DOI, or citation), `snapshot_digest` (SHA-256 of the
exact bytes read), at least one extracted claim, and at least one limitation.
Retrieval happens outside the OS; what enters the journal is a deterministic,
replayable snapshot reference. The kind is advisory like every other note: it
corroborates no exhaustion signal, grants no authority, and is never canonical
evidence.

**Prior binding by adoption.** Recording the first `external_evidence` note
opts the project in: from that point, a new `rival_draft` must cite at least
one recorded `external_evidence` note id in its `refs`, enforced at the screen
(`DISCOVERY_PRIOR_REQUIRED`) and again on replay so a hand-forged journal
cannot dodge it. Drafts recorded before the first external note stay valid —
the journal is append-only, so they have no way to comply retroactively.
Projects that never record external evidence see no behavior change.

**Surfaces.** `discovery-status --yield` reports `prior_binding_active`,
`external_evidence_note_count`, and `prior_backed_rival_draft_count`. The
frame-health packet counts external evidence. The jump dossier carries an
`external_prior` section for the draft under review and a `literature_prior`
authoring obligation ordered before the inquiry obligation.

## Boundary kept

The OS still performs no retrieval, and external material still proves
nothing. The lane records that a survey happened and binds frame candidates to
it; whether the survey was good remains a judgement for the reader and the
independent reviewer, like every other judgement in the system.
