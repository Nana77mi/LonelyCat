# Memory Package

## Purpose
Memory and knowledge storage abstractions (transcripts, facts, vectors).

## Must NOT do
- Persist sensitive data without encryption.
- Hardcode storage backends.
- Perform retrieval logic inside storage adapters.

## Integration points
- Agent runtime for recall and storage.
- KB ingestion pipeline.

## TODO
- Add pluggable storage backends.
- Implement retention policies.
- Add encryption hooks.
