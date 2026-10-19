from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


class Trace:
    def __init__(
        self,
        goal,
        model=None,
        verifier_model=None,
        root=None,
    ):
        stamp = datetime.now(timezone.utc).strftime(
            '%Y%m%dT%H%M%S_%fZ'
        )
        self.run_dir = Path(root or PROJECT_ROOT / 'runs') / stamp
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.path = self.run_dir / 'trace.json'

        self.data = {
            'goal': goal,
            'model': model,
            'verifier_model': verifier_model,
            'started_at': now(),
            'status': 'running',
            'events': [],
        }
        self._save()

    def _save(self):
        text = json.dumps(
            self.data,
            ensure_ascii=False,
            indent=2,
        )

        for name in ('LLM_API_KEY', 'GROQ_API_KEY'):
            secret = os.getenv(name)
            if secret:
                text = text.replace(secret, '[REDACTED]')

        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(self.path)

    def log(self, kind, **details):
        event = {
            'number': len(self.data['events']) + 1,
            'time': now(),
            'type': kind,
            'details': deepcopy(details),
        }
        self.data['events'].append(event)
        self._save()

    def screenshot(self, browser):
        number = len(self.data['events']) + 1
        path = self.run_dir / f'{number:03d}.png'

        try:
            browser.screenshot(path)
        except Exception as error:
            self.log('screenshot_error', error=str(error))
            return None

        self.log('screenshot', file=path.name)
        return str(path)

    def finish(self, status, message):
        self.data.update({
            'status': status,
            'final_message': message,
            'finished_at': now(),
        })
        self.log('finished', status=status, message=message)


if __name__ == '__main__':
    from agent.state import AgentState

    state = AgentState('Check scratchpad and trace recording.')
    state.remember('test_fact', 'hello')

    trace = Trace(state.goal)
    trace.log('smoke_test', context=state.context())
    trace.finish('completed', 'Scratchpad and trace check passed.')

    saved = json.loads(
        trace.path.read_text(encoding='utf-8')
    )
    recorded = saved['events'][0]['details']['context']['memory']

    if (
        recorded != {'test_fact': 'hello'}
        or saved['status'] != 'completed'
    ):
        raise RuntimeError(
            'Saved trace did not match the expected result.'
        )

    print('Scratchpad:', state.memory)
    print('Trace saved:', trace.path)
    print('State and trace check passed.')