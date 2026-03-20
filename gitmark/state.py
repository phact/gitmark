"""State management for gitmark plan stored in .git/gitmark"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from .git_ops import get_git_dir


@dataclass
class NamedCommit:
    """Represents a named commit in the plan"""
    tag: str
    hunks: List[str] = field(default_factory=list)
    message: Optional[str] = None
    exec_command: Optional[str] = None
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> 'NamedCommit':
        return NamedCommit(**data)


@dataclass
class Plan:
    """The full gitmark plan"""
    commits: List[NamedCommit] = field(default_factory=list)
    next_order: int = 0

    def to_dict(self) -> dict:
        return {
            'commits': [c.to_dict() for c in self.commits],
            'next_order': self.next_order
        }

    @staticmethod
    def from_dict(data: dict) -> 'Plan':
        commits = [NamedCommit.from_dict(c) for c in data.get('commits', [])]
        next_order = data.get('next_order', 0)
        return Plan(commits=commits, next_order=next_order)

    def get_commit(self, tag: str) -> Optional[NamedCommit]:
        for commit in self.commits:
            if commit.tag == tag:
                return commit
        return None

    def add_commit(self, tag: str) -> NamedCommit:
        existing = self.get_commit(tag)
        if existing:
            return existing
        commit = NamedCommit(tag=tag, order=self.next_order)
        self.commits.append(commit)
        self.next_order += 1
        return commit

    def remove_commit(self, tag: str) -> bool:
        for i, commit in enumerate(self.commits):
            if commit.tag == tag:
                self.commits.pop(i)
                return True
        return False

    def find_hunk_owner(self, hunk_id: str) -> Optional[str]:
        for commit in self.commits:
            if hunk_id in commit.hunks:
                return commit.tag
        return None

    def get_sorted_commits(self) -> List[NamedCommit]:
        return sorted(self.commits, key=lambda c: c.order)


class StateManager:
    def __init__(self):
        self.state_file = None

    def _get_state_file(self) -> str:
        if self.state_file is None:
            git_dir = get_git_dir()
            self.state_file = os.path.join(git_dir, 'gitmark')
        return self.state_file

    def load(self) -> Plan:
        state_file = self._get_state_file()
        if not os.path.exists(state_file):
            return Plan()
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
            return Plan.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return Plan()

    def save(self, plan: Plan) -> None:
        state_file = self._get_state_file()
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump(plan.to_dict(), f, indent=2)

    def delete(self) -> None:
        state_file = self._get_state_file()
        if os.path.exists(state_file):
            os.remove(state_file)
