from dataclasses import dataclass, field


@dataclass
class AgentState:
    goal: str
    memory: dict[str, str] = field(default_factory=dict)
    documents: dict[str, str] = field(default_factory=dict)
    human_answers: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    status: str = 'running'
    final_message: str = ''

    def remember(self, key, value):
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError('Memory key and value must be strings.')

        key = key.strip()

        if not key or len(key) > 80 or len(value) > 1000:
            raise ValueError(
                'Use a key of 1-80 characters and a value up to 1000.'
            )

        if key not in self.memory and len(self.memory) >= 20:
            raise ValueError(
                'Scratchpad is full. Update an existing key.'
            )

        self.memory[key] = value
        return f'Remembered {key}: {value}'

    def context(self):
        # This small summary is re-sent to the worker each step.
        return {
            'memory': self.memory,
            'human_answers': self.human_answers,
            'approval_denied': any(
                not decision['approved']
                for decision in self.approvals
            ),
        }