# Knowledge Base Package

## Purpose
Ingestion pipeline for documents and knowledge sources.

## Must NOT do
- Fetch remote sources without explicit user consent.
- Store raw content without validation.
- Assume a single vector backend.

## Integration points
- Memory package for vector store.
- Core API for ingestion triggers.

## TODO
- Implement source adapters.
- Add chunking strategies.
- Build indexing workflows.
