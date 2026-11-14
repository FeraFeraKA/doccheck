"""Test lease invariants using separate PostgreSQL transactions."""

import os
import unittest
from hashlib import sha256
from uuid import uuid4

import psycopg
from prototype import EXPIRE_FINAL, FINISH, RENEW, RETRY_FINISH, SCHEMA, claim
from psycopg import sql


class LeaseCase(unittest.TestCase):
    def setUp(self):
        url = os.environ.get("DOCCHECK_LEASE_PROOF_DSN")
        if not url:
            self.skipTest("DOCCHECK_LEASE_PROOF_DSN requires an isolated test database")
        self.schema = sql.Identifier(f"lease_proof_{uuid4().hex}")
        self.first = psycopg.connect(url, autocommit=True)
        self.addCleanup(self.first.close)
        self.first.execute(sql.SQL("CREATE SCHEMA {}").format(self.schema))
        self.addCleanup(
            self.first.execute, sql.SQL("DROP SCHEMA {} CASCADE").format(self.schema)
        )
        self.second = psycopg.connect(url, autocommit=True)
        self.addCleanup(self.second.close)
        for conn in (self.first, self.second):
            conn.execute(sql.SQL("SET search_path TO {}").format(self.schema))
        self.first.execute(SCHEMA)
        self.job = uuid4()
        self.first.execute(
            "INSERT INTO lease_proof(job_id, pool) VALUES (%s, 'synthetic')",
            (self.job,),
        )

    def expire(self):
        self.first.execute(
            "UPDATE lease_proof SET expires_at = clock_timestamp() - interval '1 second'"
        )

    def make_params(self, lease_id, owner="pc-1", pool="synthetic"):
        return {
            "job_id": self.job,
            "pool": pool,
            "owner": owner,
            "lease_id": lease_id,
            "result_hash": sha256(b'{"synthetic":true}').digest(),
            "ttl": 60,
        }

    def test_claimant_race_and_pool_scope(self):
        self.assertIsNone(claim(self.second, "unassigned", "pc-2", 60)[1])
        with self.first.transaction():
            lease, row = claim(self.first, "synthetic", "pc-1", 60)
            self.assertEqual(row[:2], (self.job, 1))
            self.assertIsNone(claim(self.second, "synthetic", "pc-2", 60)[1])
        self.assertIsNone(claim(self.second, "synthetic", "pc-2", 60)[1])
        self.assertIsNone(
            self.second.execute(RENEW, self.make_params(lease, owner="pc-2")).fetchone()
        )
        self.assertIsNone(
            self.second.execute(
                RENEW, self.make_params(lease, pool="unassigned")
            ).fetchone()
        )
        self.assertIsNotNone(
            self.first.execute(RENEW, self.make_params(lease)).fetchone()
        )

    def test_expired_owner_cannot_renew_or_commit_and_replacement_can(self):
        first_id, _ = claim(self.first, "synthetic", "pc-1", 60)
        self.expire()
        current = self.make_params(first_id)
        self.assertIsNone(self.first.execute(RENEW, current).fetchone())
        self.assertIsNone(self.first.execute(FINISH, current).fetchone())
        second_id, row = claim(self.second, "synthetic", "pc-2", 60)
        self.assertEqual(row[:2], (self.job, 2))
        replacement = self.make_params(second_id, owner="pc-2")
        self.assertIsNone(self.first.execute(FINISH, current).fetchone())
        self.assertEqual(
            self.second.execute(FINISH, replacement).fetchone(), (self.job,)
        )
        self.assertEqual(
            self.second.execute(RETRY_FINISH, replacement).fetchone(), (self.job,)
        )
        self.assertIsNone(
            self.second.execute(
                RETRY_FINISH, {**replacement, "result_hash": b"changed"}
            ).fetchone()
        )

    def test_expired_final_attempt_fails_and_is_never_claimed_again(self):
        for attempt in range(1, 4):
            _, row = claim(self.first, "synthetic", "pc-1", 60)
            self.assertEqual(row[:2], (self.job, attempt))
            self.expire()
        self.assertIsNone(claim(self.second, "synthetic", "pc-2", 60)[1])
        self.assertEqual(
            self.first.execute(EXPIRE_FINAL, {"pool": "synthetic"}).rowcount, 1
        )
        self.assertEqual(
            self.first.execute("SELECT status FROM lease_proof").fetchone(), ("failed",)
        )


if __name__ == "__main__":
    unittest.main()
