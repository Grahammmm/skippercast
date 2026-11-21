type WatchPushStep = 'ready' | 'enable' | 'blocked' | 'unsupported';
type WatchSaveStep = 'save' | 'enable-push' | 'note-blocked' | 'note-unsupported';

export function watchPushStep(env: {
  serviceWorker: boolean;
  pushManager: boolean;
  publicKey: string | null | undefined;
  permission: string;
  subscribed: boolean;
}): WatchPushStep {
  if (!env.serviceWorker || !env.pushManager || !env.publicKey) return 'unsupported';
  if (env.permission === 'denied') return 'blocked';
  if (env.permission === 'granted') return env.subscribed ? 'ready' : 'enable';
  if (env.permission === 'default') return 'enable';
  return 'unsupported';
}

export function watchSaveSteps(step: WatchPushStep): WatchSaveStep[] {
  switch (step) {
    case 'ready': return ['save'];
    case 'enable': return ['save', 'enable-push'];
    case 'blocked': return ['save', 'note-blocked'];
    case 'unsupported': return ['save', 'note-unsupported'];
  }
}
