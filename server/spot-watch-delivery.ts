type Attempt = 1 | 2 | 3;
type Retryable = (status: string, httpStatus: number | null, attempt: number) => boolean;
type Outcome = {status: string; httpStatus: number | null; attempt: number};
type Decision = {kind: 'delivered'} | {kind: 'send'; attempt: Attempt} | {kind: 'skip'};

function readReceipt(row: unknown): (Outcome & {attempt: Attempt}) | undefined {
  if (row === null || typeof row !== 'object') return;
  try {
    const {attempt, status, http_status} = row as Record<string, unknown>;
    if (attempt !== 1 && attempt !== 2 && attempt !== 3) return;
    if (typeof status !== 'string' || status.length === 0) return;
    const httpStatus = typeof http_status === 'number' && Number.isInteger(http_status) ? http_status : null;
    return {attempt, status, httpStatus};
  } catch {
    // An unreadable receipt is not usable evidence of a send.
    return;
  }
}

export function nextAttempt(prior: readonly unknown[], retryable: Retryable): Decision {
  let latest: ReturnType<typeof readReceipt>;
  for (const row of prior) {
    const receipt = readReceipt(row);
    if (!receipt) continue;
    if (receipt.status === 'accepted') return {kind: 'delivered'};
    if (!latest || receipt.attempt > latest.attempt) latest = receipt;
  }
  if (!latest) return {kind: 'send', attempt: 1};
  const {status, httpStatus, attempt} = latest;
  if (!retryable(status, httpStatus, attempt) || attempt === 3) return {kind: 'skip'};
  return {kind: 'send', attempt: attempt === 1 ? 2 : 3};
}

export function eventStatus(
  outcomes: readonly Outcome[],
  subscriptionCount: number,
  retryable: Retryable,
): 'delivered' | 'pending' | 'held' | 'in-app' {
  if (outcomes.some(outcome => outcome.status === 'accepted')) return 'delivered';
  if (outcomes.some(({status, httpStatus, attempt}) => retryable(status, httpStatus, attempt))) return 'pending';
  return subscriptionCount > 0 ? 'held' : 'in-app';
}
