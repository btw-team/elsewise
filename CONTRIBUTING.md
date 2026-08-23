# Contributing to Elsewise

Thank you for considering a fix, adapter improvement, documentation change, or new
workflow for Elsewise.

## Before starting

- Search existing issues and suggested features.
- Keep one pull request focused on one coherent change.
- For large product, protocol, persistence, security, or permission changes, open an
  issue describing the intended behavior before implementation.
- Never include real meeting transcripts, participant data, credentials, pairing
  tokens, runtime control tokens, API keys, or raw unsanitized DOM captures.

## Development setup

Follow [Development setup](docs/development/setup.md), then run `make check` before
submitting. Use `make coverage` to inspect changed critical paths; there is no global
coverage percentage requirement.

## Choosing tests

- Pure state transition or formatter: unit test.
- Database/API/WebSocket boundary: backend integration test.
- React user behavior: Testing Library test using accessible roles.
- Meeting DOM behavior: sanitized fixture plus adapter test; add a soak when stable
  identity or reconciliation changes.
- Cross-component browser behavior: synthetic Playwright E2E.
- OS lifecycle or packaging: add automation where possible and a platform validation
  case where native confirmation is still required.

Do not delete cross-runtime protocol parity, adapter soaks, regression tests, or
platform-specific checks merely because a higher-level scenario overlaps.

## Contract changes

- Protocol changes require JSON schema, Python model, TypeScript model, valid/invalid
  fixtures, and parity tests.
- REST error changes require `shared/api-errors.json`, web localization mapping, and
  API error documentation.
- Persistence changes require model and migration agreement plus migration tests.
- User-visible text requires complete EN/RU/FR/ES/DE/PT-BR catalogs where the
  interface supports those languages.
- Packaging changes require frozen smoke and release inventory updates.

## Pull request checklist

- [ ] The change is scoped and explained.
- [ ] Sensitive or personal data is absent.
- [ ] Relevant tests were added or updated.
- [ ] `make check` passes.
- [ ] Documentation and screenshots were updated when behavior changed.
- [ ] Platform-specific untested behavior is called out explicitly.
- [ ] License and third-party notices were updated if dependencies/assets changed.

By submitting a contribution, you agree that it is licensed under the project's
[Apache License 2.0](LICENSE).
