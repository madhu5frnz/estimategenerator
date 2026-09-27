"""Pure domain logic: no database, network, or framework imports.

Everything under ``app.domain`` must be deterministic and importable on its own, so the
calculation engine can be tested and audited in isolation.
"""

ENGINE_VERSION = "1.0.0"
