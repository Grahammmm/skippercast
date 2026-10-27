"""Bounded row-major adjacency; callers must match source SHA AND grid SHA."""


def neighbours(idx, cols, rows, total):
    if any(type(v) is not int for v in (idx, cols, rows, total)):
        raise ValueError("integer grid coordinates required")
    if cols <= 0 or rows <= 0 or total <= 0 or total > cols * rows or total <= (rows - 1) * cols:
        raise ValueError("invalid or nonminimal ragged grid")
    if not 0 <= idx < total:
        raise ValueError("index outside grid")
    r, c = divmod(idx, cols)
    result = []
    for rr, cc in ((r, c - 1), (r, c + 1), (r - 1, c), (r + 1, c)):
        k = rr * cols + cc
        if 0 <= rr < rows and 0 <= cc < cols and k < total:
            result.append(k)
    return sorted(result)
