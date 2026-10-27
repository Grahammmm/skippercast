"""Reopen hash-pinned evidence; exit 3 with a corrective report on bad inputs."""
import json
from review_common import (GraphValidator, IDENTITY, PINS, SHA, absolute, attempt_path,
                           document, finish, finding, location, observed_read, output,
                           parser, pin, problem, resolver_for, review_base, reviewer,
                           sha256, trusted_context, validate)
from coast_sample import sample
from coast_refs import loads

REQUIRED = ('valid_fraction', 'depth_median_m', 'depth_p99_m', 'nodata_fraction',
            'edge_valid_fraction', 'slope_p99_deg')


def population(resolver, context, packet):
    """Re-derive eligibility, not merely trust a packet's chosen population."""
    for key in PINS[:2]:
        if packet[key] != context[key]:
            raise ValueError('packet/context pin mismatch: ' + key)
    if packet['routing'] != context['routing'] or packet['run_author_model'] != context['run_author_model'] or packet['run_author_provenance'] != context['run_author_provenance']:
        raise ValueError('packet author/routing provenance differs from trusted context')
    run = document(resolver, context['run'])
    admission = document(resolver, context['admission'])
    if any(run[k] != context[k] or admission[k] != context[k] for k in IDENTITY):
        raise ValueError('producer/context identity mismatch')
    if run['author_model'] != context['run_author_model'] or run['card_id'] != context['run_card_id']:
        raise ValueError('run actual author/card mismatch')
    t1 = document(resolver, packet['tier1'])
    if t1['context'] != packet['context'] or t1['run'] != context['run']:
        raise ValueError('tier1/context/run pin mismatch')
    inventory = {w['window_key'] for w in admission['windows']}
    states = {w['window_key']: w['state'] for w in run['windows']}
    windows = {w['window_key']: w for w in t1['windows']}
    if set(states) != inventory or set(windows) != inventory or len(windows) != len(t1['windows']):
        raise ValueError('run/tier1 must cover complete distinct admission inventory')
    flags = []
    for w in windows.values():
        flags.extend(w['flags'])
        if w['stage_state'] != states[w['window_key']]:
            raise ValueError('tier1 state differs from verified run')
    for mode, ref in packet['checks'].items():
        check = document(resolver, ref)
        if check['mode'] != mode or check['context'] != packet['context'] or not check['integrity_ok']:
            raise ValueError('tier2 mode/context/integrity mismatch')
        flags.extend(check['findings'])
    # Packet must retain every actual T1/T2 finding. Extra bounded findings are
    # allowed, but may only reduce eligibility, never remove required flags.
    if any(f not in packet['flags'] for f in flags):
        raise ValueError('packet omitted a tier finding')
    flagged = {f['window_key'] for f in packet['flags'] if f['severity'] in ('must', 'should') and f['window_key'] is not None}
    if not flagged <= inventory:
        raise ValueError('finding names an unadmitted window')
    held, unfinished, unavailable, done, eligible = [], [], [], [], []
    for key, w in windows.items():
        state = states[key]
        if state == 'map_done':
            done.append(key)
        elif state == 'held':
            held.append(key)
        else:
            unfinished.append(key)
        missing = (w['status'] == 'unavailable' or
                   (state == 'map_done' and (any(w['measurements'][n]['status'] != 'measured' for n in REQUIRED) or
                    any(m['status'] == 'unavailable' for m in w['measurements'].values()))))
        if missing:
            unavailable.append(key)
        if state != 'map_done' or w['status'] != 'pass' or missing:
            flagged.add(key)
        if state == 'map_done' and w['status'] == 'pass' and not missing and key not in flagged:
            eligible.append(key)
    return dict(map_done=sorted(done), eligible=sorted(eligible), flagged=sorted(flagged),
                held=sorted(held), unfinished=sorted(unfinished), unavailable=sorted(unavailable))


def check_packet(resolver, context_ref, packet_ref):
    context = trusted_context(resolver, context_ref)
    graph = GraphValidator(resolver)
    graph.reference(context_ref, contract='coast-review-context-v1')
    packet = graph.reference(packet_ref, contract='coast-review-packet-v1')
    if packet['context'] != context_ref or not packet['integrity_ok']:
        raise ValueError('packet is diagnostic or has different trusted context')
    expected = population(resolver, context, packet)
    if packet['population'] != expected:
        raise ValueError('packet population differs from verified run/tier evidence')
    selected = sample(expected['map_done'], expected['eligible'], plan_sha256=context['plan_sha256'],
                      bridge_sha256=context['bridge']['sha256'])
    if packet['sample'] != selected:
        raise ValueError('sample re-derivation mismatch')
    return packet, graph


def open_packet(resolver, context_ref, packet_path, expected_hash, reviewer_model, reviewer_ref, out,
                expected_bytes=None):
    context = trusted_context(resolver, context_ref)
    runtime = reviewer(resolver, context, reviewer_model, reviewer_ref)
    attempt_path(context, out, 'tier3/open-report.json')
    key, path = location(resolver, packet_path)
    if expected_hash is not None and not SHA.fullmatch(expected_hash):
        raise ValueError('expected packet SHA256 must be lowercase 64 hex')
    expected = dict(root_id=key, path=path, expected_sha256=expected_hash, expected_bytes=expected_bytes)
    observed = dict(status='missing', observed_sha256=None, observed_bytes=None)
    problems, verified = [], []
    # Check expectations separately so direct context failures have exact paths,
    # and retain successfully verified edges even when another edge is broken.
    graph = GraphValidator(resolver)
    for name in PINS:
        ref = context[name]
        if ref is None:
            problems.append(problem('POSTED_SHA_ABSENT', name, 'posted input Ref', None))
            continue
        try:
            graph.reference(ref)
        except (ValueError, OSError, KeyError, TypeError) as error:
            code = 'HASH_MISMATCH' if 'mismatch' in str(error) else 'REF_MISSING' if isinstance(error, FileNotFoundError) else 'INPUT_INVALID'
            problems.append(problem(code, ref['path'], ref['sha256'], str(error)))
    verified.extend(loads(k[0]) for k in graph.verified)
    raw = None
    try:
        raw = observed_read(resolver, packet_path)
        observed.update(status='present', observed_sha256=sha256(raw), observed_bytes=len(raw))
        if expected_bytes is None:
            # Byte length was not posted: report it as unknown expectation. A
            # normal packet Ref still pins the independently authenticated bytes.
            pass
        if expected_hash is None:
            problems.append(problem('POSTED_SHA_ABSENT', path, 'posted packet SHA256', None))
        elif sha256(raw) != expected_hash or (expected_bytes is not None and len(raw) != expected_bytes):
            problems.append(problem('HASH_MISMATCH', path, expected_hash, sha256(raw)))
        else:
            packet_ref = dict(root_id=key, path=path, sha256=expected_hash, bytes=len(raw))
            try:
                _, graph = check_packet(resolver, context_ref, packet_ref)
                verified.extend(loads(k[0]) for k in graph.verified)
            except (ValueError, OSError, KeyError, TypeError) as error:
                problems.append(problem('INPUT_INVALID', path, 'verified full input graph and sample', str(error)))
    except FileNotFoundError:
        problems.append(problem('REF_MISSING', path, expected_hash, None))
    except (ValueError, OSError) as error:
        observed['status'] = 'unreadable'
        problems.append(problem('REF_UNREADABLE', path, expected_hash, str(error)))
    if context['mode'] == 'diagnostic':
        problems.extend(context['observations'])
    snapshots = []
    if problems and raw is not None:
        # Preserve exact untrusted bytes as opaque evidence; never parse them for
        # identity. .bin is intentional: graph validation must not parse bad JSON.
        snapshot = out.with_name('observed-packet.bin')
        from coast_refs import directory_fd
        import os
        with directory_fd(snapshot.parent):
            fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        snapshots.append(pin(resolver, snapshot))
    # Deduplicate refs without treating diagnostic expected hashes as edges.
    verified = sorted({json.dumps(r, sort_keys=True): r for r in verified}.values(), key=lambda r: (r['root_id'], r['path']))
    report = dict(review_base('open-report', context, context_ref, runtime), expected_packet=expected,
                  observed_packet=observed, integrity_ok=not problems, problems=problems,
                  verified_refs=verified, measurements_trusted=not problems,
                  reviewer_model=reviewer_model, reviewer_provenance=reviewer_ref, evidence_snapshots=snapshots)
    validate(report, resolver, root_id=context_ref['root_id'])
    return output(resolver, out, report), 3 if problems else 0


def main():
    cli = parser(__doc__)
    cli.add_argument('--context', required=True, type=absolute)
    cli.add_argument('--expected-context-sha256', required=True)
    cli.add_argument('--packet', required=True, type=absolute)
    cli.add_argument('--expected-packet-sha256')
    cli.add_argument('--expected-packet-bytes', type=int)
    cli.add_argument('--reviewer-model', required=True)
    cli.add_argument('--reviewer-provenance', required=True, type=absolute)
    cli.add_argument('--out', required=True, type=absolute)
    args = cli.parse_args()
    resolver = resolver_for(args)
    ref, code = open_packet(resolver, pin(resolver, args.context, args.expected_context_sha256), args.packet,
                            args.expected_packet_sha256, args.reviewer_model,
                            pin(resolver, args.reviewer_provenance), args.out, args.expected_packet_bytes)
    print(json.dumps(dict(open_report=ref, integrity_ok=code == 0), sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(finish(main))
