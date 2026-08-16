"""
Dry/normal run verb prefixes for user-facing log messages.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from functools import cached_property
from typing import ContextManager, Iterator, Type

__all__ = ['LoggingPrefix', 'Verb', 'DryRunMixin']


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
    __slots__ = ('base', '_present_participle', '_past_participle', 'double_last', 'drop_last', 'auto')

    def __init__(
        self,
        base: str | None = None,
        *,
        present_participle: str | None = None,  # -ing
        past_participle: str | None = None,  # -ed
        double_last: bool = False,
        drop_last: bool = False,
        auto: bool = False,
    ):
        self.base = base
        self._present_participle = present_participle
        self._past_participle = past_participle
        self.double_last = double_last
        self.drop_last = drop_last
        self.auto = auto

    def __set_name__(self, owner, name: str):
        if not self.base:
            self.base = name

    @property
    def present_participle(self) -> str:
        if self._present_participle:
            return self._present_participle

        base: str = self.base  # type: ignore
        if self.auto:
            return get_present_participle(base)

        if self.double_last:
            base += base[-1]
        elif self.drop_last:
            base = base[:-1]
        return base + 'ing'

    @property
    def past_participle(self) -> str:
        if self._past_participle:
            return self._past_participle

        base: str = self.base  # type: ignore
        suffix = 'd' if base.endswith('e') else 'ed'
        return base + suffix

    def conjugate(self, dry_run: bool = False, tense: Tense = Tense.PRESENT) -> str:
        if dry_run:
            return f'[DRY RUN] Would {self.base}'
        elif tense == Tense.PRESENT:
            return self.present_participle.capitalize()
        else:
            return self.past_participle.capitalize()

    def __get__(self, instance: LoggingPrefix | None, owner: Type[LoggingPrefix]) -> Verb | str:
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
            if self._tense == Tense.PRESENT:
                return Verb(verb, auto=True).conjugate(self.dry_run)

            raise KeyError(verb) from None

    def __getattr__(self, verb: str) -> str:
        if self._tense == Tense.PRESENT:
            return Verb(verb.replace('_', ' '), auto=True).conjugate(self.dry_run)

        raise AttributeError(verb)

    @contextmanager
    def _temp_tense(self, tense: Tense) -> Iterator[LoggingPrefix]:
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
    replace = Verb(drop_last=True)
    remove = Verb(drop_last=True)
    rename = Verb(drop_last=True)
    reset = Verb(double_last=True, past_participle='reset')
    run = Verb(double_last=True, past_participle='ran')
    save = Verb(drop_last=True)
    send = Verb()
    update = Verb(drop_last=True)


class DryRunMixin:
    __dry_run: bool = False

    @property
    def dry_run(self) -> bool:
        return self.__dry_run

    @dry_run.setter
    def dry_run(self, value: bool):
        self.__dry_run = value
        self.lp.dry_run = value

    @cached_property
    def lp(self) -> LoggingPrefix:
        return LoggingPrefix(self.dry_run)


def get_present_participle(lemma: str) -> str:
    """
    Attempts to lemmatize the given base word to the present participle / gerund form.

    Does not handle irregular verbs (e.g., "lie" -> "lying").

    See also: https://en.wikipedia.org/wiki/Lemmatization

    :param lemma: The base form of a given verb or verb phrase (e.g., "set up")
    :returns: The present participle / gerund (the "-ing form") for the given lemma
    """
    try:
        base, extra = lemma.split(' ', 1)
    except ValueError:
        base, extra = lemma, None

    gerund = _get_present_participle_base(base) + 'ing'
    return gerund if extra is None else f'{gerund} {extra}'


def _get_present_participle_base(lemma: str) -> str:
    if len(lemma) < 3:
        return lemma

    # Any further expansion of the below rules should likely adopt an exception dictionary.  If any special cases
    # below end up having more exception entries than words that are handled by the special case, then the case and its
    # exceptions should likely be inverted.

    match tuple(lemma[-3:].lower()):
        case ['n', 'g', 'e'] | [_, ('e' | 'o' | 'y'), 'e']:
            # E.g., levee -> leveeing; canoe -> canoeing; dye -> dyeing; singe -> singeing
            return lemma

        case [_, _, 'e']:
            # E.g., create -> creating; save -> saving; imbue -> imbuing
            return lemma[:-1]

        case [_, 'e', 'n'] | [_, 'i', 't']:
            if len(lemma) == 3 or lemma.lower() == 'emit':
                # E.g., sit -> sitting; pen -> penning; emit -> emitting
                # Maybe there are other cases where the last letter should be doubled, but there seem to be more cases
                # matching this pattern that shouldn't be doubled.
                return lemma + lemma[-1]

            # E.g., open -> opening; exit -> exiting; limit -> limiting
            return lemma

        case [x, ('a' | 'e' | 'i' | 'o' | 'u'), ('b' | 'd' | 'g' | 'l' | 'm' | 'n' | 'p' | 'r' | 't')]:
            if x in 'aeiou':
                # E.g., meet -> meeting; preen -> preening; moon -> mooning; bargain -> bargaining
                return lemma

            # E.g., begin -> beginning; reset -> resetting; run -> running
            return lemma + lemma[-1]

        case [_, 'i', 'c']:
            # E.g., panic -> panicking; mimic -> mimicking
            return lemma + 'k'

        case _:
            # E.g., add -> adding; copy -> copying; send -> sending
            return lemma
