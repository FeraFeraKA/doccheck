"""The versioned contract shared by the document worker, API, and UI."""

from .result import RESULT_SCHEMA_VERSION, CheckJob, CheckResult

__all__ = ["RESULT_SCHEMA_VERSION", "CheckJob", "CheckResult"]
