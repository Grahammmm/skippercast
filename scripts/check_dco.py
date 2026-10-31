"""Developer Certificate of Origin check for pull-request commits.

Reads the JSON list returned by the GitHub API for a pull request's commits
(``GET /repos/{owner}/{repo}/pulls/{number}/commits``) and fails when a commit
by a non-exempt author has no ``Signed-off-by:`` trailer matching the commit
author's email.

Exempt authors are the repository owner and the project's own agents, whose
work the owner already controls (see CONTRIBUTING.md and
docs/engineering/adr/0004-licensing.md):

* GitHub login ``Grahammmm`` (the owner; Codex commits are authored as the owner);
* ``Claude <noreply@anthropic.com>`` (Claude Code commits);
* GitHub login ``dependabot[bot]`` (dependency updates this repository configures in
  ``.github/dependabot.yml``; they contain no authored work to certify).

Commit authorship is only an email address, which anyone can set. The
exemptions therefore apply only to pull requests from branches of this
repository (pushing one needs write access). Pass ``--fork`` for a pull request
from a fork: then every commit must be signed off.

Usage: python scripts/check_dco.py [--fork] commits.json
"""
import json
import os
import re
import sys

OWNER_LOGINS = frozenset({'grahammmm'})
AGENT_EMAILS = frozenset({'noreply@anthropic.com'})
BOT_LOGINS = frozenset({'dependabot[bot]'})
SIGN_OFF = re.compile(r'^Signed-off-by:\s*(?P<name>.+?)\s*<(?P<email>[^<>\s]+@[^<>\s]+)>\s*$', re.MULTILINE)


def exempt(commit, fork=False):
    if fork:
        return False
    login = ((commit.get('author') or {}).get('login') or '').lower()
    email = (commit['commit']['author'].get('email') or '').lower()
    return login in OWNER_LOGINS or login in BOT_LOGINS or email in AGENT_EMAILS


def signed_off(commit):
    email = (commit['commit']['author'].get('email') or '').lower()
    return any(m.group('email').lower() == email for m in SIGN_OFF.finditer(commit['commit']['message']))


def offenders(commits, fork=False):
    """[(short sha, author) ...] for commits that need but lack a sign-off."""
    result = []
    for commit in commits:
        if exempt(commit, fork) or signed_off(commit):
            continue
        author = commit['commit']['author']
        result.append((commit['sha'][:12], f"{author.get('name')} <{author.get('email')}>"))
    return result


class InputError(ValueError):
    """The commits file is unreadable, empty or not a list of commit objects."""


def load_commits(path):
    """The flattened commit list in ``path``; raises InputError naming what is wrong."""
    name = os.path.basename(path)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f'cannot read {name} ({type(exc).__name__})') from None
    except ValueError:
        raise InputError(f'{name} is not JSON') from None
    if not isinstance(data, list) or not all(isinstance(page, (list, dict)) for page in data):
        raise InputError(f'{name} is not a list of commits')
    # `gh api --paginate --slurp` wraps each page in an outer list; accept either shape.
    commits = [c for page in data for c in (page if isinstance(page, list) else [page])]
    if not commits:
        raise InputError(f'{name} holds no commits; refusing to pass an empty pull request')
    for number, entry in enumerate(commits, 1):
        inner = entry.get('commit') if isinstance(entry, dict) else None
        if not (isinstance(inner, dict) and isinstance(entry.get('sha'), str)
                and isinstance(inner.get('author'), dict) and isinstance(inner.get('message'), str)):
            raise InputError(f'entry {number} is not a commit object')
    return commits


def main(argv):
    args = argv[1:]
    fork = '--fork' in args
    args = [a for a in args if a != '--fork']
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    try:
        commits = load_commits(args[0])
    except InputError as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 2
    missing = offenders(commits, fork)
    if missing:
        for sha, author in missing:
            print(f'::error::Commit {sha} by {author} has no matching "Signed-off-by:" line. '
                  'Add one with `git commit -s` (see CONTRIBUTING.md, "Developer Certificate of Origin").')
        return 1
    print(f'DCO check passed for {len(commits)} commit(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
