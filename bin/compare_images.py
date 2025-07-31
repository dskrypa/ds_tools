#!/usr/bin/env python

import logging

from cli_command_parser import Command, Positional, Option, Flag, Counter, main, inputs

log = logging.getLogger(__name__)


class ImageComparer(Command, description='Compare images'):
    path_a = Positional(type=inputs.Path(type='file', exists=True), help='Path to an image file')
    path_b = Positional(type=inputs.Path(type='file', exists=True), help='Path to an image file')
    gray = Flag('--no-gray', '-G', default=True, help='Do not normalize images to grayscale before comparisons')
    normalize = Flag('--no-normalize', '-N', default=True, help='Do not normalize images for exposure differences before comparisons')
    max_width = Option('-W', type=int, help='Resize images that have a width greater than this value')
    max_height = Option('-H', type=int, help='Resize images that have a height greater than this value')
    same = Flag('-s', help='Include comparisons intended for images that are the same')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.images.compare import ComparableImage

        image_args = (self.gray, self.normalize, self.max_width, self.max_height)
        img_a = ComparableImage(self.path_a, *image_args)
        img_b = ComparableImage(self.path_b, *image_args)
        log.log(19, f'Comparing:\n{img_a}\nto\n{img_b}')

        methods = {
            'taxicab_distance': 'lower values = more similar',
            # 'zero_norm': '0-1',
            'mean_squared_error': 'lower values = more similar',
            'mean_structural_similarity': '0-1; higher values = more similar',
            'is_same_as': 'bool',
            'is_similar_to': 'bool',
        }
        if self.same:
            methods.update({
                'euclidean_root_mse': '',
                'min_max_root_mse': '',
                'mean_root_mse': '',
                'peak_signal_noise_ratio': 'higher values ~= higher quality if image A is an original version of image B',
            })

        for method, description in methods.items():
            result = getattr(img_a, method)(img_b)
            if isinstance(result, tuple):
                overall, per_pix = result
                log.info(f'{method:>26s}: {overall:17,.3f}  -  per pixel: {per_pix:10,.6f}  ({description})')
            else:
                if method in ('is_same_as', 'is_similar_to'):
                    log.info(f'{method:>26s}: {result!r:>17}{" " * 26}  ({description})')
                else:
                    log.info(f'{method:>26s}: {result:17,.3f}{" " * 26}  ({description})')


if __name__ == '__main__':
    main()
