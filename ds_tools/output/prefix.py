"""
Dry/normal run verb prefixes for user-facing log messages.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from typing import Optional, Type, Union, ContextManager

__all__ = ['LoggingPrefix', 'Verb']


class Tense(Enum):
    PRESENT = 'present'
    PAST = 'past'

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            try:
                return cls._member_map_[value.upper()]
            except KeyError:
                pass
        return super()._missing_(value)


class Verb:
    __slots__ = ('base', '_present_participle', '_past_participle', 'double_last', 'drop_last')

    def __init__(
        self,
        base: str = None,
        *,
        present_participle: str = None,  # -ing
        past_participle: str = None,  # -ed
        double_last: bool = False,
        drop_last: bool = False,
    ):
        self.base = base
        self._present_participle = present_participle
        self._past_participle = past_participle
        self.double_last = double_last
        self.drop_last = drop_last

    def __set_name__(self, owner, name: str):
        if not self.base:
            self.base = name

    @property
    def present_participle(self) -> str:
        if self._present_participle:
            return self._present_participle
        base = self.base
        if self.double_last:
            base += base[-1]
        elif self.drop_last:
            base = base[:-1]
        return base + 'ing'

    @property
    def past_participle(self) -> str:
        if self._past_participle:
            return self._past_participle
        base = self.base
        suffix = 'd' if base.endswith('e') else 'ed'
        return base + suffix

    def conjugate(self, dry_run: bool = False, tense: Tense = Tense.PRESENT) -> str:
        if dry_run:
            return f'[DRY RUN] Would {self.base}'
        elif tense == Tense.PRESENT:
            return self.present_participle.capitalize()
        else:
            return self.past_participle.capitalize()

    def __get__(self, instance: Optional[LoggingPrefix], owner: Type[LoggingPrefix]) -> Union[Verb, str]:
        if instance is None:
            return self
        return self.conjugate(instance.dry_run, instance.tense)


class LoggingPrefix:
    __slots__ = ('dry_run', '_tense')

    def __init__(self, dry_run: bool = False, tense: Tense | str = Tense.PRESENT):
        self.dry_run = dry_run
        self.tense = tense

    @property
    def tense(self) -> Tense:
        return self._tense

    @tense.setter
    def tense(self, value: Tense | str):
        self._tense = Tense(value)

    def __getitem__(self, verb: str) -> str:
        try:
            return getattr(self, verb)
        except AttributeError:
            raise KeyError(verb) from None

    @contextmanager
    def _temp_tense(self, tense: Tense) -> ContextManager[LoggingPrefix]:
        old = self._tense
        try:
            self._tense = tense
            yield self
        finally:
            self._tense = old

    def past_tense(self) -> ContextManager[LoggingPrefix]:
        return self._temp_tense(Tense.PAST)

    def present_tense(self) -> ContextManager[LoggingPrefix]:
        return self._temp_tense(Tense.PRESENT)

    add = Verb()
    begin = Verb(double_last=True)
    copy = Verb()
    create = Verb(drop_last=True)
    delete = Verb(drop_last=True)
    move = Verb(drop_last=True)
    remove = Verb(drop_last=True)
    rename = Verb(drop_last=True)
    reset = Verb(double_last=True, past_participle='reset')
    run = Verb(double_last=True, past_participle='ran')
    save = Verb(drop_last=True)
    send = Verb()
    update = Verb(drop_last=True)
