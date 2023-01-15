"""
Dry/normal run verb prefixes for user-facing log messages.
"""

from __future__ import annotations

from typing import Optional, Type, Union

__all__ = ['LoggingPrefix', 'Verb']


class Verb:
    __slots__ = ('base', '_present_participle', 'double_last', 'drop_last')

    def __init__(
        self,
        base: str = None,
        *,
        present_participle: str = None,  # -ing
        double_last: bool = False,
        drop_last: bool = False,
    ):
        self.base = base
        self._present_participle = present_participle
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

    def conjugate(self, dry_run: bool = False) -> str:
        if not dry_run:
            return self.present_participle.capitalize()
        return f'[DRY RUN] Would {self.base}'

    def __get__(self, instance: Optional[LoggingPrefix], owner: Type[LoggingPrefix]) -> Union[Verb, str]:
        if instance is None:
            return self
        return self.conjugate(instance.dry_run)


class LoggingPrefix:
    __slots__ = ('dry_run',)

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def __getitem__(self, verb: str) -> str:
        try:
            return getattr(self, verb)
        except AttributeError:
            raise KeyError(verb) from None

    add = Verb()
    create = Verb(drop_last=True)
    delete = Verb(drop_last=True)
    run = Verb(double_last=True)
    save = Verb(drop_last=True)
