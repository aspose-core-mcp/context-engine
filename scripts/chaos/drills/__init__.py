"""Individual chaos / DR fault-injection drill modules.

Each module exposes a single ``run() -> DrillResult`` entry point. Drills are
side-effect-light: they exercise *application code paths* (degraded retrieval,
snapshot rollback, partial publish, DR restore) rather than killing live
infrastructure, so the suite is CI-runnable and reproducible by auditors.
"""
