# ADR-0005: Holdout isolation

Holdout data must not participate in model fitting or optimization. Holdout
execution is an explicit operational action and is not part of routine tests.
