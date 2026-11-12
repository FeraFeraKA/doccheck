"""Local rereading policy with separate extraction, review, and merge decisions.

The old identity module is frozen. Reader observations can improve a proposed
number or corroborate it, but can NEVER create a new automatic merge edge.
No expected answers, family IDs, filename patterns, or prefix dictionaries are
inputs. Tesseract preprocessing variants are stability checks of ONE engine.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import math
import re

from . import identity_v2 as v2

VERSION = "identity-v3.0.2"
TESS_CONFIDENCE_MIN = 80.0


def _complete_token(value):
    if not isinstance(value, str):
        return None
    # A structured field may legitimately start with N123/No123. Only № is
    # unambiguously a marker here; ASCII N must not be deleted from an ID.
    value = re.sub(r"^\s*№\s*", "", value)
    token = v2.number_token(value)
    return token if token and "?" not in token and "..." not in token else None


def _parse_text(text, allow_bare=False):
    """Parse observations, never repair letter/digit identities or fill gaps."""
    if not isinstance(text, str) or not text.strip():
        return {"value": None, "explicit_anchor": False, "reason": "no_reading"}
    lines = [{"text": line, "page": 1} for line in text.splitlines() if line.strip()]
    joined = " ".join(line["text"].strip() for line in lines)
    if allow_bare and re.match(r"^N(?:[oо]\.?)?\s*\d", joined, re.I):
        # In a bare source-line crop, N123 is ambiguous between a real prefix
        # and the number marker. Preserve it for review instead of erasing N.
        token = _complete_token(joined)
        return {"value": token, "explicit_anchor": False, "reason": "ascii_n_prefix_preserved"}
    candidates = v2.extract_number_candidates(lines)
    complete = [c for c in candidates if _complete_token(c["value"])]
    if len(candidates) == 1 and len(complete) == 1:
        return {"value": complete[0]["value"], "explicit_anchor": True,
                "reason": "number_anchor", "evidence": complete[0]["evidence"]}
    if candidates:
        return {"value": None, "explicit_anchor": False, "reason": "multiple_or_partial_numbers"}
    if allow_bare:
        token = _complete_token(joined)
        if token:
            return {"value": token, "explicit_anchor": False, "reason": "source_anchored_crop"}
    return {"value": None, "explicit_anchor": False, "reason": "no_number_anchor"}


def observations(baseline: dict, readers: dict | None) -> dict:
    """Validate identity and interpret one saved/local reader result envelope."""
    if readers and readers.get("source_sha256") != baseline.get("source_sha256"):
        raise ValueError("Reader observations belong to another source file")
    if readers and readers.get("id") != baseline.get("id"):
        raise ValueError("Reader observations belong to another document ID")
    readers = readers or {}
    crop = readers.get("crop") or {}
    anchored_crop = (crop.get("mode") == "single_line" and
                     len(baseline["number"].get("candidates", [])) == 1)
    roi = readers.get("qwen_roi") or {}
    prediction = roi.get("prediction") or {}
    roi_value = _complete_token(prediction.get("doc_number")) if not roi.get("error") else None
    quote = _parse_text(prediction.get("verbatim_line"), allow_bare=anchored_crop)
    quote_support = bool(roi_value and v2.norm(roi_value) == v2.norm(quote["value"]))
    # A proposed value without a matching quote is retained as an observation,
    # but cannot replace the field or become a corroborated key.
    roi_observation = {"value": roi_value, "quote_support": quote_support,
                       "explicit_anchor": quote.get("explicit_anchor", False),
                       "error": roi.get("error"), "verbatim_line": prediction.get("verbatim_line")}
    tesseract = []
    for row in readers.get("tesseract") or []:
        parsed = _parse_text(row.get("text"), allow_bare=anchored_crop) if not row.get("error") else {"value": None, "explicit_anchor": False}
        tesseract.append({"variant": row.get("variant"), **parsed,
                          "mean_confidence": row.get("mean_confidence"), "error": row.get("error"),
                          "text": row.get("text")})
    variants = {row["variant"]: row for row in tesseract}
    stable = (len(tesseract) == 2 and set(variants) == {"original", "gray2x"} and
              all(row["value"] and not row["error"] for row in tesseract) and
              len({v2.norm(row["value"]) for row in tesseract}) == 1)
    tess_value = variants["original"]["value"] if stable else None
    confidence_ok = stable and all(isinstance(row.get("mean_confidence"), (int, float)) and
                                   math.isfinite(row["mean_confidence"]) and
                                   TESS_CONFIDENCE_MIN <= row["mean_confidence"] <= 100 for row in tesseract)
    return {"roi": roi_observation, "tesseract": tesseract, "tesseract_stable": bool(stable),
            "tesseract_value": tess_value, "confidence_ok": bool(confidence_ok),
            "source_anchored_crop": anchored_crop,
            "crop": crop, "selected": bool(readers.get("selected"))}


def _base(baseline, arm):
    result = deepcopy(baseline)
    result["version"] = VERSION
    result["arm"] = arm
    result["baseline_identity"] = deepcopy(baseline)
    result["number"]["manual_review_required"] = baseline["number"].get("usable_value") is None
    result["number"]["verification"] = "existing_source_policy" if baseline["number"].get("usable_value") else "unverified"
    return result


def evaluate_arms(baseline_record: dict, joined_reader_row: dict | None = None) -> dict:
    """Return immutable-baseline, isolated-reader, and integrated outcomes."""
    base = baseline_record
    arms = {name: _base(base, name) for name in ("v2_1", "roi_only", "tess_only", "combined")}
    obs = observations(base, joined_reader_row)
    for record in arms.values():
        record["reread"] = deepcopy(obs)
    # Selection never depends on evaluation labels. Existing usable values are
    # not overwritten, even if a caller supplies extra diagnostic observations.
    if base["acquisition"] != "scan" or base["number"].get("usable_value") is not None or not obs["selected"]:
        return arms
    roi_value = obs["roi"]["value"] if obs["roi"]["quote_support"] else None
    tess_value = obs["tesseract_value"]
    for arm, value in (("roi_only", roi_value), ("tess_only", tess_value)):
        if value:
            arms[arm]["number"].update(value=value, status=arm + "_proposal",
                                       issues=v2.number_issues(value, "scan"))
    combined = arms["combined"]["number"]
    proposal = roi_value or tess_value or base["number"].get("value")
    combined.update(value=proposal, usable_value=None, status="reread_unverified",
                    issues=v2.number_issues(proposal, "scan"), manual_review_required=True)
    agreement = bool(roi_value and tess_value and v2.norm(roi_value) == v2.norm(tess_value))
    explicit_anchors = obs["roi"]["explicit_anchor"] and all(x["explicit_anchor"] for x in obs["tesseract"])
    source_anchor = obs["source_anchored_crop"] or explicit_anchors
    reasons = []
    if not roi_value:
        reasons.append("no_quote_supported_qwen_number")
    if not obs["tesseract_stable"]:
        reasons.append("tesseract_preprocessing_disagreement_or_missing")
    if not agreement:
        reasons.append("independent_reader_disagreement_or_missing")
    if not obs["confidence_ok"]:
        reasons.append("tesseract_confidence_below_fixed_threshold")
    if not source_anchor:
        reasons.append("document_number_anchor_unverified")
    if agreement and obs["confidence_ok"] and source_anchor and not combined["issues"]:
        combined.update(usable_value=proposal, status="cross_engine_corroborated",
                        verification="two_engines_and_preprocessing_stability",
                        manual_review_required=False)
    combined["issues"] += reasons
    combined["baseline_value"] = base["number"].get("value")
    combined["baseline_issues"] = base["number"].get("issues", [])
    combined["reader_agreement_is_not_proof"] = True
    return arms


def compare_documents(a: dict, b: dict) -> dict:
    """A reread can affect candidates, never authorize a new automatic merge."""
    decision = v2.compare_documents(a, b)
    original = v2.compare_documents(a.get("baseline_identity", a), b.get("baseline_identity", b))
    if decision["auto_merge"] and not original["auto_merge"]:
        decision.update(status="candidate", auto_merge=False)
        decision["reasons"].append("rereading_cannot_authorize_a_new_merge")
    uncertain_change = any(
        r["number"].get("usable_value") is None and
        v2.norm(r["number"].get("value")) != v2.norm(r.get("baseline_identity", r)["number"].get("value"))
        for r in (a, b))
    if uncertain_change and ((original["status"] == "conflict" and decision["status"] != "conflict") or
                             (original["status"] == "candidate" and decision["status"] not in {"candidate", "conflict", "duplicate"})):
        # A suggestion without verification is not evidence that an existing
        # amount/version conflict or possible duplicate has been resolved.
        decision = {**original, "reasons": original["reasons"] + ["unverified_reread_cannot_clear_existing_review"],
                    "reread_suggested_status": decision["status"]}
    return decision


def group_documents(records: list[dict]) -> dict:
    """Only proof-backed edges form actual groups; review edges never propagate."""
    by_id = {r["id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("Document IDs must be unique")
    parent = {k: k for k in by_id}
    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    pairs = []
    for a, b in combinations(records, 2):
        p = compare_documents(a, b)
        if p["auto_merge"]:
            parent[root(b["id"])] = root(a["id"])
        if p["status"] in {"duplicate", "candidate", "conflict"}:
            pairs.append(p)
    groups = {}
    for k in sorted(by_id):
        groups.setdefault(root(k), []).append(k)
    return {"groups": list(groups.values()), "review_pairs": pairs, "files_deleted": False,
            "candidate_edges_used_for_clustering": False, "new_auto_edges_from_rereading": False}


def fact_review_queue(records: list[dict]) -> dict:
    """Keep source fact conflicts visible even without a number or pair review."""
    flagged = sorted((r for r in records if r.get("fact_conflicts")), key=lambda r: r["id"])
    cards = [{"document_ids": [r["id"]], "kind": "fact_review",
              "fields": sorted(r["fact_conflicts"]), "correction_propagates": False}
             for r in flagged]
    return {"fact_review_document_ids": [r["id"] for r in flagged], "fact_cards": cards}


def review_queue(records: list[dict]) -> dict:
    """UI cards are not duplicate groups or measured human decisions.

    A candidate component can share one comparison card only when every pair is
    compatible. Candidate chains are split; no correction propagates to peers.
    """
    by_id = {r["id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("Document IDs must be unique")
    flagged = {r["id"] for r in records if r["number"].get("manual_review_required", r["number"].get("usable_value") is None)}
    neighbors = {k: set() for k in by_id}
    review_pairs, compatible = [], set()
    for a, b in combinations(records, 2):
        d = compare_documents(a, b)
        edge = tuple(sorted((a["id"], b["id"])))
        if d["status"] in {"duplicate", "candidate"}:
            compatible.add(edge)
            neighbors[a["id"]].add(b["id"])
            neighbors[b["id"]].add(a["id"])
        if d["status"] in {"candidate", "conflict"}:
            review_pairs.append(d)
    seen, cards = set(), []
    for first in sorted(by_id):
        if first in seen:
            continue
        stack, component = [first], set()
        while stack:
            current = stack.pop()
            if current not in component:
                component.add(current)
                stack.extend(neighbors[current] - component)
        seen.update(component)
        pending = sorted(component & flagged)
        if not pending:
            continue
        clique = all(tuple(sorted(pair)) in compatible for pair in combinations(component, 2))
        chunks = [pending] if clique else [[k] for k in pending]
        for ids in chunks:
            cards.append({"document_ids": ids, "comparison_ids": sorted(component) if clique else ids,
                          "kind": "number_review", "correction_propagates": False,
                          "is_duplicate_group": False})
    return {"number_review_document_ids": sorted(flagged), "number_cards": cards,
            **fact_review_queue(records),
            "identity_review_pairs": review_pairs,
            "number_review_documents": len(flagged), "number_review_cards": len(cards),
            "identity_review_pair_count": len(review_pairs),
            "actual_human_actions_measured": False, "all_unverified_numbers_are_visible": True}
