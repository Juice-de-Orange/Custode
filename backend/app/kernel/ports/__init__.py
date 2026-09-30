"""Ports — interfaces to the outside world (ARCHITECTURE §8.3).

Each port has a real adapter, a **Null adapter** (neutral answer when the feature
is off) and a Fake (tests). Domain code asks a port, never 'is X configured?' —
that is how 'works fully without Wearables/Weather/AI' is the normal path, not a
special case (Graceful Enhancement, P5)."""
