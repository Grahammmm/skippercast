// Header badge with the best morning of the week (#best-day-banner). The
// button itself stays in index.html (weather-ui.js handles its click); this
// renders its label and value and keeps its state attributes in step.
import {useLayoutEffect} from 'preact/hooks';
import {outlook, type Outlook} from '../views.ts';

export function OutlookBadge({host, value}: {host?: HTMLElement | null; value?: Outlook}) {
  const o = value ?? outlook.value;
  useLayoutEffect(() => {
    if (!host) return;
    host.classList.toggle('qualifying', !!o.qualifying);
    if (o.ariaLabel) host.setAttribute('aria-label', o.ariaLabel);
    if (o.hour !== undefined) host.dataset.hour = String(o.hour);
  }, [host, o]);
  return <><span>{o.label}</span><strong>{o.value}</strong></>;
}
