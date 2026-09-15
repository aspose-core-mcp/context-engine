"""ADCS chaos / DR fault-injection drill harness.

Every drill exercises a *real* ADCS degraded-mode path (lane failure,
timeout, rollback, partial publish, DR restore) and writes a structured JSON
record to ``reports/chaos/`` so that auditors can verify the resilience claim
without booting Kubernetes.
"""
