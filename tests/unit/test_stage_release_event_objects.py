"""Malformed STAGE event objects give field-specific holds without logging values."""

import pytest

from scripts.relief import stage_release
from skippercast.relief import stage_transport as stage


@pytest.mark.parametrize('value', [None, ['payload-value'], False])
@pytest.mark.parametrize('event_name, field', [
    ('workflow_dispatch', 'inputs'),
    ('workflow_run', 'workflow_run'),
    ('workflow_run', 'workflow_run.head_repository'),
])
def test_malformed_event_object(event_name, field, value):
    env = dict(GITHUB_REPOSITORY=stage.REPOSITORY, GITHUB_REF='refs/heads/main',
               GITHUB_REF_PROTECTED='true', RUNNER_ENVIRONMENT='github-hosted',
               GITHUB_EVENT_NAME=event_name)
    if field == 'workflow_run.head_repository':
        event = dict(action='completed', workflow_run=dict(
            path='.github/workflows/ci.yml', name='Offline checks', event='push',
            head_branch='main', status='completed', conclusion='success', head_repository=value,
        ))
    else:
        event = {'action': 'completed', field: value}

    # A dict default misses explicit null; truthiness also hides false-valued non-objects.
    with pytest.raises(stage.StageError) as caught:
        stage_release.deploy_mode(env, event)
    assert str(caught.value) == f'event field {field} must be a JSON object'
