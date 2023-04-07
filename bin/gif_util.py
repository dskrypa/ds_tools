#!/usr/bin/env python

from cli_command_parser import Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, main, inputs

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.images.animated.gif import AnimatedGif


class GifUtil(Command, description='Utility for working with animated GIFs'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None, names=None)


class C2A(GifUtil, help='Convert the specified color to alpha'):
    path = Positional(help='Path to the input file')
    output = Positional(help='Path for the output file')
    color = Option('-c', required=True, metavar='RGB', help='Color to convert to alpha as an RGB hex code')
    disposal = Option('-d', type=int, nargs='+', help='Way to treat the graphic after displaying it. Specify 1 value to apply to all, or per-frame values. 1: Do not dispose; 2: Restore to bg color; 3: Restore to prev content')

    def main(self):
        orig = AnimatedGif(self.path)
        updated = orig.color_to_alpha(self.color)
        disposal = _int_or_list(self.disposal)
        updated.save(self.output, duration=orig.info['duration'], transparency=0, disposal=disposal)


class Split(GifUtil, help='Save each frame of an animated gif as a separate file'):
    path = Positional(help='Path to the input file')
    output_dir = Positional(help='Path to the input file')
    prefix = Option('-p', default='frame_', help='Frame filename prefix')
    format = Option('-f', default='PNG', help='Image format for output files')

    def main(self):
        AnimatedGif(self.path).save_frames(self.output_dir, prefix=self.prefix, format=self.format)


class Combine(GifUtil, help='Combine multiple images into a single animated gif'):
    paths = Positional(nargs='+', help='Input file paths')
    output = Option('-o', required=True, metavar='PATH', help='Output file path')
    disposal = Option(type=int, nargs='+', help='Way to treat the graphic after displaying it. Specify 1 value to apply to all, or per-frame values. 1: Do not dispose; 2: Restore to bg color; 3: Restore to prev content')
    duration = Option('-d', type=int, nargs='+', help='Duration between frames in milliseconds. Specify 1 value to apply to all, or per-frame values')

    def main(self):
        kwargs = dict(zip(('disposal', 'duration'), map(_int_or_list, (self.disposal, self.duration))))
        AnimatedGif(self.paths).save(self.output, **kwargs)


class Info(GifUtil, help='Display information about the given image'):
    path = Positional(type=inputs.Path(type='file', exists=True), help='Path to the input file')

    with ParamGroup(mutually_exclusive=True):
        all = Flag('-a', help='Show information about all frames')
        frames = Option('-f', type=int, help='Show information about up to the specified number of frames')

    def main(self):
        from ds_tools.images.utils import get_image_info

        try:
            AnimatedGif(self.path).print_info(self.all or self.frames or False)
        except ValueError:
            print(get_image_info(self.path, True, self.path.as_posix()))


def _int_or_list(value):
    if not value:
        return None
    return value[0] if len(value) == 1 else value


if __name__ == '__main__':
    main()
