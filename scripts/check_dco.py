"""Developer Certificate of Origin check for pull-request commits.

Reads the JSON list returned by the GitHub API for a pull request's commits
(``GET /repos/{owner}/{repo}/pulls/{number}/commits``) and fails when a commit
by a non-exempt author has no ``Signed-off-by:`` trailer matching the commit
author's email.

Exempt authors are the repository owner and the project's own agents, whose
work the owner already controls (see CONTRIBUTING.md and
docs/engineering/adr/0004-licensing.md):

* GitHub login ``Grahammmm`` (the owner; Codex commits are authored as the owner);
* ``Claude <noreply@anthropic.com>`` (Claude Code commits).

Commit authorship is only an email address, which anyone can set. The
exemptions therefore apply only to pull requests from branches of this
repository (pushing one needs write access). Pass ``--fork`` for a pull request
from a fork: then every commit must be signed off.

Usage: python scripts/check_dco.py [--fork] commits.json
"""
import json
import re
import sys

OWNER_LOGINS = frozenset({'grahammmm'})
AGENT_EMAILS = frozenset({'noreply@anthropic.com'})
SIGN_OFF = re.compile(r'^Signed-off-by:\s*(?P<name>.+?)\s*<(?P<email>[^<>\s]+@[^<>\s]+)>\s*$', re.MULTILINE)


def exempt(commit, fork=False):
    if fork:
        return False
    login = ((commit.get('author') or {}).get('login') or '').lower()
    email = (commit['commit']['author'].get('email') or '').lower()
    return login in OWNER_LOGINS or email in AGENT_EMAILS


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


def main(argv):
    args = argv[1:]
    fork = '--fork' in args
    args = [a for a in args if a != '--fork']
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    with open(args[0], encoding='utf-8') as handle:
        data = json.load(handle)
    # `gh api --paginate --slurp` wraps each page in an outer list; accept either shape.
    commits = [c for page in data for c in (page if isinstance(page, list) else [page])]
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
