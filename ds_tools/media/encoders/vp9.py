"""
VP9 Transcoding utils

:author: Doug Skrypa
"""

import logging
from csv import DictReader
from typing import Union

from ...core.decorate import cached_classproperty
from .base import Encoder

__all__ = ['Vp9Encoder']
log = logging.getLogger(__name__)

VP9_MIN_QUALITY_SETTINGS = """
width,height,     fps,bit_rate,min_bit_rate,max_bit_rate,crf,speed_1,speed_2,tile-columns,threads,
1280,    720,24;25;30,    1024,         512,        1485, 32,      4,      2,           2,      8,
1280,    720,   50;60,    1800,         900,        2610, 32,      4,      2,           2,      8,
1920,   1080,24;25;30,    1800,         900,        2610, 31,      4,      2,           2,      8,
1920,   1080,   50;60,    3000,        1500,        4350, 31,      4,      2,           2,      8,
2560,   1440,24;25;30,    6000,        3000,        8700, 24,      4,      2,           3,     16,
2560,   1440,   50;60,    9000,        4500,       13050, 24,      4,      2,           3,     16,
3840,   2160,24;25;30,   12000,        6000,       17400, 15,      4,      2,           3,     16,
3840,   2160,   50;60,   18000,        9000,       26100, 15,      4,      2,           3,     16,
"""


class Vp9Encoder(Encoder, codec='vp9'):
    def __init__(self, *args, use_min: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if use_min:
            options = self.get_min_quality_options(*self.new_resolution, fps=self.new_fps)
            self.options = options | self.options

    @cached_classproperty
    def all_quality_settings(cls) -> list[dict[str, Union[str, int]]]:
        reader = DictReader(VP9_MIN_QUALITY_SETTINGS.strip().splitlines(), skipinitialspace=True)
        return [{k: v if k == 'fps' else int(v) for k, v in row.items()} for row in reader]

    @classmethod
    def get_min_quality_options(cls, width: int, height: int, fps: float) -> dict[str, Union[str, int]]:
        fps_group = '24;25;30' if fps < 40 else '50;60'
        for row in cls.all_quality_settings:  # noqa
            if row['width'] == width and row['height'] == height and fps_group == row['fps']:
                return row

        raise ValueError(f'No pre-configured VP9 options for resolution={width}x{height} with {fps=}')

    def get_args(self, audio: str = None, pass_num: int = None) -> list[str]:
        args = super().get_args(audio, pass_num)
        args += ['-quality', 'good', '-g', '240']
        args += self._get_speed(pass_num)

        key_opt_map = {
            'bit_rate': '-b:v',
            'min_bit_rate': '-minrate',
            'max_bit_rate': '-maxrate',
            'tile-columns': '-tile-columns',
            'threads': '-threads',
            'crf': '-crf',
        }

        options = self.options
        for key, option in key_opt_map.items():
            try:
                val = options[key]
            except KeyError:
                pass
            else:
                if key.endswith('bit_rate'):
                    val = f'{val}k'
                args += [option, val]

        return args

    def _get_speed(self, pass_num: int) -> list[str]:
        try:
            speed = self.options[f'speed_{pass_num}']
        except KeyError:
            return []
        else:
            return ['-speed', speed]
