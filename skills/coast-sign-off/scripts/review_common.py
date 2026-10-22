"""Bounded offline review IO and independently supplied identity contracts.

Provenance and posted handoffs use canonical JSON in .txt evidence envelopes;
these are opaque leaves to the shared graph validator, checked here by role.
No profile or requested alias is accepted as proof of an actual runtime model.
"""
import argparse
import os
from pathlib import Path
import stat
import sys

SHARED = Path(__file__).resolve().parents[2] / 'coast-campaign-shared/scripts'
sys.path.insert(0, str(SHARED))
from coast_refs import (Resolver, canonical, directory_fd, loads, relative_parts,
                        sha256, SHA, write_once)
from validate_coast_receipt import GraphValidator, validate, validate_schema

IDENTITY = ('campaign_segment_id', 'coordinator_segment_id', 'plan_id', 'plan_sha256')
HEADER = ('created_utc', 'author_profile', 'author_model', 'card_id', 'code_commit', 'skill_commit')
PINS = ('admission', 'run', 'bridge', 'enqueue')
LIMIT = 32 * 1024 * 1024


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or any(p in ('.', '..') for p in value.split('/')):
        raise argparse.ArgumentTypeError('file arguments must be absolute and normalized')
    return path


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument('--roots', required=True, type=absolute)
    result.add_argument('--allowed-root-id', action='append', required=True,
                        help='Card-admitted namespace; repeat independently of roots JSON')
    return result


def resolver_for(args):
    return Resolver(loads(args.roots.read_bytes()), allowed_root_ids=args.allowed_root_id)


def location(resolver, path):
    path = Path(path)
    matches = [(key, root) for key, root in resolver.bindings.items() if path.is_relative_to(root)]
    if len(matches) != 1:
        raise ValueError('file must belong to exactly one admitted root')
    key, root = matches[0]
    relative = path.relative_to(root).as_posix()
    relative_parts(relative)
    return key, relative


def observed_read(resolver, path):
    """Confined no-follow bounded read for observations, never a claimed valid Ref."""
    key, relative = location(resolver, path)
    parts = relative_parts(relative)
    with directory_fd(resolver.bindings[key]) as root:
        fd = os.dup(root)
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                before = os.fstat(leaf)
                if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
                    raise ValueError('input must be a regular file within 32 MiB')
                with os.fdopen(leaf, 'rb', closefd=False) as stream:
                    raw = stream.read(LIMIT + 1)
                after = os.fstat(leaf)
                identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                if identity(before) != identity(after) or len(raw) != before.st_size:
                    raise ValueError('input changed during observation')
            finally:
                os.close(leaf)
        finally:
            os.close(fd)
    return raw


def pin(resolver, path, expected_sha256=None):
    raw = observed_read(resolver, path)
    if expected_sha256 is not None and (not SHA.fullmatch(expected_sha256) or sha256(raw) != expected_sha256):
        raise ValueError('independently posted input hash mismatch')
    key, relative = location(resolver, path)
    return dict(root_id=key, path=relative, sha256=sha256(raw), bytes=len(raw))


def document(resolver, ref):
    if ref['bytes'] > LIMIT:
        raise ValueError('structured input exceeds 32 MiB')
    return loads(resolver.read(ref))


def output(resolver, path, value):
    location(resolver, path)
    # Check every parent before write_once; card execution requires exclusive
    # ownership, as for the shared ledger. No permission or route changes.
    with directory_fd(path.parent):
        pass
    write_once(path, value)
    return pin(resolver, path)


def provenance(resolver, ref, model):
    value = document(resolver, ref)
    required = {'actual_model', 'family', 'profile', 'card_id', 'code_commit',
                'skill_commit', 'created_utc', 'session_id', 'provider'}
    if not isinstance(value, dict) or set(value) != required or any(not isinstance(v, str) or not v for v in value.values()):
        raise ValueError('actual runtime provenance is missing or malformed')
    if value['actual_model'] != model:
        raise ValueError('runtime provenance actual model mismatch')
    return value


def header(context, runtime=None):
    if runtime is None:
        return {key: context[key] for key in HEADER}
    return dict(created_utc=runtime['created_utc'], author_profile=runtime['profile'],
                author_model=runtime['actual_model'], card_id=runtime['card_id'],
                code_commit=runtime['code_commit'], skill_commit=runtime['skill_commit'])


def review_base(name, context, context_ref, runtime):
    return dict(schema='coast-' + name + '-v1', **header(context, runtime),
                **{key: context[key] for key in IDENTITY},
                review_round=context['review_round'], attempt=context['attempt'], context=context_ref)


def trusted_context(resolver, ref):
    graph = GraphValidator(resolver)
    context = graph.reference(ref, scope='identity_snapshot', contract='coast-review-context-v1')
    if set(context['root_ids']) != set(resolver.bindings):
        raise ValueError('context root inventory differs from admitted bindings')
    identity = document(resolver, context['identity_provenance'])
    for key in (*IDENTITY, 'run_author_model', 'run_card_id'):
        if identity.get(key) != context[key]:
            raise ValueError('independently authenticated identity mismatch: ' + key)
    provenance(resolver, context['run_author_provenance'], context['run_author_model'])
    posted = document(resolver, context['posted_hashes'])
    if not isinstance(posted, dict):
        raise ValueError('posted hashes envelope must be an object')
    for key in PINS:
        if context[key] is not None and posted.get(key) != context[key]:
            raise ValueError('posted handoff missing or differs: ' + key)
    return context


def reviewer(resolver, context, model, provenance_ref):
    author = provenance(resolver, context['run_author_provenance'], context['run_author_model'])
    actual = provenance(resolver, provenance_ref, model)
    policy = document(resolver, context['routing'])
    validate_schema(policy)
    if model == author['actual_model'] or actual['family'] == author['family']:
        raise ValueError('same actual author/reviewer model family')
    if [author['family'], actual['family']] in policy['disallowed_family_pairs']:
        raise ValueError('forbidden author/reviewer family pair')
    if dict(author_model=author['actual_model'], reviewer_model=model) not in policy['allowed_pairs']:
        raise ValueError('actual author/reviewer pair is not admitted')
    qualified = [q for q in policy['qualified_reviewers'] if q['actual_model'] == model and q['family'] == actual['family']]
    if len(qualified) != 1:
        raise ValueError('reviewer lacks unique admitted qualification')
    resolver.read(qualified[0]['provenance'])
    return actual


def attempt_path(context, path, leaf):
    suffix = Path('plans') / context['plan_id'] / 'review' / f"r{context['review_round']:02d}" / f"a{context['attempt']:02d}"
    expected = suffix / leaf
    if tuple(path.parts[-len(expected.parts):]) != expected.parts:
        raise ValueError('output must use its immutable plan/round/attempt address')


def problem(code, path, expected=None, observed=None):
    return dict(code=code, path=str(path), expected=expected, observed=observed)


def finding(code, detail, key=None):
    return dict(window_key=key, severity='must', code=code, detail=detail, evidence=[])


def finish(main):
    try:
        return main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 3
