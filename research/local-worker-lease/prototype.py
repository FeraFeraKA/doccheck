"""Isolated PostgreSQL proof of lease ownership; no HTTP or inference."""

from uuid import UUID, uuid4

SCHEMA = """
CREATE TABLE lease_proof (
    job_id uuid PRIMARY KEY,
    pool text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    status text NOT NULL DEFAULT 'queued',
    attempt integer NOT NULL DEFAULT 0,
    owner text,
    lease_id uuid,
    expires_at timestamptz,
    result_hash bytea,
    CONSTRAINT lease_proof_status CHECK (status IN ('queued', 'processing', 'completed', 'failed'))
)
"""

# At most three attempts. The row, owner and lease are locked together so
# concurrent claimers cannot both receive the same processing generation.
CLAIM = """
WITH selected AS (
    SELECT job_id FROM lease_proof
    WHERE pool = %(pool)s AND attempt < 3 AND (
        status = 'queued' OR (status = 'processing' AND expires_at <= clock_timestamp())
    )
    ORDER BY created_at, job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE lease_proof AS job
SET status = 'processing', attempt = attempt + 1,
    owner = %(owner)s, lease_id = %(lease_id)s,
    expires_at = clock_timestamp() + %(ttl)s * interval '1 second'
FROM selected
WHERE job.job_id = selected.job_id
RETURNING job.job_id, job.attempt, job.expires_at
"""

RENEW = """
UPDATE lease_proof
SET expires_at = clock_timestamp() + %(ttl)s * interval '1 second'
WHERE job_id = %(job_id)s AND pool = %(pool)s AND owner = %(owner)s
AND lease_id = %(lease_id)s AND status = 'processing' AND expires_at > clock_timestamp()
RETURNING expires_at
"""

FINISH = """
UPDATE lease_proof
SET status = 'completed', result_hash = %(result_hash)s, expires_at = NULL
WHERE job_id = %(job_id)s AND pool = %(pool)s AND owner = %(owner)s
AND lease_id = %(lease_id)s AND status = 'processing' AND expires_at > clock_timestamp()
RETURNING job_id
"""

RETRY_FINISH = """
SELECT job_id FROM lease_proof
WHERE job_id = %(job_id)s AND pool = %(pool)s AND owner = %(owner)s
AND lease_id = %(lease_id)s AND status = 'completed' AND result_hash = %(result_hash)s
"""

EXPIRE_FINAL = """
UPDATE lease_proof
SET status = 'failed', expires_at = NULL, owner = NULL, lease_id = NULL
WHERE pool = %(pool)s AND status = 'processing' AND attempt >= 3
AND expires_at <= clock_timestamp()
"""


def claim(conn, pool: str, owner: str, ttl: int) -> tuple[UUID, tuple | None]:
    lease_id = uuid4()
    row = conn.execute(
        CLAIM, {"pool": pool, "owner": owner, "lease_id": lease_id, "ttl": ttl}
    ).fetchone()
    return lease_id, row
