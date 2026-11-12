// Scroll cue (UXFIX-03, design § 6 item 8): a scroll area with more below fades its bottom 16 px (web/ui/ui.css
// `.ui-scroll-cue[data-more="true"]`) and drops the fade at the end. This hook only sets `data-more` from one read of the
// scroll geometry, on mount, on scroll (passive), when the box resizes and when its content changes (a capped box does not
// resize when its list gets longer or shorter). A sticky action row marked `data-cue-inset` stays out of the fade: its
// height becomes `--cue-inset`, so the fade ends above it.
import {useEffect} from 'preact/hooks';
import type {RefObject} from 'preact';

export function useScrollCue(ref: RefObject<HTMLElement>): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const more = el.scrollHeight - el.scrollTop - el.clientHeight > 1;
      if (el.dataset.more !== String(more)) el.dataset.more = String(more);
      const inset = el.querySelector<HTMLElement>('[data-cue-inset]')?.offsetHeight;
      if (inset) el.style.setProperty('--cue-inset', `${inset}px`);
      else el.style.removeProperty('--cue-inset');
    };
    update();
    el.addEventListener('scroll', update, {passive: true});
    const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(update) : null;
    resize?.observe(el);
    const mutate = typeof MutationObserver === 'function' ? new MutationObserver(update) : null;
    mutate?.observe(el, {childList: true, subtree: true});
    return () => {
      el.removeEventListener('scroll', update);
      resize?.disconnect();
      mutate?.disconnect();
    };
  }, [ref]);
}
