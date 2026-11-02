// Render failures stay in this panel; event handlers and asynchronous effects
// need their own error handling, not this render boundary.
import {Component, type ComponentChildren} from 'preact';
import './guard.css';

type Props = {name: string; children: ComponentChildren};
export class Guard extends Component<Props, {failed: boolean}> {
  override state = {failed: false};
  static override getDerivedStateFromError() { return {failed: true}; }
  override componentDidCatch(error: unknown) {
    console.error('[guard]', this.props.name, error);
  }
  render({name, children}: Props, {failed}: {failed: boolean}) {
    return failed ? <div class="ui-guard" role="status" data-guard={name}>
      <p>This part could not load. The rest of the page still works.</p>
      <button type="button" onClick={() => this.setState({failed: false})}>Try again</button>
    </div> : children;
  }
}
