from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
from multiprocessing import Process, Queue, Event
from os import stat, cpu_count, getpid
from pathlib import Path
from queue import Empty as QueueEmpty
from traceback import format_exception
from typing import Any, Collection, Iterator, Type

from PIL import UnidentifiedImageError
from tqdm import tqdm

from ds_tools.logging import init_logging as _init_logging, ENTRY_FMT_DETAILED_PID
from .multi import MultiHash, MULTI_MODES, get_multi_class
from .single import ImageHashBase, HASH_MODES, get_hash_class

__all__ = [
    'ImageProcessor', 'process_image', 'process_images',
    'process_images_mp', 'process_images_via_executor', 'process_images_st',
]
log = logging.getLogger(__name__)

ProcessedResults = tuple[tuple[bytes, ...], str, int, float]


class ImageProcessor:
    __slots__ = ('workers', 'hash_mode', 'multi_mode', 'use_executor', 'init_logging', 'verbosity')

    def __init__(
        self,
        workers: int | None = None,
        hash_mode: str = 'difference',
        multi_mode: str = 'rotated',
        *,
        use_executor: bool = False,
        init_logging: bool = True,
        verbosity: int | None = 1,
    ):
        self.workers = workers
        self.hash_mode = hash_mode
        self.multi_mode = multi_mode
        self.use_executor = use_executor
        self.init_logging = init_logging
        self.verbosity = verbosity

    def process_images(self, paths: Collection[Path]) -> Iterator[tuple[int, Path, ProcessedResults]]:
        kwargs: dict[str, Any] = {'hash_mode': self.hash_mode, 'multi_mode': self.multi_mode}
        if self.workers is None or self.workers > 1:
            # Even after optimizing away some of the serialization/deserialization overhead, after a certain point, a
            # CPU usage pattern emerges where there are periods of high/efficient CPU use followed by long periods of
            # relative inactivity.
            # The root cause is that it takes significantly longer to deserialize all results / insert them in the DB
            # than it takes to process all of them.  This can be observed by having worker processes print when they
            # finish, yet observing via the progress bar that thousands of results are still pending processing.
            kwargs['workers'] = self.workers
            if self.use_executor:
                process_images_func = process_images_via_executor
            else:
                process_images_func = process_images_mp
                kwargs['init_logging'] = self.init_logging
                kwargs['verbosity'] = self.verbosity
        else:
            process_images_func = process_images

        return process_images_func(paths, **kwargs)


def process_images(
    paths: Collection[Path],
    workers: int | None = None,
    hash_mode: str = 'difference',
    multi_mode: str = 'rotated',
    *,
    use_executor: bool = False,
    init_logging: bool = True,
    verbosity: int | None = 1,
) -> Iterator[tuple[int, Path, ProcessedResults]]:
    processor = ImageProcessor(
        workers, hash_mode, multi_mode, use_executor=use_executor, init_logging=init_logging, verbosity=verbosity
    )
    return processor.process_images(paths)


def process_images_mp(
    paths: Collection[Path],
    workers: int | None = None,
    *,
    hash_mode: str = 'difference',
    multi_mode: str = 'rotated',
    init_logging: bool = True,
    verbosity: int | None = 1,
) -> Iterator[tuple[int, Path, ProcessedResults]]:
    get_hash_class(hash_mode)  # These are called here just to validate the input before spawning processes
    get_multi_class(multi_mode)

    in_queue, out_queue, shutdown, done_feeding = args = Queue(), Queue(), Event(), Event()
    kwargs = {
        'hash_mode': hash_mode, 'multi_mode': multi_mode, 'init_logging': init_logging, 'verbosity': verbosity
    }
    processes = [Process(target=_image_processor, args=args, kwargs=kwargs) for _ in range(workers or cpu_count() or 1)]
    for proc in processes:
        proc.start()

    with tqdm(range(1, len(paths) + 1), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
        for path in paths:
            # Note: `Path(loads(dumps(path.as_posix())))` is >2x faster than `loads(dumps(path))` with pickle
            in_queue.put(path.as_posix())
        done_feeding.set()
        try:
            for finished in prog_bar:
                path, result = out_queue.get()
                if isinstance(result, BaseException):
                    try:
                        raise result  # This sets exc_info
                    except Exception as e:
                        exc_info = not isinstance(e, UnidentifiedImageError)
                        log.error(f'Error hashing {path}: {e}', exc_info=exc_info, extra={'color': 'red'})
                else:
                    yield finished, Path(path), result
        except BaseException:
            shutdown.set()
            raise

    for proc in processes:
        proc.join()


def process_images_via_executor(
    paths: Collection[Path], workers: int | None = None, *, hash_mode: str = 'difference', multi_mode: str = 'rotated'
) -> Iterator[tuple[int, Path, ProcessedResults]]:
    hash_cls = HASH_MODES[hash_mode]  # Since this occurs in the main process for this approach,
    multi_cls = MULTI_MODES[multi_mode]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        with tqdm(total=len(paths), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
            # Note: `Path(loads(dumps(path.as_posix())))` is >2x faster than `loads(dumps(path))` with pickle
            futures = {executor.submit(process_image, path.as_posix(), hash_cls, multi_cls): path for path in paths}
            # When accepting `Iterable[Path]` instead of `Collection[Path]`, because workers immediately start
            # processing the futures, if the number of paths is high, it is very likely that the total count (of
            # futures) will not be identified / the progress bar will not be displayed before a potentially
            # significant number of files have already been processed.
            try:
                for i, future in enumerate(as_completed(futures), 1):
                    path = Path(futures[future])
                    prog_bar.update(1)
                    try:
                        result = future.result()
                    except Exception as e:
                        exc_info = not isinstance(e, UnidentifiedImageError)
                        log.error(f'Error hashing {path}: {e}', exc_info=exc_info, extra={'color': 'red'})
                    else:
                        yield i, path, result
            except BaseException:
                executor.shutdown(cancel_futures=True)
                raise


def process_images_st(
    paths: Collection[Path], *, hash_mode: str = 'difference', multi_mode: str = 'rotated'
) -> Iterator[tuple[int, Path, ProcessedResults]]:
    hash_cls = HASH_MODES[hash_mode]  # Since this occurs in the main process for this approach,
    multi_cls = MULTI_MODES[multi_mode]

    with tqdm(total=len(paths), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
        for i, path in enumerate(paths, 1):
            prog_bar.update(1)
            try:
                result = process_image(path, hash_cls, multi_cls)
            except Exception as e:
                exc_info = not isinstance(e, UnidentifiedImageError)
                log.error(f'Error hashing {path}: {e}', exc_info=exc_info, extra={'color': 'red'})
            else:
                yield i, path, result


def process_image(path: str | Path, hash_cls: Type[ImageHashBase], multi_cls: Type[MultiHash]) -> ProcessedResults:
    stat_info = stat(path, follow_symlinks=True)
    with open(path, 'rb') as f:
        data = f.read()

    sha256sum = sha256(data).hexdigest()
    hashes = multi_cls.from_file(BytesIO(data), hash_cls=hash_cls).hashes
    arrays = tuple(h.array.tobytes() for h in hashes)
    # This approach results in the least overhead for deserializing this data in the main process
    return arrays, sha256sum, stat_info.st_size, stat_info.st_mtime


def _image_processor(
    in_queue: Queue,
    out_queue: Queue,
    shutdown: Event,
    done_feeding: Event,
    *,
    hash_mode: str = 'difference',
    multi_mode: str = 'rotated',
    init_logging: bool = True,
    verbosity: int | None = 1,
):
    if init_logging:
        _init_logging(verbosity, log_path=None, entry_fmt=ENTRY_FMT_DETAILED_PID)

    hash_cls = HASH_MODES[hash_mode]  # Note: Key membership is verified in process_images before this is called
    multi_cls = MULTI_MODES[multi_mode]
    log.debug(f'Worker process starting with hash_cls={hash_cls.__name__}, multi_cls={multi_cls.__name__}')

    while not shutdown.is_set():
        try:
            path = in_queue.get(timeout=0.1)
        except QueueEmpty:  # Prevent blocking shutdown if the queue is still being filled
            if done_feeding.is_set():
                break
            else:
                continue

        try:
            out_queue.put((path, process_image(path, hash_cls, multi_cls)))
        except BaseException as e:  # noqa
            out_queue.put((path, _ExceptionWrapper(e, e.__traceback__)))

    log.log(19, f'Worker process finished: {getpid()}')


class _ExceptionWrapper:
    """Based on `concurrent.futures.process._ExceptionWithTraceback`"""

    def __init__(self, exc: BaseException, tb):
        tb = ''.join(format_exception(type(exc), exc, tb))
        self.exc = exc
        self.exc.__traceback__ = None
        self.tb = f'\n"""\n{tb}"""'

    def __reduce__(self):
        return _rebuild_exc, (self.exc, self.tb)


def _rebuild_exc(exc: BaseException, tb):
    exc.__cause__ = _RemoteException(tb)
    return exc


class _RemoteException(Exception):
    def __init__(self, tb: str):
        self.tb = tb

    def __str__(self) -> str:
        return self.tb
