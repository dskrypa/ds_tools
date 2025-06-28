#!/usr/bin/env python

from __future__ import annotations

import logging
from collections import Counter as _Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import chdir
from dataclasses import dataclass
from functools import cached_property
from multiprocessing import set_start_method
from pathlib import Path
from subprocess import check_call, check_output
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Iterable, Sequence

from cli_command_parser import Command, ParamGroup, Positional, Option, Counter, SubCommand, main
from cli_command_parser.inputs import Path as IPath, NumRange
from imageio.v3 import imread
from numpy import unique, uint32, array
from tqdm import tqdm

from ds_tools.output.formatting import format_duration
from ds_tools.images.geometry import COMMON_VIDEO_ASPECT_RATIOS, AspectRatio, Box

if TYPE_CHECKING:
    from numpy.typing import NDArray

log = logging.getLogger(__name__)
EXISTING_PATH = IPath(type='file|dir', exists=True)
THRESHOLD = NumRange(float, min=0, max=1, include_max=True)


class AspectRatioChangeFinder(Command, show_group_tree=True):
    """Find aspect ratio changes in a given video or sequence of images"""

    sub_cmd = SubCommand()

    with ParamGroup('Common'):
        verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
        parallel = Option('-P', default=20, type=int, help='Maximum number of workers to use in parallel')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)
        set_start_method('spawn')


class Fix(AspectRatioChangeFinder):
    in_path: Path = Option('-i', type=IPath(type='file', exists=True), required=True, help='A video file to examine')
    output: Path = Option('-o', type=IPath(type='file', exists=False), required=True, help='The output path')
    image_dir: Path = Option('-I', type=IPath(type='dir'), help='Save or load images to/from this location')
    max_sizes: int = Option('-s', default=2, help='Maximum number of size variations to allow')
    threshold: float = Option('-t', type=THRESHOLD, default=0.99, help='Letterbox area color match detection threshold')

    def main(self):
        log.warning(
            'THIS DOES NOT WORK'
            ' - It will produce a valid video, but VLC will not automatically switch between aspect ratios - '
            'THIS DOES NOT WORK'
        )
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            changes = self._find_ratio_changes(tmp_dir)
            split_dir = self._split_video(tmp_dir, changes)
            self._merge_parts(split_dir)

    def _find_ratio_changes(self, tmp_dir: Path) -> list[RatioChange]:
        if self.image_dir and self.image_dir.exists():
            image_dir = self.image_dir
        else:
            image_dir = self._convert_video_to_images(tmp_dir)

        processor = AspectRatioProcessor(image_dir, self.max_sizes, self.threshold, self.parallel)
        changes = processor.get_ratio_changes()
        self._max_image_box = processor.max_image_box
        self._src_aspect_ratio = processor.common_box_ratio_map[processor.max_image_box]

        if self.image_dir and not self.image_dir.exists():
            self.image_dir.parent.mkdir(parents=True, exist_ok=True)
            image_dir.rename(self.image_dir)

        return changes

    def _convert_video_to_images(self, tmp_dir: Path) -> Path:
        image_dir = tmp_dir.joinpath('images')
        image_dir.mkdir()
        log.info('Converting video to images...')
        with chdir(image_dir):
            cmd = [
                'ffmpeg',
                '-loglevel', 'warning',
                '-i', self.in_path.as_posix(),
                '-vf', r'select=bitor(gte(t-prev_selected_t\,1)\,isnan(prev_selected_t))',
                '-fps_mode', 'vfr',
                'still_%04d.jpg',
            ]
            check_call(cmd)

        return image_dir

    def _split_video(self, tmp_dir: Path, changes: Sequence[RatioChange]) -> Path:
        split_dir = tmp_dir.joinpath('split')
        split_dir.mkdir()
        log.info(f'Splitting video into {len(changes)} sections...')

        base_cmd = ['ffmpeg', '-i', self.in_path.as_posix()]
        with chdir(split_dir):
            with tqdm(total=len(changes), unit='section', smoothing=0.1, maxinterval=1) as prog_bar:
                for i, change in enumerate(changes):
                    cmd = base_cmd + ['-ss', change.time_stamp, '-to', change.end_str, '-c', 'copy']
                    if change.ratio != self._src_aspect_ratio:
                        cmd += ['-aspect', str(change.ratio) if change.ratio.y > 1 else str(change.ratio.x)]
                    cmd.append(f'part_{i:04d}.mkv')  # TODO: Handle mp4, etc

                    check_output(cmd)
                    prog_bar.update()

        return split_dir

    def _merge_parts(self, split_dir: Path):
        cmd = ['mkvmerge', '-o', self.output.as_posix()]  # sudo apt install mkvtoolnix
        for i, path in enumerate(sorted(split_dir.iterdir())):
            cmd.append(f'+{path.name}' if i else path.name)

        log.info(f'Merging split parts into {self.output.as_posix()}')
        with chdir(split_dir):
            check_call(cmd)


class Images(AspectRatioChangeFinder):
    image_dir: Path = Positional(
        type=IPath(type='dir', exists=True), help='Directory containing a sequence of images extracted from a video'
    )
    max_sizes: int = Option('-s', default=2, help='Maximum number of size variations to allow')
    threshold: float = Option('-t', type=THRESHOLD, default=0.99, help='Letterbox area color match detection threshold')

    def main(self):
        processor = AspectRatioProcessor(self.image_dir, self.max_sizes, self.threshold, self.parallel)
        changes = processor.get_ratio_changes()
        print(f'Found {len(changes)} aspect ratio changes:')
        for change in changes:
            print(f'  - {change}')


class AspectRatioProcessor:
    def __init__(self, image_dir: Path, max_sizes: int = 2, threshold: float = 0.99, parallel: int = 4):
        self.image_dir = image_dir
        self.max_sizes = max_sizes
        self.threshold = threshold
        self.parallel = parallel

    @cached_property
    def all_image_info(self) -> list[ImageInfo]:
        paths = sorted(self.image_dir.iterdir())
        log.info(f'Processing {len(paths)} images using {self.parallel} workers...')
        results = []
        with ProcessPoolExecutor(max_workers=self.parallel) as executor:
            with tqdm(total=len(paths), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
                try:
                    futures = {executor.submit(_get_image_info, path): path for path in paths}
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception as e:
                            log.error(f'Error opening {futures[future].as_posix()}: {e}')
                            prog_bar.update()
                        else:
                            prog_bar.update()
                except BaseException as e:
                    log.warning(f'Shutting down due to {e}')
                    executor.shutdown(cancel_futures=True)
                    raise

        results.sort()
        return results

    @cached_property
    def common_box_ratio_map(self) -> dict[Box, AspectRatio]:
        return {v: k for k, v in self.common_ratios.items()}

    def get_ratio_changes(self) -> list[RatioChange]:
        allowed_sizes = self.get_size_boxes()
        log.info(f'Found {len(allowed_sizes)} common aspect ratios:')
        for box, count in allowed_sizes.items():
            log.info(f' - Found {count} occurrences of {box=} with aspect ratio={self.common_box_ratio_map[box]}')

        changes: list[RatioChange] = []
        last = last_change = None
        for i, info in enumerate(self.all_image_info):
            box = info.find_closest_bbox(allowed_sizes)
            if box != last:
                try:
                    next_info = self.all_image_info[i + 1]
                except IndexError:
                    pass
                else:
                    # TODO: Configurable look-ahead / min duration?
                    if next_info.find_closest_bbox(allowed_sizes) == last:
                        log.debug(f'Ignoring single second difference between to matching boxes for {box=}')
                        continue

                if last_change:
                    last_change.duration = info.seconds - last_change.seconds

                last_change = RatioChange(info.seconds, box, self.common_box_ratio_map[box])
                changes.append(last_change)
                last = box

        final_info = self.all_image_info[-1]
        if last_change and last_change.seconds != final_info.seconds:
            last_change.duration = final_info.seconds - last_change.seconds

        return changes

    def get_size_boxes(self) -> dict[Box, int]:
        bboxes = _Counter(info.find_closest_bbox(self.common_ratios.values()) for info in self.all_image_info)
        boxes = {self.max_image_box: bboxes[self.max_image_box]}
        max_height = self.max_image_box.height
        sorted_bboxes = {
            b: c for b, c in sorted(bboxes.items(), key=lambda bc: bc[1], reverse=True) if b.height != max_height
        }
        for box, count in sorted_bboxes.items():
            if len(boxes) >= self.max_sizes:
                break
            boxes[box] = count
        return boxes

    @cached_property
    def max_image_box(self) -> Box:
        return max(info.box for info in self.all_image_info)

    @cached_property
    def common_ratios(self) -> dict[AspectRatio, Box]:
        log.debug(f'Using {self.max_image_box=}')
        return _get_common_ratios(self.max_image_box)


def _get_common_ratios(box: Box) -> dict[AspectRatio, Box]:
    common_ratios = {}
    for ar in COMMON_VIDEO_ASPECT_RATIOS:
        try:
            common_ratios[ar] = box.centered_crop_to_ratio(*ar)
        except ValueError as e:
            log.debug(e)
    return common_ratios


def _get_image_info(path: Path, threshold: float = 0.99) -> ImageInfo:
    return Image(path).get_info(threshold)


class Image:
    _pack_arrays = {
        1: array([1], dtype=uint32),
        2: array([1, 256], dtype=uint32),
        3: array([1, 256, 65536], dtype=uint32),
        4: array([1, 256, 65536, 16777216], dtype=uint32),  # 2 ** (0, 8, 16, 24)
    }

    def __init__(self, path: Path):
        self.path = path
        self.data = imread(path)
        # Note: imiter(self.path) can be used to iterate over individual frames as numpy arrays
        height, width, self.bands = self.data.shape
        self.box = Box.from_size_and_pos(width, height)

    def get_info(self, threshold: float = 0.99) -> ImageInfo:
        return ImageInfo(self.path, box=self.box, bbox=self.find_bbox(threshold), bands=self.bands)

    def find_bbox(self, threshold: float = 0.99) -> Box:
        return Box(0, self.find_top(threshold), self.box.right, self.find_bottom(threshold))

    def find_top(self, threshold: float = 0.99) -> int:
        return self._find_row(self.data, threshold)

    def find_bottom(self, threshold: float = 0.99) -> int:
        return self.box.bottom - self._find_row(self.data[::-1], threshold)

    def _find_row(self, image_data: NDArray, threshold: float = 0.99) -> int:
        pack_array = self._pack_arrays[image_data.shape[2]]
        row: NDArray
        for i, row in enumerate(image_data):
            # Pack each pixel's 3-4 RGB(A) 8-bit ints into a 32-bit int so that counting unique values counts full
            # colors instead of counting unique values for individual bands
            row = row.dot(pack_array)
            values, counts = unique(row, return_counts=True)
            if len(values) == 1:  # Only one unique value
                continue
            if (counts.max() / len(row)) < threshold:
                return i
        return 0


@dataclass
class ImageInfo:
    path: Path
    box: Box
    bbox: Box
    bands: int

    @cached_property
    def seconds(self) -> int:
        return int(self.path.stem.rsplit('_', 1)[-1]) - 1  # ffmpeg starts from 1

    def find_closest_bbox(self, boxes: Iterable[Box]) -> Box:
        return min(boxes, key=lambda box: abs(box.area - self.bbox.area))

    def __lt__(self, other: ImageInfo) -> bool:
        return self.seconds < other.seconds


@dataclass
class RatioChange:
    seconds: int
    box: Box
    ratio: AspectRatio
    duration: int = 0

    def __str__(self) -> str:
        box = self.box
        return (
            f't={self.seconds} ({self.time_stamp}), duration={self.duration} ({self.duration_str}),'
            f' pos={box.position}, size={box.width}x{box.height}'
        )

    @property
    def time_stamp(self) -> str:
        return format_duration(self.seconds)

    @property
    def duration_str(self) -> str:
        return format_duration(self.duration)

    @property
    def end_seconds(self) -> int:
        return self.seconds + self.duration

    @property
    def end_str(self) -> str:
        return format_duration(self.end_seconds)


if __name__ == '__main__':
    main()
