def supersedes(n):
    return dict(path=str(PRIOR / 'metadata' / (n + '.json')), sha256=sha(PRIOR / 'metadata' / (n + '.json')), reviewer_id=expired[n].get('reviewer_id'), valid_until=expired[n]['valid_until'])
