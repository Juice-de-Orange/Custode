"""Public surface for ``backoffice`` — intentionally empty. The ops console is a leaf: no feature
module imports it, and it reads household data only via aggregate views / defined action procedures
(ADR-0015), never another module's internals."""

from __future__ import annotations
