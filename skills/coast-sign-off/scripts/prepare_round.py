"""Prepare a write-once review context from independently posted handoff Refs."""
import errno
import os
from pathlib import Path
import stat
from review_common import (PINS, IDENTITY, LIMIT, GraphValidator, absolute, attempt_path,
                           document, finish, header, output, parser, pin, problem,
                           resolver_for, trusted_context, validate_schema, loads)


def prepare(resolver, inputs, review_round, attempt, out):
    context = dict(inputs, schema='coast-review-context-v1', review_round=review_round, attempt=attempt)
    validate_schema(context)
    attempt_path(context, out, 'context.json')
    # Validate identity independently before using any run/packet-derived identity.
    identity = document(resolver, context['identity_provenance'])
    for key in (*IDENTITY, 'run_author_model', 'run_card_id'):
        if identity.get(key) != context[key]:
            raise ValueError('independent identity differs: ' + key)
    posted = document(resolver, context['posted_hashes'])
    if any(context[k] is not None and posted.get(k) != context[k] for k in PINS):
        raise ValueError('posted handoff pins absent or different; corrective handoff required')
    if review_round == 1 and attempt == 1:
        if context['supersedes'] is not None or context['correction_verdict'] is not None:
            raise ValueError('initial round cannot supersede a review')
    else:
        if context['supersedes'] is None:
            raise ValueError('new round/attempt must explicitly supersede its context')
        previous = trusted_context(resolver, context['supersedes'])
        if any(previous[k] != context[k] for k in IDENTITY):
            raise ValueError('changed plan needs new admission, not review correction')
        if attempt > 1:
            if previous['review_round'] != review_round or previous['attempt'] + 1 != attempt:
                raise ValueError('attempt must increment within the same round')
        else:
            correction = context['correction_verdict']
            if correction is None:
                raise ValueError('new round requires previous must_fix verdict')
            verdict = GraphValidator(resolver).reference(correction, contract='coast-review-verdict-v1')
            if (verdict['verdict'] != 'must_fix' or verdict['context'] != context['supersedes'] or
                    previous['review_round'] + 1 != review_round):
                raise ValueError('correction does not bind immediately previous must_fix round')
    problems = list(context['observations'])
    graph = GraphValidator(resolver)
    for key in PINS:
        if context[key] is None:
            problems.append(problem('POSTED_SHA_ABSENT', key, 'independent posted Ref', None))
            continue
        try:
            # Shared tooling consumes the hash-bound v2 adapter records; PC9's
            # native v1 receipts are reached only through legacy_enqueue/legacy_run.
            value = graph.reference(context[key], contract={'admission': 'coast-admission-v1',
                'run': 'coast-run-summary-v2', 'enqueue': 'coast-enqueue-receipt-v2'}.get(key))
            if key in ('admission', 'run', 'enqueue'):
                if any(value[k] != context[k] for k in IDENTITY):
                    raise ValueError('producer identity mismatch')
            if key == 'run' and (value['author_model'] != context['run_author_model'] or value['card_id'] != context['run_card_id']):
                raise ValueError('run author/card provenance mismatch')
        except (ValueError, OSError, KeyError, TypeError) as error:
            problems.append(problem('INPUT_INVALID', key, context[key]['sha256'], str(error)))
    context.update(mode='diagnostic' if problems else 'normal', observations=problems)
    validate_schema(context)
    # Stage context once, then use its independent identity-only role to check
    # provenance/roots. The normal graph is checked before declaring ready.
    from review_common import provenance
    provenance(resolver, context['run_author_provenance'], context['run_author_model'])
    for key in ('routing', 'thresholds', 'prompts', 'identity_provenance', 'posted_hashes'):
        graph.walk(context[key], root_id='queue:' + context['campaign_segment_id'])
    if set(context['root_ids']) != set(resolver.bindings):
        raise ValueError('unexpected context root IDs')
    ref = output(resolver, out, context)
    trusted_context(resolver, ref)
    if not problems:
        GraphValidator(resolver).reference(ref, contract='coast-review-context-v1')
    return ref, bool(problems)


_CHUNK = 1024 * 1024


def _snapshot(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stable(before, after, named):
    """The descriptor is unchanged by the read and its name still binds that same file."""
    return _snapshot(before) == _snapshot(after) == _snapshot(named)


def _open_component(name, flags, parent):
    try:
        return os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            try:
                link = stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode)
            except OSError:
                link = False
            if link:
                raise ValueError('--inputs path must not contain a symlink: ' + name) from error
        raise


def _read_inputs(path):
    """Descriptor-bound --inputs read: no symlink at any component, a regular file within
    LIMIT, at most LIMIT + 1 bytes requested, and stable identity through completion."""
    path = Path(path)
    if not path.is_absolute() or path.name in ('', '.', '..') or any(p in ('.', '..') for p in path.parts):
        raise ValueError('--inputs must be absolute and normalized')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = _open_component(part, os.O_RDONLY | os.O_DIRECTORY, parent)
            os.close(parent)
            parent = child
        leaf = _open_component(path.name, os.O_RDONLY | os.O_NONBLOCK, parent)
        try:
            before = os.fstat(leaf)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('--inputs must be a regular file')
            if before.st_size > LIMIT:
                raise ValueError('--inputs exceeds 32 MiB')
            # Total requested bytes never exceed st_size + 1 <= LIMIT + 1, even on short reads.
            chunks, remaining = [], before.st_size + 1
            while remaining > 0:
                request = min(remaining, _CHUNK)
                remaining -= request
                chunk = os.read(leaf, request)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b''.join(chunks)
            after = os.fstat(leaf)
            try:
                named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError as error:
                raise ValueError('--inputs changed while it was read') from error
            if len(raw) != before.st_size or not _stable(before, after, named):
                raise ValueError('--inputs changed while it was read')
        finally:
            os.close(leaf)
    finally:
        os.close(parent)
    return raw


def main():
    cli = parser(__doc__)
    cli.add_argument('--inputs', required=True, type=absolute)
    cli.add_argument('--round', required=True, type=int)
    cli.add_argument('--attempt', required=True, type=int)
    cli.add_argument('--out', required=True, type=absolute)
    args = cli.parse_args()
    resolver = resolver_for(args)
    ref, diagnostic = prepare(resolver, loads(_read_inputs(args.inputs)), args.round, args.attempt, args.out)
    import json
    print(json.dumps(dict(context=ref, diagnostic=diagnostic), sort_keys=True))
    return 3 if diagnostic else 0


if __name__ == '__main__':
    raise SystemExit(finish(main))
