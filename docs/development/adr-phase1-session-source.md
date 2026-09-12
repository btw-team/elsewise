# ADR: Phase 1 Session, Source, and pairing boundaries

**Status:** accepted  
**Date:** 2026-09-12

## Context

The original capture path combined meeting detection, extension controls, a
global pairing token, and transcript persistence. That made reconnects,
multiple tabs, and a reliable Stop boundary ambiguous.

## Decision

- `SessionController` is the only owner of Session Start/Stop and serializes
  lifecycle transitions through a bounded executor.
- `SourceManager` owns source discovery, selection, reconciliation, health,
  and daemon-issued `source.start`/`source.stop` commands.
- A `CaptureSource` identifies one paired-client tab lifetime and provider
  activity; a `SourceEpoch` identifies one continuous producer namespace.
- Browser and deterministic synthetic captions are code-owned drivers using
  the same protocol-v2 lifecycle and normalized-evidence contract.
- Captions are projected into canonical utterances scoped by SourceEpoch. Raw
  provider payload, URL, document title, and meeting title are not persisted.
- Pairing is request/approve over a short-lived socket. Each installation gets
  a revocable high-entropy credential whose digest is the only server-side
  persisted secret material.
- The persistence layer is a new consolidated `0001_initial` schema. There is
  no old-database migration, protocol-v1 fallback, or compatibility control
  plane.

## Consequences

Session can run without a source and survives source loss. A single live
candidate may be selected automatically; multiple candidates require an
explicit user choice. Transport reconnect preserves an epoch, while producer
restart creates one. Stop drains producers within a hard budget and makes the
transcript immutable once the Session reaches `stopped`.

This ADR summarizes the implemented boundary. The normative implementation
plan remains [`notes/plan-1.md`](../../notes/plan-1.md).
