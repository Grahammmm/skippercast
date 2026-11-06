// Render failures stay in this panel; event handlers and asynchronous effects
// need their own error handling, not this render boundary.
import {Component, type ComponentChildren} from 'preact';
import {language, t} from '../i18n.ts';
import './guard.css';

type Props = {name: string; children: ComponentChildren};
type State = {failed: boolean; name?: string};
// A function component, so the visible fallback tracks the language signal without resetting the failure.
export function GuardFallback({name, onRetry}: {name: string; onRetry: () => void}) {
  const lang = language.value;
  return <div class="ui-guard" role="status" data-guard={name}>
    <p>{t('shared.guard.failed', lang)}</p>
    <button type="button" onClick={onRetry}>{t('shared.guard.retry', lang)}</button>
  </div>;
}
export class Guard extends Component<Props, State> {
  override state: State = {failed: false};
  // A view ternary reuses this instance for the next panel; a new name starts clean.
  static override getDerivedStateFromProps({name}: Props, state: State) { return state.name === name ? null : {failed: false, name}; }
  static override getDerivedStateFromError() { return {failed: true}; }
  override componentDidCatch(error: unknown) {
    console.error('[guard]', this.props.name, error);
  }
  render({name, children}: Props, {failed}: State) {
    return failed ? <GuardFallback name={name} onRetry={() => this.setState({failed: false})} /> : children;
  }
}
