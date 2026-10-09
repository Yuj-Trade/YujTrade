# ADR-0001: Domain boundaries

Trading decisions that must be identical in live and simulated execution belong
in `domain/`. Adapters translate provider-specific objects before calling these
pure functions.
