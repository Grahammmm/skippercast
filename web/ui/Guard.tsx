// Render failures stay in this panel; event handlers and asynchronous effects
// need their own error handling, not this render boundary.
import {Component, type ComponentChildren} from 'preact';
import './guard.css';

type Props = {name: string; children: ComponentChildren};
type State = {failed: boolean; name?: string};
export class Guard extends Component<Props, State> {
  override state: State = {failed: false};
  // A view ternary reuses this instance for the next panel; a new name starts clean.
  static override getDerivedStateFromProps({name}: Props, state: State) { return state.name === name ? null : {failed: false, name}; }
  static override getDerivedStateFromError() { return {failed: true}; }
  override componentDidCatch(error: unknown) {
    console.error('[guard]', this.props.name, error);
  }
  render({name, children}: Props, {failed}: State) {
    return failed ? <div class="ui-guard" role="status" data-guard={name}>
      <p>This part could not load. The rest of the page still works.</p>
      <button type="button" onClick={() => this.setState({failed: false})}>Try again</button>
    </div> : children;
  }
}
