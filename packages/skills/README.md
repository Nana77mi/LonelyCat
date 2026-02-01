# Skills Package

## Purpose
Framework for loading and registering skills.

## Must NOT do
- Execute tools inside registration.
- Load untrusted code without sandboxing.
- Modify global state without audit logs.

## Integration points
- Runtime policy and tool runner.
- Core API for skill management.

## TODO
- Implement manifest parsing.
- Add registry persistence.
- Define skill sandboxing.
