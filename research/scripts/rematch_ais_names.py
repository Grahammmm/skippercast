"""Re-match the charter registry against the AIS static names already held (AISMATCH-2).

Sits beside ``join_fleet_registries.py`` (AISBULK-1) and reuses its loaders, normalisation, evidence vocabulary and
contradiction checks; it does not build a second joiner. AISBULK-1 resolves a vessel through licence data; this tool
only asks the cheaper question first: which registry names does an AIS static already carry that the matching rule
missed? It adds a ladder of name-folding rules, applied to both sides, and reports for every rule how many registry
vessels it newly matches cleanly and how many it makes ambiguous.

**A name never resolves.** Every new pair is a ``candidate``. It is ``corroborated`` only when (a) nothing contradicts
it (US MMSI, charter-plausible ship type, US-format call sign), (b) it is not ambiguous (one MMSI for the vessel, the
MMSI claimed by no other registry vessel, the registry name not shared by another registry vessel) and (c) an
independent fact backs it: the MMSI was observed in the vessel's home-port geofence (1+ days for the exact-fold rules;
3+ days for the weaker prefix, operator-text and spelling rules), or its call sign sits on a licence of the same
MMSI and name in the AISBULK-1 private join. The registry carries no vessel length, so a length check is not
available; the AIS length is shown for the reviewer. Nothing is promoted: no watch list, registry or rights value is
written, and the AIS state is opened ``mode=ro``.

**The trap.** Two different boats can share a name (PATRIOT: one MMSI at two ports). A looser rule makes that worse,
so every rule is reported with its clean and its ambiguous count, and an ambiguous vessel is never corroborated.

Run (repository root)::

    python research/scripts/rematch_ais_names.py --resolved RUN/resolved.jsonl --state SNAPSHOT/state.sqlite \\
        --out PRIVATE_DIR [--prior-join AISBULK/join.json]

Standard output is counts only. ``--out`` (outside the repository) receives ``pairs.json`` and ``pairs.md`` with
MMSIs and call signs (private) and ``pr-table.md`` without them (for the PR body).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Callable, Mapping
import unicodedata

from skippercast.fleet.normalize import roman_to_int

from research.scripts import join_fleet_registries as J

__all__ = ["tokens", "RULES", "rule_keys", "rematch", "main"]

# ---- name folding --------------------------------------------------------------------------------------

PREFIX = re.compile(r"\b[FM][/.]?V\.?(?=\s)", re.I)
NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN FIFTEEN SIXTEEN "
    "SEVENTEEN EIGHTEEN NINETEEN TWENTY".split())}
NUMBER_WORDS.pop("ZERO")
NUMBER_MARKERS = frozenset({"NO", "NUM", "NUMBER", "NR"})
GENERATIONAL = frozenset({"JR", "SR", "JUNIOR", "SENIOR"})
ARTICLES = frozenset({"THE", "LA", "EL", "LOS", "LAS", "LE", "L", "OF", "A"})
ABBREVIATIONS = {"CAPT": "CAPTAIN", "CPT": "CAPTAIN", "CAPN": "CAPTAIN", "CAP": "CAPTAIN", "ST": "SAINT",
                 "BRO": "BROTHER", "BROS": "BROTHERS", "BRO'S": "BROTHERS", "DR": "DOCTOR", "MT": "MOUNT",
                 "FT": "FORT", "SPT": "SPORT", "FSH": "FISHING", "MS": "MISS", "MR": "MISTER"}
OPERATOR_WORDS = frozenset({"SPORTFISHING", "SPORTSFISHING", "SPORT", "SPORTS", "FISHING", "CHARTER", "CHARTERS",
                            "BOAT", "BOATS", "LANDING", "CRUISES", "TOURS", "LLC", "INC"})
PORT_WORDS = frozenset({"SD", "LB", "SB", "SF", "LA", "MDR", "HMB", "OXNARD", "VENTURA", "BERKELEY", "SAUSALITO",
                        "EMERYVILLE", "ALAMEDA", "MONTEREY", "OCEANSIDE", "REDONDO", "NEWPORT", "DANA", "POINT",
                        "SAN", "DIEGO", "PEDRO", "FRANCISCO", "LONG", "BEACH", "SANTA", "CRUZ", "BARBARA", "MORRO",
                        "BAY", "BODEGA", "NOYO", "EUREKA", "MISSION", "MARINA", "REY", "PILLAR"})
ROMAN_TOKEN = re.compile(r"[IVX]{1,4}\.?")
FULL_AIS = J.AIS_NAME_MAX


def tokens(name: str | None) -> list[str]:
    """Upper-case ASCII tokens: parenthetical notes and FV/MV prefixes dropped, ``&`` spelled AND, hyphens and
    punctuation (apostrophes kept inside a token) turned into spaces."""
    text = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c)).upper()
    text = re.sub(r"\([^)]*\)?", " ", text)
    text = PREFIX.sub(" ", text + " ")
    text = text.replace("&", " AND ").replace("\u2019", "'").replace("`", "'")
    return re.sub(r"[^A-Z0-9' ]", " ", text).split()


def _digits_trailing(toks: list[str]) -> list[str]:
    """The registry rule: a trailing roman numeral becomes digits."""
    if len(toks) > 1 and ROMAN_TOKEN.fullmatch(toks[-1]):
        number = roman_to_int(toks[-1].rstrip("."))
        if number is not None:
            return toks[:-1] + [str(number)]
    return toks


def _key(toks: list[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", "".join(toks))


def _lead(toks: list[str]) -> list[str]:
    while len(toks) > 1 and toks[0] in ("THE", "FV", "MV"):
        toks = toks[1:]
    return toks


def r_ampersand(t):    # "X & Y" / "X AND Y" / "X N Y" -> same
    return [x for x in t if x not in ("AND", "N", "'N'", "&")]


def r_possessive(t):   # "NINA'S", "NINAS" -> NINA (trailing S of the last word; plural/possessive)
    out = [re.sub(r"'S?$", "", x) if "'" in x else x for x in t]
    if out and len(out[-1]) > 3 and out[-1].endswith("S") and not out[-1].endswith("SS"):
        out[-1] = out[-1][:-1]
    return out


def r_generational(t):
    return [x.rstrip(".") for x in t if x.rstrip(".") not in GENERATIONAL]


def r_numerals(t):     # TWO -> 2; II -> 2 anywhere; "No. 1", "Number 1" -> 1
    out = []
    for x in t:
        if x in NUMBER_MARKERS:
            continue
        if x in NUMBER_WORDS:
            out.append(NUMBER_WORDS[x])
        elif ROMAN_TOKEN.fullmatch(x) and roman_to_int(x.rstrip(".")) and len(t) > 1:
            out.append(str(roman_to_int(x.rstrip("."))))
        else:
            out.append(x)
    return out


def r_articles(t):
    return [x for x in t if x not in ARTICLES] or t


def r_abbreviations(t):
    return [ABBREVIATIONS.get(x, x) for x in t]


def r_operator(t):     # the landing's operator or port text around a boat name
    kept = [x for x in t if x not in OPERATOR_WORDS and x not in PORT_WORDS]
    # what is left must still be a name: 6+ characters (one generic word like SPIRIT is not an identity)
    return kept if len(_key(kept)) >= 6 and kept != t else t


def r_combined(t):
    for fn in (r_ampersand, r_generational, r_numerals, r_articles, r_abbreviations, r_possessive):
        t = fn(t)
    return t


# (rule id, function, strength). Strength sets the corroboration bar: "exact" folds need 1+ home-port days,
# "weak" rules need 3+ (the AISBULK-1 lead standard).
RULES: tuple[tuple[str, Callable[[list[str]], list[str]], str], ...] = (
    ("R1-ampersand-and", r_ampersand, "exact"),
    ("R2-generational-jr-sr", r_generational, "exact"),
    ("R3-numerals-words-roman", r_numerals, "exact"),
    ("R4-articles", r_articles, "exact"),
    ("R5-abbreviations", r_abbreviations, "exact"),
    ("R6-possessive-plural-s", r_possessive, "exact"),
    ("R7-combined-folds", r_combined, "exact"),
    ("R8-operator-or-port-text", lambda t: r_operator(r_ampersand(t)), "weak"),
)
EXTRA_RULES = (("R9-token-prefix", "weak"), ("R10-one-letter-spelling", "weak"))
RULE_ORDER = [r[0] for r in RULES] + [r[0] for r in EXTRA_RULES]
STRENGTH = {**{r[0]: r[2] for r in RULES}, **dict(EXTRA_RULES)}


def rule_keys(name: str | None) -> dict[str, str]:
    """The comparison key of a name under every rule (and ``base``: the AISBULK-1 rule)."""
    t = tokens(name)
    out = {"base": J.norm(name)}
    for rid, fn, _ in RULES:
        out[rid] = _key(_digits_trailing(fn(_lead(list(t)))))
    out["combined-tokens"] = " ".join(_digits_trailing(r_operator(r_combined(_lead(list(t))))))
    out["plain-tokens"] = " ".join(_digits_trailing(r_ampersand(_lead(list(t)))))   # for the prefix rule
    return out


# ---- the re-match --------------------------------------------------------------------------------------

def _prefix_match(a: str, b: str) -> bool:
    """Token-boundary prefix: one name is the whole leading part of the other, the shorter at least six
    characters, and what is left over holds no number or generational word (a different numbered boat)."""
    ta, tb = a.split(), b.split()
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if short == long or long[:len(short)] != short or len(_key(short)) < (6 if len(short) > 1 else 8):
        return False
    return not any(x.isdigit() or x in NUMBER_WORDS or x in NUMBER_MARKERS or x in GENERATIONAL or ROMAN_TOKEN.fullmatch(x) for x in long[len(short):])


def _one_letter(a: str, b: str) -> bool:
    return (len(a) == len(b) >= 7 and sum(x != y for x, y in zip(a, b)) == 1
            and all(x.isalpha() and y.isalpha() for x, y in zip(a, b) if x != y))


def _hits(rows, statics):
    """vessel_id -> {mmsi -> earliest rule}, for every rule beyond the AISBULK-1 base rule."""
    skeys = {m: rule_keys(s.name) for m, s in statics.items() if s.name}
    longs = {m for m, s in statics.items() if s.name and s.truncated}
    index: dict[str, dict[str, set]] = {rid: defaultdict(set) for rid, _, _ in RULES}
    base_index: dict[str, set] = defaultdict(set)
    for m, k in skeys.items():
        base_index[k["base"]].add(m)
        for rid, _, _ in RULES:
            if k[rid]:
                index[rid][k[rid]].add(m)
    out: dict[str, dict[str, str]] = {}
    base: dict[str, set] = {}
    for r in rows:
        vk = rule_keys(r["name"])
        key = vk["base"]
        have = set(base_index.get(key, ())) | {m for m in longs if J.same_name(key, skeys[m]["base"], True)}
        base[r["vessel_id"]] = have
        found: dict[str, str] = {}
        for rid, _, _ in RULES:
            if len(vk[rid]) < 3:
                continue
            for m in index[rid].get(vk[rid], ()):
                if m not in have:
                    found.setdefault(m, rid)
        for m, k in skeys.items():
            if m in have or m in found:
                continue
            if _prefix_match(vk["plain-tokens"], k["plain-tokens"]):
                found[m] = "R9-token-prefix"
            elif _one_letter(vk["R7-combined-folds"], k["R7-combined-folds"]):
                found[m] = "R10-one-letter-spelling"
        out[r["vessel_id"]] = found
    return out, base


def _licence_index(prior_join: Path | None) -> dict[tuple[str, str], dict]:
    """Licences already read by AISBULK-1 (private join.json), by (MMSI, call sign). Partial by design: only the
    licences that run touched; it is not a fresh FCC lookup."""
    out: dict[tuple[str, str], dict] = {}
    if prior_join is None:
        return out
    data = json.loads(Path(prior_join).read_text())
    lics = [c["licence"] for r in data["rows"] for c in r["candidates"] if c.get("licence")]
    lics += [l for c in data.get("call_signs", []) for l in c.get("licences", [])]
    for l in lics:
        if l.get("mmsi") and l.get("call_sign"):
            out[(str(l["mmsi"]), l["call_sign"])] = l
    return out


def rematch(registry: list[dict], statics: Mapping[str, J.Static], presence: Mapping[str, Counter],
            licences: Mapping[tuple[str, str], dict] | None = None) -> dict:
    """The measured re-match: baseline counts, every new pair with its rule and corroboration, ambiguities per
    rule, and the vessels still unmatched. Pure: reads its arguments only."""
    licences = licences or {}
    hits, base = _hits(registry, statics)
    by_id = {r["vessel_id"]: r for r in registry}
    legacy_index = defaultdict(set)
    for s in statics.values():
        legacy_index[J.legacy_norm(s.name)].add(s.mmsi)
    legacy = sum(1 for r in registry if J.legacy_norm(r["name"]) and legacy_index.get(J.legacy_norm(r["name"])))
    matched_base = {v for v, m in base.items() if m}
    # claims: how many registry vessels each MMSI is matched to under any rule (the PATRIOT trap)
    base_claims: dict[str, set] = defaultdict(set)
    for v, m in base.items():
        for x in m:
            base_claims[x].add(v)
    claims: dict[str, set] = defaultdict(set, {k: set(s) for k, s in base_claims.items()})
    for v, found in hits.items():
        for x in found:
            claims[x].add(v)
    name_share = Counter(rule_keys(r["name"])["base"] for r in registry)

    def base_is_ambiguous(v):
        return (len(base[v]) > 1 or any(len(base_claims[m]) > 1 for m in base[v])
                or name_share[rule_keys(by_id[v]["name"])["base"]] > 1)
    base_ambiguous = sum(1 for v in matched_base if base_is_ambiguous(v))
    pairs, vessels, existing = [], {}, {}
    # Every registry row is audited, not only the newly reached ones: a rule can also add a second MMSI to a
    # vessel the AISBULK-1 rule already matched, and that rival is a cost of the rule.
    for vid, found in hits.items():
        if not found:
            continue
        r = by_id[vid]
        is_base = vid in matched_base
        ranked = sorted(found.items(), key=lambda kv: RULE_ORDER.index(kv[1]))
        rule = ranked[0][1]
        why = []
        if is_base:
            why.append(f"adds {len(found)} MMSI(s) to a vessel the AISBULK-1 rule already matched")
        elif len(found) > 1:
            why.append(f"{len(found)} MMSIs match")
        if any(len(claims[m]) > 1 for m in found):
            why.append("an MMSI is also matched to another registry vessel")
        if name_share[rule_keys(r["name"])["base"]] > 1:
            why.append("the registry has this name at more than one port")
        entry = {"vessel_id": vid, "name": r["name"], "port_id": r["port_id"], "rule": rule,
                 "ambiguous": bool(why), "ambiguity": why, "mmsis": sorted(found)}
        if is_base:
            entry["base_ambiguous_before"] = base_is_ambiguous(vid)
            existing[vid] = entry
        else:
            vessels[vid] = entry
        for i, (m, prule) in enumerate(ranked):
            role = "existing-base-rival" if is_base else "primary" if i == 0 else "secondary-rival"
            s = statics[m]
            days = presence.get(m, Counter())
            home = days.get(r["port_id"], 0)
            conflicts = []
            if m[:3] not in J.US_MIDS:
                conflicts.append(f"non-us-mmsi(mid {m[:3]})")
            if s.ship_type not in (None, *J.CHARTER_TYPES, *J.UNSPECIFIC_TYPES):
                conflicts.append(f"ais-ship-type-{s.ship_type}")
            call = J._alnum(s.call_sign) if s.call_sign else ""
            if call and not J.US_CALL.fullmatch(call):
                conflicts.append("call-sign-not-us-format")
            lic = licences.get((m, call)) if call else None
            lic_ok = bool(lic and lic.get("status") == "active"
                          and rule_keys(lic["name"])["R7-combined-folds"] == rule_keys(r["name"])["R7-combined-folds"])
            need = 1 if STRENGTH[prule] == "exact" else 3
            if entry["ambiguous"]:
                status = "ambiguous"
            elif conflicts:
                status = "contradicted"
            elif lic_ok or home >= need:
                status = "corroborated"
            else:
                status = "candidate"
            support = ([f"call sign on active licence of same MMSI and name (AISBULK-1 private join)"] if lic_ok else []) \
                + ([f"home-port presence {home}d"] if home else [])
            pairs.append({"vessel_id": vid, "our_name": r["name"], "port_id": r["port_id"], "ais_name": s.name,
                          "mmsi": m, "call_sign": s.call_sign, "ship_type": s.ship_type, "length_m": s.length_m,
                          "rule": prule, "role": role, "status": status, "ambiguity": why, "conflicts": conflicts,
                          "collides_with_other_vessel": len(claims[m]) > 1,
                          "home_port_days": home, "other_ports": {p: d for p, d in days.items() if p != r["port_id"]},
                          "support": support})
    per_rule = {}
    for rid in RULE_ORDER:
        vs = [v for v in vessels.values() if v["rule"] == rid]
        ps = [p for p in pairs if p["rule"] == rid]
        by_role = Counter(p["role"] for p in ps)
        # cost = every pair this rule contributed to an ambiguous vessel, whichever rule reached it first
        cost = [p for p in ps if p["ambiguity"]]
        per_rule[rid] = {"vessels_newly_matched": len(vs), "clean": sum(1 for v in vs if not v["ambiguous"]),
                         "ambiguous": sum(1 for v in vs if v["ambiguous"]),
                         "candidate": sum(1 for p in ps if p["status"] == "candidate"),
                         "corroborated": sum(1 for p in ps if p["status"] == "corroborated"),
                         "contradicted": sum(1 for p in ps if p["status"] == "contradicted"),
                         "pairs": len(ps),
                         "rival_pairs_on_existing_vessels": by_role["existing-base-rival"],
                         "existing_vessels_given_a_rival": len({p["vessel_id"] for p in ps
                                                                if p["role"] == "existing-base-rival"}),
                         "secondary_rival_pairs_on_new_vessels": by_role["secondary-rival"],
                         "pairs_colliding_with_another_vessel": sum(1 for p in ps if p["collides_with_other_vessel"]),
                         "ambiguity_cost_pairs": len(cost),
                         "ambiguity_cost_vessels": len({p["vessel_id"] for p in cost})}
    # a vessel is corroborated when exactly one pair is and the vessel is not ambiguous
    vstatus = {}
    for vid, v in vessels.items():
        statuses = [p["status"] for p in pairs if p["vessel_id"] == vid]
        vstatus[vid] = ("ambiguous" if v["ambiguous"] else "corroborated" if "corroborated" in statuses
                        else "contradicted" if statuses and all(s == "contradicted" for s in statuses)
                        else "candidate")
    unmatched = _unmatched(registry, matched_base | set(vessels), statics, presence)
    counts = {
        "registry_vessels": len(registry), "ais_statics": len(statics),
        "ais_distinct_names": len({J.norm(s.name) for s in statics.values() if s.name}),
        "matched_first_pass_rule": legacy, "matched_aisbulk1_rule": len(matched_base),
        "matched_aisbulk1_rule_ambiguous": base_ambiguous,
        "newly_matched_vessels": len(vessels), "matched_after": len(matched_base) + len(vessels),
        "newly_matched_clean": sum(1 for v in vessels.values() if not v["ambiguous"]),
        "newly_matched_ambiguous": sum(1 for v in vessels.values() if v["ambiguous"]),
        "new_pairs": sum(1 for p in pairs if p["role"] != "existing-base-rival"),
        "rival_pairs_on_existing_vessels": sum(1 for p in pairs if p["role"] == "existing-base-rival"),
        "existing_vessels_given_a_rival": len(existing),
        "existing_vessels_newly_ambiguous": sum(1 for e in existing.values() if not e["base_ambiguous_before"]),
        "all_pairs_added": len(pairs),
        "vessels_by_final_status": dict(sorted(Counter(vstatus.values()).items())),
        "resolved_by_this_tool": 0, "per_rule": per_rule,
        "unmatched_after": len(unmatched), "unmatched_by_cause": dict(sorted(Counter(u["cause"] for u in unmatched).items())),
    }
    return {"counts": counts, "pairs": pairs, "vessels": list(vessels.values()),
            "existing_vessels_with_rivals": list(existing.values()), "vessel_status": vstatus,
            "unmatched": unmatched}


STOP = frozenset(OPERATOR_WORDS | PORT_WORDS | ARTICLES | {"SEA", "BLUE", "LADY", "MISS", "CAPTAIN", "AND", "BAY",
                                                            "OCEAN", "STAR", "KING", "QUEEN", "SPIRIT", "PACIFIC"})


def _unmatched(registry, matched: set, statics, presence) -> list[dict]:
    """Registry vessels with no AIS name match under any rule, each with the likely cause."""
    comb = {m: rule_keys(s.name)["combined-tokens"] for m, s in statics.items() if s.name}
    tok_count: Counter = Counter()
    by_tok: dict[str, set] = defaultdict(set)
    for m, c in comb.items():
        for x in set(c.split()):
            tok_count[x] += 1
            by_tok[x].add(m)
    out = []
    for r in registry:
        if r["vessel_id"] in matched:
            continue
        kind = J.name_kind(r["name"])
        k = rule_keys(r["name"])
        if kind != "vessel":
            out.append({"vessel_id": r["vessel_id"], "name": r["name"], "port_id": r["port_id"],
                        "cause": "no-vessel-name-in-registry", "near": []})
            continue
        compact = _key(k["combined-tokens"].split())
        near = set()
        for m, c in comb.items():
            if difflib.SequenceMatcher(None, compact, _key(c.split())).ratio() >= 0.85 and len(compact) >= 5:
                near.add(m)
        for x in k["combined-tokens"].split():
            if len(x) >= 5 and x not in STOP and not x.isdigit() and tok_count[x] <= 3:
                near |= by_tok.get(x, set())
        out.append({"vessel_id": r["vessel_id"], "name": r["name"], "port_id": r["port_id"],
                    "cause": "name-not-reconciled" if near else "absent-from-statics",
                    "near": sorted(near)})
    return out


def port_table(registry, rep, presence, statics) -> list[dict]:
    """Per home port: vessels, matched before/after, unmatched with cause, and a receiver-coverage proxy
    (MMSIs seen in the port geofence whose AIS static carries no name)."""
    new = {v["vessel_id"] for v in rep["vessels"]}
    after_un = {u["vessel_id"]: u for u in rep["unmatched"]}
    ports = sorted({r["port_id"] for r in registry})
    seen = defaultdict(set)
    for m, c in presence.items():
        for p in c:
            seen[p].add(m)
    rows = []
    for p in ports:
        rs = [r for r in registry if r["port_id"] == p]
        un = [after_un[r["vessel_id"]] for r in rs if r["vessel_id"] in after_un]
        c = Counter(u["cause"] for u in un)
        nameless = sum(1 for m in seen[p] if not (statics.get(m) and statics[m].name))
        rows.append({"port_id": p, "vessels": len(rs), "newly_matched": sum(1 for r in rs if r["vessel_id"] in new),
                     "unmatched": len(un), "absent_from_statics": c["absent-from-statics"],
                     "name_not_reconciled": c["name-not-reconciled"],
                     "no_vessel_name": c["no-vessel-name-in-registry"],
                     "mmsis_seen_in_port": len(seen[p]), "seen_in_port_without_static_name": nameless})
    return rows


# ---- output --------------------------------------------------------------------------------------------

def _cell(v) -> str:
    return str(v if v not in (None, "", []) else "-").replace("|", "/").replace("\n", " ")


def pr_table(rep: dict) -> str:
    """The new-pair table for a PR body: no MMSIs and no call signs (only whether one is broadcast)."""
    lines = ["| Our name | Port | AIS name | Call sign broadcast | Type | Length m | Rule | Role | Home-port days | Status |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in sorted(rep["pairs"], key=lambda p: (RULE_ORDER.index(p["rule"]), p["port_id"], p["our_name"])):
        lines.append("| " + " | ".join(_cell(x) for x in (
            p["our_name"], p["port_id"], p["ais_name"], "yes" if p["call_sign"] else "no", p["ship_type"],
            p["length_m"], p["rule"], p["role"], p["home_port_days"],
            p["status"] + (f" ({'; '.join(p['ambiguity'])})" if p["ambiguity"] else "")
            + (f" [{'; '.join(p['conflicts'])}]" if p["conflicts"] else ""))) + " |")
    return "\n".join(lines) + "\n"


def private_table(rep: dict) -> str:
    lines = ["| Our name | Port | AIS name | MMSI | Call sign | Type | Length m | Rule | Role | Status | Support | Other ports |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in sorted(rep["pairs"], key=lambda p: (RULE_ORDER.index(p["rule"]), p["port_id"], p["our_name"])):
        lines.append("| " + " | ".join(_cell(x) for x in (
            p["our_name"], p["port_id"], p["ais_name"], p["mmsi"], p["call_sign"], p["ship_type"], p["length_m"],
            p["rule"], p["role"], p["status"] + (f" ({'; '.join(p['ambiguity'])})" if p["ambiguity"] else ""),
            "; ".join(p["support"]), ", ".join(f"{k} {v}d" for k, v in p["other_ports"].items()))) + " |")
    return "\n".join(lines) + "\n"


def rule_table(rep: dict) -> str:
    """Per-rule gains and ambiguity cost across the whole registry (counts only)."""
    cols = ["vessels_newly_matched", "clean", "ambiguous", "rival_pairs_on_existing_vessels",
            "existing_vessels_given_a_rival", "secondary_rival_pairs_on_new_vessels",
            "pairs_colliding_with_another_vessel", "ambiguity_cost_pairs", "ambiguity_cost_vessels"]
    lines = ["| Rule | " + " | ".join(cols) + " |", "| --- | " + " | ".join("---" for _ in cols) + " |"]
    for rid in RULE_ORDER:
        pr = rep["counts"]["per_rule"][rid]
        lines.append(f"| {rid} | " + " | ".join(str(pr[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--prior-join", type=Path, default=None, help="AISBULK-1 private join.json (optional)")
    parser.add_argument("--out", type=Path, required=True, help="private directory outside the repository")
    args = parser.parse_args(argv)
    if J._inside_repository(args.out):
        parser.error("--out must be outside the repository: the pair table holds MMSIs")
    before = _sha256(args.state)
    registry = [json.loads(s) for s in args.resolved.read_text().splitlines() if s.strip()]
    statics, presence, window = J.load_ais(args.state)
    rep = rematch(registry, statics, presence, _licence_index(args.prior_join))
    rep["ports"] = port_table(registry, rep, presence, statics)
    after = _sha256(args.state)
    proof = {"ais_state_sha256_before": before, "ais_state_sha256_after": after, "unchanged": before == after,
             "opened": "mode=ro", "presence_window": window}
    rep["counts"]["ais_state_read_only_proof"] = proof
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "pairs.json").write_text(json.dumps(rep, indent=1, default=str))
    (args.out / "pairs.md").write_text(private_table(rep))
    (args.out / "pr-table.md").write_text(pr_table(rep))
    (args.out / "rule-table.md").write_text(rule_table(rep))
    (args.out / "ports.json").write_text(json.dumps(rep["ports"], indent=1))
    head = list(rep["ports"][0])
    (args.out / "ports.md").write_text("| " + " | ".join(head) + " |\n| " + " | ".join("---" for _ in head) + " |\n"
                                       + "".join("| " + " | ".join(str(p[h]) for h in head) + " |\n"
                                                 for p in rep["ports"]))
    print(json.dumps(rep["counts"], indent=1, sort_keys=True))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
