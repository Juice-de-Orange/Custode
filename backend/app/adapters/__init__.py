"""Adapters implement kernel/ports. They know kernel/ports only — never modules.

Layout (grows per integration): ``null/`` (neutral, Graceful Enhancement),
later ``openmeteo/``, ``ollama/``, ``paddle/``, ``s3/``, ``smtp/``, ``oura/`` …"""
