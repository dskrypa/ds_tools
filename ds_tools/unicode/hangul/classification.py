from .constants import (
    SYLLABLES_START, SYLLABLES_END, JAMO_START, MEDIAL_START, MEDIAL_END, INITIAL_OFFSETS, FINAL_OFFSETS
)

__all__ = ['is_hangul_syllable', 'is_jamo', 'is_lead_jamo', 'is_vowel_jamo', 'is_final_jamo']


def is_hangul_syllable(char: str) -> bool:
    if len(char) != 1:
        return False
    return SYLLABLES_START <= ord(char) <= SYLLABLES_END


def is_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return JAMO_START < ord(char) <= MEDIAL_END


def is_lead_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_START) in INITIAL_OFFSETS


def is_vowel_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return MEDIAL_START <= ord(char) <= MEDIAL_END


def is_final_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_START) in FINAL_OFFSETS
