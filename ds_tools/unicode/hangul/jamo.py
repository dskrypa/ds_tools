"""
:author: Doug Skrypa
"""

from enum import IntFlag
from itertools import product
from typing import Union, Optional, Iterator

from .constants import JAMO_START, MEDIAL_START, INITIAL_OFFSETS, FINAL_OFFSETS, COMBO_CHANGES
from .constants import ROMANIZED_SHORT_NAMES, ROMANIZED_LONG_NAMES

__all__ = ['JamoType', 'Jamo', 'Syllable', 'Word']

_Jamo = Union[str, 'Jamo', None]


class JamoType(IntFlag):
    INITIAL = 1  # Leading consonant
    MEDIAL = 2  # Vowel
    FINAL = 4  # Final consonant


class Jamo:
    __instances = {}
    __slots__ = ('char', 'type', 'romanizations', 't_stop', 'sh_vowel', 'ord')

    def __init__(
        self,
        char: str,
        type: Union[JamoType, int],  # noqa
        romanizations: set[str],
        t_stop: bool = False,
        sh_vowel: bool = False,
    ):
        self.char = char
        self.type = type
        self.romanizations = romanizations
        self.t_stop = t_stop
        self.sh_vowel = sh_vowel
        self.ord = ord(char)
        self.__instances[self.char] = self

    @classmethod
    def for_char(cls, char: str) -> 'Jamo':
        try:
            return cls.__instances[char]
        except KeyError as e:
            raise ValueError(f'Not a Jamo: {char!r}') from e

    @classmethod
    def _for_ord(cls, char_ord: int) -> 'Jamo':
        return cls.__instances[chr(char_ord)]

    @classmethod
    def decompose(cls, char: str) -> tuple['Jamo', 'Jamo', Optional['Jamo']]:
        # syllable = 588 initial + 28 medial + final + 44032
        i, rem = divmod(ord(char) - 44032, 588)
        m, f = divmod(rem, 28)
        jamo = cls._for_ord
        js = JAMO_START
        return jamo(js + INITIAL_OFFSETS[i]), jamo(MEDIAL_START + m), jamo(js + FINAL_OFFSETS[f]) if f > 0 else None

    def __repr__(self) -> str:
        return f'<Jamo[{self.char!r}, type={self.type}]>'

    def __str__(self) -> str:
        return self.char

    @property
    def ord_initial(self) -> int:
        return INITIAL_OFFSETS.index(self.ord - JAMO_START)

    @property
    def ord_medial(self) -> int:
        return self.ord - MEDIAL_START

    @property
    def ord_final(self) -> int:
        return FINAL_OFFSETS.index(self.ord - JAMO_START)

    def iter_romanizations(self, position: JamoType = JamoType.MEDIAL, medial: 'Jamo' = None) -> Iterator[str]:
        romanizations = self.romanizations
        if position & JamoType.INITIAL:
            if medial and medial.sh_vowel and (char := self.char) in {'ㅅ', 'ㅆ'}:
                yield from ('sh', 'ssh') if char == 'ㅆ' else ('sh',)
            elif self.char == 'ㅇ':
                romanizations = ('',)
        elif position & JamoType.FINAL and self.t_stop:
            yield 't'

        yield from romanizations

    def get_romanizations(self, position: JamoType = JamoType.MEDIAL, medial: 'Jamo' = None) -> set[str]:
        return set(self.iter_romanizations(position, medial))
        # if position & JamoType.INITIAL:
        #     if medial and medial.sh_vowel and (char := self.char) in {'ㅅ', 'ㅆ'}:
        #         romanizations = self.romanizations.copy()
        #         romanizations.add('sh')
        #         if char == 'ㅆ':
        #             romanizations.add('ssh')
        #     elif self.char == 'ㅇ':
        #         romanizations = {''}
        #     else:
        #         romanizations = self.romanizations
        # elif position & JamoType.FINAL and self.t_stop:
        #     romanizations = self.romanizations.copy()
        #     romanizations.add('t')
        # else:
        #     romanizations = self.romanizations
        # return romanizations

    def get_romanization_pattern(self, position: JamoType = JamoType.MEDIAL, medial: 'Jamo' = None) -> str:
        singles, doubles = [], []
        for rom in self.iter_romanizations(position, medial):
            if len(rom) == 1:
                singles.append(rom)
            elif rom:
                doubles.append(rom)

        single_str = '[{}]'.format(''.join(singles)) if singles else ''
        double_str = '|'.join(f'{d[0]}{{1,2}}' if d[0] == d[1] else d for d in doubles) if doubles else ''
        combined = (double_str + '|' + single_str) if single_str and double_str else single_str or double_str
        # print(f'{self!r}.get_romanization_pattern({position}, {medial=}) -> {single_str=} {double_str=} {combined=}')
        return f'(?:{combined})' if double_str else combined  # double always needs the group


class Syllable:
    __slots__ = ('_initial', '_medial', '_final', '_composed')

    def __init__(self, initial: _Jamo, medial: _Jamo, final: _Jamo = None, composed: str = None):
        self.initial = initial
        self.medial = medial
        self.final = final
        self._composed = composed

    @classmethod
    def from_char(cls, char: str) -> 'Syllable':
        return cls(*Jamo.decompose(char), composed=char)

    # region Jamo Properties / Validation

    @property
    def initial(self) -> Optional[Jamo]:
        return self._initial

    @initial.setter
    def initial(self, value: _Jamo):
        if not value:
            raise ValueError('An initial consonant jamo is required')
        self._initial = self._validate(value, JamoType.INITIAL)

    @property
    def medial(self) -> Optional[Jamo]:
        return self._medial

    @medial.setter
    def medial(self, value: _Jamo):
        if not value:
            raise ValueError('A medial vowel jamo is required')
        self._medial = self._validate(value, JamoType.MEDIAL)

    @property
    def final(self) -> Optional[Jamo]:
        return self._final

    @final.setter
    def final(self, value: _Jamo):
        self._final = self._validate(value, JamoType.FINAL)

    @classmethod
    def _validate(cls, jamo: _Jamo, position: JamoType):
        if jamo is None:
            return jamo
        if isinstance(jamo, str):
            try:
                jamo = JAMO[jamo]
            except KeyError as e:
                raise ValueError(f'Invalid character={jamo!r} - it is not a Korean jamo') from e
        if not jamo.type & position:
            raise ValueError(f'Invalid {jamo=} - it cannot be used in {position=}')
        return jamo

    # endregion

    def __getitem__(self, index: int):
        if index == 0:
            return self.initial
        elif index == 1:
            return self.medial
        elif index == 2:
            return self.final
        raise IndexError(f'Invalid {index=}')

    def __repr__(self) -> str:
        return f'<Syllable[{self.initial!r}, {self.medial!r}, {self.final!r}]>'

    def __str__(self) -> str:
        return self.composed

    @property
    def composed(self) -> str:
        if self._composed is None:
            initial = self.initial.ord_initial if self.initial else 0
            medial = self.medial.ord_medial if self.medial else 0
            final = self.final.ord_final if self.final else 0
            self._composed = chr(44032 + (initial * 588) + (medial * 28) + final)
        return self._composed

    def decompose(self) -> tuple[Optional[Jamo], Optional[Jamo], Optional[Jamo]]:
        return self.initial, self.medial, self.final

    @property
    def romanizations(self) -> set[str]:
        try:
            candidates = {ROMANIZED_SHORT_NAMES[self.composed]}
        except KeyError:
            candidates = set()

        medial = self.medial
        initials = self.initial.get_romanizations(JamoType.INITIAL, medial)
        finals = final.get_romanizations(JamoType.FINAL) if (final := self.final) else ('',)
        candidates.update(map(''.join, product(initials, medial.romanizations, finals)))
        return candidates

    @property
    def romanization_pattern(self) -> str:
        medial = self.medial
        initial_str = self.initial.get_romanization_pattern(JamoType.INITIAL, medial)
        medial_str = medial.get_romanization_pattern()
        final_str = final.get_romanization_pattern(JamoType.FINAL) if (final := self.final) else ''
        try:
            name = ROMANIZED_SHORT_NAMES[self.composed]
        except KeyError:
            return initial_str + medial_str + final_str
        else:
            return f'(?:{name}|{initial_str}{medial_str}{final_str})'


class Word:
    __slots__ = ('word', 'syllables')

    def __init__(self, word: str):
        self.word = word
        self.syllables = tuple(Syllable.from_char(c) for c in word)

    @property
    def romanizations(self) -> set[str]:
        try:
            candidates = {ROMANIZED_LONG_NAMES[self.word]}
        except KeyError:
            candidates = set()
        candidates.update(map(''.join, product(*(s.romanizations for s in self.syllables))))
        return candidates

    @property
    def romanization_pattern(self) -> str:
        pattern = ''.join(s.romanization_pattern for s in self.syllables)
        try:
            name = ROMANIZED_LONG_NAMES[self.word]
        except KeyError:
            return pattern
        else:
            return f'(?:{name}|{pattern})'


JAMO = {
    'ㄱ': Jamo('ㄱ', JamoType.INITIAL | JamoType.FINAL, {'g', 'k'}),
    'ㄲ': Jamo('ㄲ', JamoType.INITIAL | JamoType.FINAL, {'gg', 'kk'}),
    'ㄴ': Jamo('ㄴ', JamoType.INITIAL | JamoType.FINAL, {'n'}),
    'ㄷ': Jamo('ㄷ', JamoType.INITIAL | JamoType.FINAL, {'d', 't'}),
    'ㄸ': Jamo('ㄸ', JamoType.INITIAL | JamoType.FINAL, {'dd', 'tt'}),
    'ㄹ': Jamo('ㄹ', JamoType.INITIAL | JamoType.FINAL, {'r', 'l'}),
    'ㅁ': Jamo('ㅁ', JamoType.INITIAL | JamoType.FINAL, {'m'}),
    'ㅂ': Jamo('ㅂ', JamoType.INITIAL | JamoType.FINAL, {'b', 'p', 'v'}),
    'ㅃ': Jamo('ㅃ', JamoType.INITIAL | JamoType.FINAL, {'bb', 'pp'}),
    'ㅅ': Jamo('ㅅ', JamoType.INITIAL | JamoType.FINAL, {'s'}, t_stop=True),
    'ㅆ': Jamo('ㅆ', JamoType.INITIAL | JamoType.FINAL, {'ss'}, t_stop=True),
    'ㅇ': Jamo('ㅇ', JamoType.INITIAL | JamoType.FINAL, {'ng'}),
    'ㅈ': Jamo('ㅈ', JamoType.INITIAL | JamoType.FINAL, {'j', 'ch'}, t_stop=True),
    'ㅉ': Jamo('ㅉ', JamoType.INITIAL | JamoType.FINAL, {'jj'}, t_stop=True),
    'ㅊ': Jamo('ㅊ', JamoType.INITIAL | JamoType.FINAL, {'ch'}, t_stop=True),
    'ㅋ': Jamo('ㅋ', JamoType.INITIAL | JamoType.FINAL, {'k'}),
    'ㅌ': Jamo('ㅌ', JamoType.INITIAL | JamoType.FINAL, {'t'}),
    'ㅍ': Jamo('ㅍ', JamoType.INITIAL | JamoType.FINAL, {'p'}),
    'ㅎ': Jamo('ㅎ', JamoType.INITIAL | JamoType.FINAL, {'h'}, t_stop=True),
    'ㅏ': Jamo('ㅏ', JamoType.MEDIAL, {'a'}),
    'ㅐ': Jamo('ㅐ', JamoType.MEDIAL, {'ae'}),
    'ㅑ': Jamo('ㅑ', JamoType.MEDIAL, {'ya'}, sh_vowel=True),
    'ㅒ': Jamo('ㅒ', JamoType.MEDIAL, {'yae'}),
    'ㅓ': Jamo('ㅓ', JamoType.MEDIAL, {'eo', 'u'}),
    'ㅔ': Jamo('ㅔ', JamoType.MEDIAL, {'e'}),
    'ㅕ': Jamo('ㅕ', JamoType.MEDIAL, {'yeo', 'you', 'yu'}, sh_vowel=True),
    'ㅖ': Jamo('ㅖ', JamoType.MEDIAL, {'ye'}),
    'ㅗ': Jamo('ㅗ', JamoType.MEDIAL, {'o', 'oh'}),
    'ㅘ': Jamo('ㅘ', JamoType.MEDIAL, {'wa'}),
    'ㅙ': Jamo('ㅙ', JamoType.MEDIAL, {'wae'}),
    'ㅚ': Jamo('ㅚ', JamoType.MEDIAL, {'oe'}),
    'ㅛ': Jamo('ㅛ', JamoType.MEDIAL, {'yo'}, sh_vowel=True),
    'ㅜ': Jamo('ㅜ', JamoType.MEDIAL, {'u', 'oo'}),
    'ㅝ': Jamo('ㅝ', JamoType.MEDIAL, {'weo', 'wo'}),
    'ㅞ': Jamo('ㅞ', JamoType.MEDIAL, {'we'}),
    'ㅟ': Jamo('ㅟ', JamoType.MEDIAL, {'wi'}),
    'ㅠ': Jamo('ㅠ', JamoType.MEDIAL, {'yu', 'yoo'}, sh_vowel=True),
    'ㅡ': Jamo('ㅡ', JamoType.MEDIAL, {'eu'}),
    'ㅢ': Jamo('ㅢ', JamoType.MEDIAL, {'eui', 'ui', 'ee'}),
    'ㅣ': Jamo('ㅣ', JamoType.MEDIAL, {'i', 'ee', 'y'}, sh_vowel=True),
    'ㄳ': Jamo('ㄳ', JamoType.FINAL, {'gs'}),
    'ㄵ': Jamo('ㄵ', JamoType.FINAL, {'nj'}),
    'ㄶ': Jamo('ㄶ', JamoType.FINAL, {'nh'}),
    'ㄺ': Jamo('ㄺ', JamoType.FINAL, {'rk', 'lk'}),
    'ㄻ': Jamo('ㄻ', JamoType.FINAL, {'rm', 'lm'}),
    'ㄼ': Jamo('ㄼ', JamoType.FINAL, {'rb', 'lb'}),
    'ㄽ': Jamo('ㄽ', JamoType.FINAL, {'rs', 'ls'}),
    'ㄾ': Jamo('ㄾ', JamoType.FINAL, {'rt', 'lt'}),
    'ㄿ': Jamo('ㄿ', JamoType.FINAL, {'rp', 'lp'}),
    'ㅀ': Jamo('ㅀ', JamoType.FINAL, {'rh', 'lh'}),
    'ㅄ': Jamo('ㅄ', JamoType.FINAL, {'bs', 'ps'}),
}
