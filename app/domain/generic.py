"""Default domain: pure grounded RAG + rule registry, no personal records.

Runs end to end as-is (policy Q&A, citations, precedence, not_found, audit).
For a real problem statement: python scripts/new_domain.py <name>
"""
from app.domain.base import Domain


class Generic(Domain):
    name = "generic"


DOMAIN = Generic()
