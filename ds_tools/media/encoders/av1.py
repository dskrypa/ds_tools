"""
AV1 Transcoding utils

:author: Doug Skrypa
"""

import logging

from .base import Encoder

__all__ = ['Av1Encoder']
log = logging.getLogger(__name__)

CRF_ARG = '-qp'  # TODO: Switch to '-crf' once it works


class Av1Encoder(Encoder, codec='av1', default_encoder='libsvtav1'):
    def get_args(self, audio: str = None, pass_num: int = None) -> list[str]:
        args = super().get_args(audio, pass_num)
        width, height = self.new_resolution
        if height <= 720:
            crf = 32
            preset = 12
        elif height <= 1080:
            crf = 27
            preset = 9
        else:
            preset = 8
            crf = 24 if height <= 1440 else 15 if height <= 2160 else 5

        args += [CRF_ARG, str(crf), '-preset', str(preset)]
        return args
