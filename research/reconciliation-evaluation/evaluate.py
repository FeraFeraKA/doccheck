"""Score separately supplied indicator expectations and observations."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Literal, cast

type Key = tuple[str, str]
type Status = Literal["verified", "discrepancy", "unverified"]
type Split = Literal["development", "holdout"]

STATUSES = ("verified", "discrepancy", "unverified")
SPLITS = ("development", "holdout")


class InputError(ValueError):
    """Input error whose message never contains source values."""


def _rows(data: object, fields: set[str]) -> list[dict[str, object]]:
    if not isinstance(data, list) or any(
        not isinstance(row, dict) or row.keys() != fields for row in data
    ):
        raise InputError("Expected a JSON array of rows with the documented fields")
    return data


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise InputError(
            "Identifiers must be nonempty strings without surrounding whitespace"
        )
    return value


def _status(value: object) -> Status:
    if value not in STATUSES:
        raise InputError("Invalid reconciliation status")
    return cast(Status, value)


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def evaluate(
    expectations: object, observations: object, *, split: Split
) -> dict[str, object]:
    if split not in SPLITS:
        raise InputError("Invalid evaluation split")

    expected: dict[Key, Status] = {}
    group_splits: dict[str, object] = {}
    keys: set[Key] = set()
    case_groups: dict[str, str] = {}
    for row in _rows(
        expectations,
        {"case_id", "indicator_id", "origin_group", "split", "expected_status"},
    ):
        key = (_text(row["case_id"]), _text(row["indicator_id"]))
        group = _text(row["origin_group"])
        row_split = row["split"]
        status = _status(row["expected_status"])
        if row_split not in SPLITS:
            raise InputError("Invalid split in expectations")
        if case_groups.setdefault(key[0], group) != group:
            raise InputError("A case belongs to multiple origin groups")
        if group_splits.setdefault(group, row_split) != row_split:
            raise InputError("An origin group crosses evaluation splits")
        if key in keys:
            raise InputError("Duplicate key in expectations")
        keys.add(key)
        if row_split == split:
            expected[key] = status

    observed: dict[Key, tuple[Status, bool]] = {}
    for row in _rows(
        observations, {"case_id", "indicator_id", "status", "has_evidence"}
    ):
        key = (_text(row["case_id"]), _text(row["indicator_id"]))
        has_evidence = row["has_evidence"]
        if not isinstance(has_evidence, bool):
            raise InputError("has_evidence must be a boolean")
        if key not in expected or key in observed:
            raise InputError(
                "Observation key is duplicate or absent from the selected split"
            )
        observed[key] = (_status(row["status"]), has_evidence)

    pairs = Counter(
        (status, observed.get(key, ("missing", False))[0])
        for key, status in expected.items()
    )
    actual = Counter(status for status, _ in observed.values())
    true_discrepancies = sum(status == "discrepancy" for status in expected.values())
    true_positives = pairs["discrepancy", "discrepancy"]
    false_alarms = pairs["verified", "discrepancy"]
    false_confirmations = pairs["discrepancy", "verified"]
    unsupported_confirmations = pairs["unverified", "verified"]
    definitive = actual["verified"] + actual["discrepancy"]
    definitive_with_evidence = sum(
        present and status != "unverified" for status, present in observed.values()
    )
    total = len(expected)
    return {
        "split": split,
        "target_rows": total,
        "origin_groups": sum(value == split for value in group_splits.values()),
        "true_discrepancies": true_discrepancies,
        "missing_rows": total - len(observed),
        "status_matrix": {
            wanted: {
                actual_status: pairs[wanted, actual_status]
                for actual_status in (*STATUSES, "missing")
            }
            for wanted in STATUSES
        },
        "metrics": {
            "discrepancy_precision": _ratio(
                true_positives, true_positives + false_alarms
            ),
            "discrepancy_recall": _ratio(true_positives, true_discrepancies),
            "false_confirmation_rate": _ratio(
                false_confirmations + unsupported_confirmations, actual["verified"]
            ),
            "false_alarm_rate": _ratio(
                false_alarms, sum(status == "verified" for status in expected.values())
            ),
            "unverified_rate": _ratio(actual["unverified"], total),
            "response_coverage": _ratio(len(observed), total),
            "definitive_coverage": _ratio(definitive, total),
            "definitive_evidence_rate": _ratio(definitive_with_evidence, definitive),
        },
        "actual_discrepancies_on_expected_unverified": pairs[
            "unverified", "discrepancy"
        ],
    }


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(items)
    if len(result) != len(items):
        raise InputError("Duplicate JSON object field")
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise InputError("Unable to read an input as UTF-8 JSON") from None


class EvaluationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse includes raw arguments in some errors.
        self.exit(2, "Invalid command-line arguments. Use --help.\n")


def main() -> None:
    parser = EvaluationArgumentParser(prog="evaluate.py", description=__doc__)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--split", choices=SPLITS, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(
            _read_json(args.expectations),
            _read_json(args.observations),
            split=args.split,
        )
    except InputError as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
