"""Immutable limits and a durable, monotone, conservative coastal budget ledger."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
import uuid
from pathlib import Path

from .receipts import atomic_json, canonical_json, digest, file_sha256, monotonic, utc, managed_writes, managed_configuration
from .runner import boot_id


def _counter(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _seconds(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'non-negative'}")
    return value


@dataclass(frozen=True)
class Limits:
    wall_s: float
    reserve_s: float = 0
    bytes: int = 0
    requests: int = 0
    attempts_per_candidate: int = 1
    stagnation_s: float | None = None
    tokens: int | None = None

    def __post_init__(self):
        _seconds(self.wall_s, "wall_s", positive=True)
        _seconds(self.reserve_s, "reserve_s")
        if self.reserve_s >= self.wall_s:
            raise ValueError("reserve_s must be smaller than wall_s")
        for key in ("bytes", "requests", "attempts_per_candidate"):
            _counter(getattr(self, key), key)
        if not self.attempts_per_candidate:
            raise ValueError("attempts_per_candidate must be positive")
        if self.stagnation_s is not None:
            _seconds(self.stagnation_s, "stagnation_s", positive=True)
        if self.tokens is not None:
            _counter(self.tokens, "tokens")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None
    remaining: dict

    @property
    def status(self):
        return "ALLOW" if self.allowed else "STOP"


@dataclass(frozen=True)
class Budget:
    """One owned ledger; reservations are fsynced before callers perform work.

    Settled reservations conservatively charge their entire reserved cap.
    Imported usage is reported separately and cannot authorize a refund.
    Uncertain attempts retain their entire reservation in effective consumption.
    Limits and their digest are immutable across reopen and every transaction.
    """
    path: Path
    limits: Limits
    clock: object = None
    managed_output: dict | None = None

    @classmethod
    def create(cls, path, limits, *, clock=None, origin=None, managed_output=None):
        limits = limits if isinstance(limits, Limits) else Limits(**limits)
        managed_output = managed_output if managed_output is not None else managed_configuration()
        if managed_output is not None:
            managed_output = json.loads(canonical_json(managed_output))
        instance = cls(Path(path), limits, clock, managed_output)
        with instance._lock():
            if instance.path.exists():
                raise FileExistsError(f"budget ledger already exists: {path}")
            now = monotonic(clock)
            created = utc(clock)
            started = now
            if origin is not None:
                if not isinstance(origin,dict) or set(origin)!={"boot_id","utc","monotonic"}:
                    raise ValueError("explicit complete immutable budget origin required")
                from datetime import datetime
                current_utc=datetime.fromisoformat(str(created).replace("Z","+00:00")).timestamp()
                if isinstance(origin["utc"],str):
                    supplied=datetime.fromisoformat(origin["utc"].replace("Z","+00:00"))
                    if supplied.tzinfo is None or supplied.utcoffset() is None:raise ValueError("aware budget UTC origin required")
                    supplied_utc=supplied.timestamp()
                else:supplied_utc=origin["utc"]
                started=origin["monotonic"]
                if (origin["boot_id"]!=boot_id() or isinstance(started,bool) or not isinstance(started,(int,float))
                    or not math.isfinite(started) or started>now or started<0
                    or isinstance(supplied_utc,bool) or not isinstance(supplied_utc,(int,float))
                    or not math.isfinite(supplied_utc) or supplied_utc>current_utc
                    or abs((current_utc-supplied_utc)-(now-started))>2):
                    raise ValueError("budget origin future/boot/skew invalid")
                created=datetime.fromtimestamp(supplied_utc,__import__("datetime").timezone.utc).isoformat()
            state = {
                "schema": "coastal-budget-v1", "limits": asdict(limits),
                "limits_sha256": digest(asdict(limits)), "boot_id": boot_id(),
                "started_monotonic": started, "last_monotonic": now,
                "elapsed_s": max(0,now-started), "last_progress_elapsed_s": 0.0,
                "clock_uncertain": False, "created_utc": created,
                "reserved": {"bytes": 0, "requests": 0, "tokens": 0},
                "charged": {"bytes": 0, "requests": 0, "tokens": 0},
                "reservations": {}, "usage_sources": {}, "progress_sources": {}, "events": []}
            if managed_output is not None:
                state["managed_output"] = managed_output
            atomic_json(instance.path, state)
        return instance

    @classmethod
    def open(cls, path, *, clock=None, managed_output=None):
        state = json.loads(Path(path).read_text())
        managed_output = managed_output if managed_output is not None else managed_configuration()
        if managed_output is not None:
            managed_output = json.loads(canonical_json(managed_output))
        if state.get("managed_output") != managed_output:
            raise ValueError("budget managed output binding changed or missing")
        instance = cls(Path(path), Limits(**state["limits"]), clock, managed_output)
        with instance._lock():
            instance._read()
        return instance

    @contextmanager
    def _lock(self):
        with managed_writes(self.managed_output) as writer:
            if writer is not None:
                writer.relative_path(self.path)
            with open(str(self.path) + ".lock", "a+b") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                yield

    def _read(self):
        state = json.loads(self.path.read_text())
        if state.get("managed_output") != self.managed_output:
            raise ValueError("budget managed output binding changed or missing")
        expected = asdict(self.limits)
        if state.get("schema") != "coastal-budget-v1" or state.get("limits") != expected or state.get("limits_sha256") != digest(expected):
            raise ValueError("budget limits changed or ledger schema invalid")
        reservations = state.get("reservations")
        if not isinstance(reservations, dict):
            raise ValueError("budget reservations must be an object")
        sums_reserved = dict.fromkeys(("bytes", "requests", "tokens"), 0)
        sums_charged = dict.fromkeys(("bytes", "requests", "tokens"), 0)
        for reservation in reservations.values():
            if reservation.get("state") not in {"reserved", "settled", "uncertain"}:
                raise ValueError("invalid reservation state")
            for key in sums_reserved:
                sums_reserved[key] += _counter(reservation["reserved"][key], key)
                sums_charged[key] += _counter(reservation["charged"][key], key)
                if reservation["charged"][key] > reservation["reserved"][key]:
                    raise ValueError("charged amount exceeds its write-ahead reservation")
                if reservation["state"] == "settled" and reservation["charged"][key] != reservation["reserved"][key]:
                    raise ValueError("legacy settlement refunded capacity without an authenticated recorder")
        for aggregate in ("reserved", "charged"):
            for key in sums_reserved:
                _counter(state[aggregate][key], f"{aggregate}.{key}")
        if state.get("reserved") != sums_reserved or state.get("charged") != sums_charged:
            raise ValueError("budget aggregate counters do not match reservations")
        _seconds(state["elapsed_s"], "elapsed_s")
        _seconds(state["last_progress_elapsed_s"], "last_progress_elapsed_s")
        if state["last_progress_elapsed_s"] > state["elapsed_s"]:
            raise ValueError("budget progress time exceeds elapsed time")
        return state

    def _observe(self, state):
        now = monotonic(self.clock)
        if boot_id() != state["boot_id"] or now < state["last_monotonic"]:
            # A reboot or monotonic rollback cannot grant time back.
            state["clock_uncertain"] = True
        state["elapsed_s"] = max(state["elapsed_s"], now - state["started_monotonic"], 0)
        state["last_monotonic"] = max(state["last_monotonic"], now)

    def _effective(self, state):
        values = dict(state["charged"])
        for reservation in state["reservations"].values():
            if reservation["state"] != "settled":
                for key in values:
                    values[key] += reservation["reserved"][key] - reservation["charged"][key]
        return values

    def _decision(self, state):
        effective = self._effective(state)
        remaining = {
            "wall_s": max(0, self.limits.wall_s - self.limits.reserve_s - state["elapsed_s"]),
            "bytes": max(0, self.limits.bytes - effective["bytes"]),
            "requests": max(0, self.limits.requests - effective["requests"]),
            "tokens": None if self.limits.tokens is None else max(0, self.limits.tokens - effective["tokens"])}
        reason = None
        if state["clock_uncertain"]:
            reason = "clock_uncertain"
        elif state["elapsed_s"] >= self.limits.wall_s - self.limits.reserve_s:
            reason = "wall_budget_exhausted"
        elif self.limits.stagnation_s is not None and state["elapsed_s"] - state["last_progress_elapsed_s"] >= self.limits.stagnation_s:
            reason = "stagnation_budget_exhausted"
        elif any(r["state"] == "uncertain" or self._lost_execution_owner(r)
                 for r in state["reservations"].values()):
            reason = "failed_uncertain"
        elif self.limits.bytes and effective["bytes"] >= self.limits.bytes:
            reason = "byte_budget_exhausted"
        elif self.limits.requests and effective["requests"] >= self.limits.requests:
            reason = "request_budget_exhausted"
        elif self.limits.tokens and effective["tokens"] >= self.limits.tokens:
            reason = "token_budget_exhausted"
        return Decision(reason is None, reason, remaining)

    def _lost_execution_owner(self, entry):
        if entry["state"] != "reserved" or (entry.get("execution") or {}).get("state") != "launching":
            return False
        from .runner import process_identity
        owner = entry["execution"].get("dispatch_owner")
        if not isinstance(owner, dict) or owner.get("boot_id") != boot_id():
            return True
        current = process_identity(owner.get("pid"))
        return (current is None or current.get("host") != owner.get("host")
                or current.get("start_ticks") != owner.get("start_ticks")
                or current.get("state") in {"Z", "X"})

    def decide(self):
        with self._lock():
            state = self._read()
            self._observe(state)
            atomic_json(self.path, state)
            return self._decision(state)

    def reserve(self, reservation_id, *, bytes=0, requests=0, tokens=0, candidate=None):
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise ValueError("reservation_id is required")
        values = {key: _counter(value, key) for key, value in
                  (("bytes", bytes), ("requests", requests), ("tokens", tokens))}
        if candidate is not None and (not isinstance(candidate, str) or not candidate.strip()):
            raise ValueError("candidate must be a nonempty string")
        with self._lock():
            state = self._read()
            self._observe(state)
            if reservation_id in state["reservations"]:
                raise ValueError("reservation_id already used; no replay or refund")
            decision = self._decision(state)
            if not decision.allowed:
                raise ValueError(f"budget stopped: {decision.reason}")
            for key, value in values.items():
                cap = decision.remaining[key]
                if cap is not None and value > cap:
                    raise ValueError(f"budget {key} reservation exceeds remaining cap")
            if candidate is not None:
                attempts = sum(r.get("candidate") == candidate for r in state["reservations"].values())
                if attempts >= self.limits.attempts_per_candidate:
                    raise ValueError("candidate attempts cap exhausted")
            entry = {"state": "reserved", "candidate": candidate, "reserved": values,
                     "charged": dict.fromkeys(values, 0), "reserved_utc": utc(self.clock)}
            state["reservations"][reservation_id] = entry
            for key, value in values.items():
                state["reserved"][key] += value
            state["events"].append({"kind": "reserved", "id": reservation_id, "values": values})
            atomic_json(self.path, state)
            return dict(entry)

    def execute(self, reservation_id, argv, *, intent, completed_exit_codes=(0,), **kwargs):
        """Bind one prior reservation to an actual shared-runner execution.

        Callers cannot provide a completed receipt as execution proof. This method
        dispatches the target itself, captures the durable supervisor receipt and
        recomputes its output hashes. Explicit fixed stage exit codes can establish
        completed process accounting only; the coordinator must separately verify
        the actual stage result and mark uncertainty if it is absent or invalid.
        It never releases acquisition reservations:
        captured process output is not a measurement of network bytes or requests.
        """
        from .runner import process_identity, run_bounded
        if (not isinstance(completed_exit_codes, (list, tuple, set))
                or any(isinstance(code, bool) or not isinstance(code, int)
                       or code not in {0, 3, 4, 5, 6, 7} for code in completed_exit_codes)):
            raise ValueError("completed_exit_codes must use fixed coastal stage codes")
        completed_exit_codes = sorted({0, *completed_exit_codes})
        intent = Path(intent).absolute()
        with self._lock():
            state = self._read()
            self._observe(state)
            entry = state["reservations"].get(reservation_id)
            if entry is None or entry["state"] != "reserved" or entry.get("execution"):
                raise ValueError("execute requires a fresh unsettled reservation")
            decision = self._decision(state)
            if decision.reason in {"clock_uncertain", "wall_budget_exhausted",
                                   "stagnation_budget_exhausted", "failed_uncertain"}:
                raise ValueError(f"budget stopped: {decision.reason}")
            timeout = kwargs.pop("timeout_s", decision.remaining["wall_s"])
            _seconds(timeout, "timeout_s", positive=True)
            timeout = min(timeout, decision.remaining["wall_s"])
            if any(key in kwargs for key in ("byte_reservation", "clock", "execution_binding")):
                raise ValueError("execution reservation and clock are owned by Budget")
            configuration = kwargs.get("managed_output", self.managed_output)
            if self.managed_output is not None:
                if (not isinstance(configuration, dict)
                        or configuration.get("grant") != self.managed_output["grant"]
                        or configuration.get("grant_digest") != self.managed_output["grant_digest"]):
                    raise ValueError("runner managed grant differs from Budget")
                kwargs["managed_output"] = configuration
            elif configuration is not None:
                raise ValueError("cannot attach managed output to an unbound Budget")
            execution_binding = digest({"nonce": uuid.uuid4().hex,
                                        "ledger": str(self.path.absolute()),
                                        "reservation_id": reservation_id})
            launch_boot_id = boot_id()
            entry["execution"] = {"state": "launching", "intent_path": str(intent),
                                  "argv_sha256": digest(argv),
                                  "execution_binding": execution_binding,
                                  "launch_boot_id": launch_boot_id,
                                  "dispatch_owner": process_identity(os.getpid())}
            atomic_json(self.path, state)
        try:
            outcome = run_bounded(argv, intent=intent, timeout_s=timeout, clock=self.clock,
                                  byte_reservation=entry["reserved"]["bytes"],
                                  execution_binding=execution_binding, **kwargs)
            observed = json.loads(intent.read_text())
            execution = {"state": "completed", "intent_path": str(intent),
                         "intent_sha256": file_sha256(intent),
                         "argv_sha256": digest(argv), "status": outcome.status,
                         "execution_binding": execution_binding,
                         "launch_boot_id": launch_boot_id,
                         "runner_status": outcome.status,
                         "completed_exit_codes": completed_exit_codes,
                         "outputs": observed.get("outputs", [])}
            completed = (outcome.status == "ok" or (
                outcome.status == "failed_uncertain" and outcome.rc in completed_exit_codes
                and observed.get("state") == "finished"
                and observed.get("processes_stopped") is True
                and not observed.get("error")))
            if completed and outcome.status != "ok":
                execution["status"] = "completed_process"
            with self._lock():
                state = self._read()
                self._observe(state)
                entry = state["reservations"][reservation_id]
                entry["execution"] = execution
                if not completed:
                    self._hold(state, entry, reservation_id,
                               f"execution outcome {outcome.status} is uncertain")
                self._bound_execution(entry)
                atomic_json(self.path, state)
            return outcome
        except BaseException as exc:
            with self._lock():
                state = self._read()
                entry = state["reservations"][reservation_id]
                if entry["state"] == "reserved":
                    self._hold(state, entry, reservation_id,
                               f"execution verification {type(exc).__name__}: {exc}")
            raise

    def recover_uncertain(self, reservation_id, *, intent, receipt):
        """Settle only this bound stopped execution, without refund or clock reset.

        The same original proof is replayable after a consuming SQL transaction
        crashes. It never resolves another uncertain reservation or changes limits,
        attempt history, wall-clock high-water marks or stagnation timestamps.
        """
        from .runner import recover
        receipt = json.loads(Path(receipt).read_text()) if isinstance(receipt, (str, Path)) else receipt
        intent = Path(intent).absolute()
        with self._lock():
            state = self._read()
            self._observe(state)
            entry = state["reservations"].get(reservation_id)
            if entry is None or entry["state"] not in {"reserved", "uncertain", "settled"}:
                raise ValueError("recovery requires an owned unsettled execution reservation")
            execution = entry.get("execution") or {}
            if str(intent) != execution.get("intent_path"):
                raise ValueError("budget recovery intent does not match owned execution")
            binding = execution.get("execution_binding")
            if not isinstance(binding, str) or not execution.get("launch_boot_id"):
                raise ValueError("budget recovery lacks durable execution launch binding")
            observed = json.loads(intent.read_text())
            original = observed.get("recovery_checkpoint") if observed.get("state") == "recovered" else observed
            if not isinstance(original, dict):
                raise ValueError("budget recovery original checkpoint is uncertain")
            if (original.get("schema") != "coastal-run-intent-v1"
                    or original.get("execution_binding") != binding
                    or original.get("boot_id") != execution["launch_boot_id"]
                    or digest(original.get("argv")) != execution.get("argv_sha256")
                    or original.get("byte_reservation") != entry["reserved"]["bytes"]):
                raise ValueError("budget recovery execution identity or reservation mismatch")
            original_file_sha256 = hashlib.sha256(canonical_json(original) + b"\n").hexdigest()
            bound_original_sha256 = execution.get("recovery_source_intent_sha256")
            if execution.get("state") != "recovered":
                bound_original_sha256 = execution.get("intent_sha256")
            if bound_original_sha256 and original_file_sha256 != bound_original_sha256:
                raise ValueError("budget recovery bound intent bytes changed")
            if not bound_original_sha256:
                # After parent loss the pre-launch binding remains, but an
                # invented finished/failed-launch marker is not identity proof.
                if not original.get("supervisor") or not original.get("child"):
                    raise ValueError("budget recovery launch process identities are unknown")
            if entry["state"] == "settled" and entry.get("recovery") is not None:
                if entry.get("recovery") != receipt or file_sha256(intent) != execution.get("intent_sha256"):
                    raise ValueError("budget recovery replay differs from settled proof")
                recover(intent, receipt)  # recheck exact original proof and stopped groups
                atomic_json(self.path, state)  # persist elapsed high-water, no charge twice
                return dict(entry)
            recovered = recover(intent, receipt)
            # Receipt output integrity is forensic only; recovery never qualifies
            # those artifacts or grants measured-usage credit.
            for output in original.get("outputs", []):
                if (Path(output["path"]).stat().st_size != output["bytes"]
                        or file_sha256(output["path"], cap=output["bytes"]) != output["sha256"]):
                    raise ValueError("budget recovery captured output bytes changed")
            execution.update(state="recovered", status="failed_uncertain",
                             intent_sha256=file_sha256(intent),
                             recovery_checkpoint_sha256=digest(original),
                             recovery_source_intent_sha256=original_file_sha256)
            entry["recovery"] = receipt
            entry["recovery_status"] = "stopped_uncertain_execution_accounted"
            return self._settle_locked(
                state, entry, reservation_id,
                {"intent_path": str(intent), "recovery_receipt": receipt},
                reported_usage=None)

    def _hold(self, state, entry, reservation_id, reason, reported_usage=None):
        """Retain the entire reservation and stop on ambiguous accounting."""
        entry.update(state="uncertain", reason=reason)
        if reported_usage is not None:
            entry["reported_usage"] = reported_usage
        state["events"].append({"kind": "failed_uncertain", "id": reservation_id, "reason": reason})
        atomic_json(self.path, state)

    def _bound_execution(self, entry):
        execution = entry.get("execution") or {}
        if execution.get("state") != "completed" or execution.get("status") not in {"ok", "completed_process"}:
            raise ValueError("accounting requires a successful bound execution")
        intent = Path(execution["intent_path"])
        if file_sha256(intent) != execution.get("intent_sha256"):
            raise ValueError("bound execution receipt changed")
        observed = json.loads(intent.read_text())
        if (observed.get("schema") != "coastal-run-intent-v1"
                or observed.get("state") != "finished"
                or observed.get("status") != execution.get("runner_status", execution["status"])
                or observed.get("rc") not in execution.get("completed_exit_codes", [0])
                or observed.get("processes_stopped") is not True
                or observed.get("error")
                or digest(observed.get("argv")) != execution["argv_sha256"]
                or observed.get("byte_reservation") != entry["reserved"]["bytes"]
                or observed.get("execution_binding") != execution.get("execution_binding")
                or observed.get("boot_id") != execution.get("launch_boot_id")
                or observed.get("outputs") != execution["outputs"]):
            raise ValueError("bound execution identity or outcome mismatch")
        for output in execution["outputs"]:
            if (Path(output["path"]).stat().st_size != output["bytes"]
                    or file_sha256(output["path"], cap=output["bytes"]) != output["sha256"]):
                raise ValueError("bound execution output changed")
        return execution

    def charge(self, reservation_id, *, bytes=0, requests=0, tokens=0, evidence=None):
        """Conservatively settle a verified completed execution at its full cap.

        External counters/files are audit material, never authority to refund
        capacity. The runner cannot measure acquisition traffic, so any lower or
        otherwise ambiguous claim retains the reservation and adds an uncertain
        hold. Authenticated request accounting can be added by a future recorder.
        """
        values = {key: _counter(value, key) for key, value in
                  (("bytes", bytes), ("requests", requests), ("tokens", tokens))}
        if tokens:
            raise ValueError("token charge requires provider usage import")
        with self._lock():
            state = self._read()
            self._observe(state)
            entry = state["reservations"].get(reservation_id)
            if entry is None or entry["state"] != "reserved":
                raise ValueError("charge requires an unsettled reservation")
            try:
                self._bound_execution(entry)
                if entry["reserved"]["tokens"]:
                    raise ValueError("token reservations require provider usage import")
                if values != entry["reserved"]:
                    raise ValueError("unverified resource counters cannot refund or exceed a reservation")
                if evidence is not None:
                    if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
                            or file_sha256(evidence["path"]) != evidence["sha256"]):
                        raise ValueError("audit evidence hash mismatch")
            except (ValueError, OSError, KeyError) as exc:
                self._hold(state, entry, reservation_id, str(exc), values)
                raise ValueError(str(exc)) from None
            return self._settle_locked(state, entry, reservation_id, evidence,
                                       reported_usage=values)

    def _settle_locked(self, state, entry, reservation_id, evidence, *,
                       reported_usage=None, usage_source=None):
        if usage_source is not None and usage_source in state["usage_sources"]:
            raise ValueError("provider usage source was already charged")
        # Always retain full write-ahead capacity. Caller-authored or unauthenticated
        # files cannot establish an accounting refund, even when hash-bound.
        accounted = dict(entry["reserved"])
        previous_charge = dict(entry["charged"])
        entry.update(state="settled", charged=accounted, evidence=evidence,
                     accounting_basis="conservative_reservation",
                     reported_usage=reported_usage)
        for key, value in accounted.items():
            state["charged"][key] += value - previous_charge[key]
        if usage_source is not None:
            state["usage_sources"][usage_source] = reservation_id
        state["events"].append({"kind": "charged", "id": reservation_id,
                                "values": accounted, "evidence": evidence,
                                "accounting_basis": "conservative_reservation"})
        atomic_json(self.path, state)
        return dict(entry)

    def account_usage(self, reservation_id, *, path, sha256):
        """Record provider-shaped usage without granting unauthenticated refunds.

        These files are not authenticated by this module. Parsed usage is recorded
        separately; effective consumption always remains the full token cap.
        """
        if file_sha256(path) != sha256:
            raise ValueError("provider usage hash mismatch")
        total = 0
        request_ids = set()
        for line in Path(path).read_text().splitlines():
            record = json.loads(line)
            if record.get("schema") != "coastal-provider-usage-v1" or not record.get("request_id") or record.get("provider") not in {"openai", "anthropic"}:
                raise ValueError("provider usage record lacks route metadata")
            if record["request_id"] in request_ids:
                raise ValueError("duplicate provider request_id in usage source")
            request_ids.add(record["request_id"])
            usage = record.get("response", {}).get("usage", {})
            pair = ("input_tokens", "output_tokens")
            if record["provider"] == "openai" and "prompt_tokens" in usage:
                pair = ("prompt_tokens", "completion_tokens")
            if any(key not in usage for key in pair):
                raise ValueError("provider response has no measured token counters")
            subtotal = sum(_counter(usage[key], key) for key in pair)
            if record["provider"] == "anthropic":
                # Anthropic input_tokens excludes cache-read and cache-creation
                # inputs; the two top-level categories must be counted separately.
                for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
                    subtotal += _counter(usage.get(key, 0), key)
                if "cache_creation" in usage and "cache_creation_input_tokens" not in usage:
                    raise ValueError("Anthropic cache creation aggregate is missing")
            if "total_tokens" in usage and _counter(usage["total_tokens"], "total_tokens") != subtotal:
                raise ValueError("provider total_tokens disagrees with response counters")
            total += subtotal
        if not total:
            raise ValueError("provider usage source has no tokens")
        with self._lock():
            state = self._read()
            self._observe(state)
            entry = state["reservations"].get(reservation_id)
            if entry is None or entry["state"] != "reserved":
                raise ValueError("token import requires an unsettled reservation")
            if entry["reserved"]["bytes"] or entry["reserved"]["requests"]:
                self._hold(state, entry, reservation_id,
                           "provider usage import requires a dedicated token-only reservation")
                raise ValueError("provider usage import requires a dedicated token-only reservation")
            if total > entry["reserved"]["tokens"]:
                self._hold(state, entry, reservation_id, "provider tokens exceed write-ahead reservation",
                           {"tokens": total})
                raise ValueError("provider tokens exceed write-ahead reservation")
            return self._settle_locked(
                state, entry, reservation_id, {"path": str(path), "sha256": sha256},
                reported_usage={"bytes": 0, "requests": 0, "tokens": total},
                usage_source=sha256)

    def fail_uncertain(self, reservation_id, *, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("uncertain failure requires an explicit reason")
        with self._lock():
            state = self._read()
            self._observe(state)
            entry = state["reservations"].get(reservation_id)
            if entry is None or entry["state"] != "reserved":
                raise ValueError("uncertain failure requires an unsettled reservation")
            entry.update(state="uncertain", reason=reason)
            state["events"].append({"kind": "failed_uncertain", "id": reservation_id, "reason": reason})
            atomic_json(self.path, state)
            return dict(entry)

    def progress(self, *, evidence):
        """Refuse generic progress claims; runtime output is not scientific progress.

        A hash proves content identity, not a new accepted scientific transition.
        Until a coordinator-owned transition authority is explicitly integrated,
        neither external files nor fresh stdout/nonces can reset stagnation.
        """
        if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
                or file_sha256(evidence["path"]) != evidence["sha256"]):
            raise ValueError("progress requires hash-bound audit evidence")
        with self._lock():
            state = self._read()
            self._observe(state)
            state["events"].append({"kind": "progress_refused", "evidence": evidence,
                                    "reason": "semantic_transition_authority_required"})
            atomic_json(self.path, state)
        raise ValueError("semantic progress requires a committed coordinator transition; runtime cannot infer it")
