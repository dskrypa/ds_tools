#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from datetime import datetime

from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging
from ds_tools.misc.nier.save_file import GameData

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Nier Replicant ver.1.22474487139... Save File Editor')

    garden = parser.add_subparser('action', 'garden', 'Examine or modify the garden')
    garden_view = garden.add_subparser('sub_action', 'view', 'View the current garden state')
    garden_time = garden.add_subparser('sub_action', 'time', 'Change the plant time for all plots')
    gt_group = garden_time.add_mutually_exclusive_group()
    gt_group.add_argument('--time', '-t', metavar='YYYY-MM-DD HH:MM:SS', type=datetime.fromisoformat, help='A specific time to set as the plant time')
    gt_group.add_argument('--hours', '-H', type=int, help='Set the plant time to be the given number of hours earlier than now')

    parser.add_common_sp_arg('--path', '-p', help='Save file path')
    parser.add_common_sp_arg('--slot', '-s', type=int, choices=(1, 2, 3), help='Save slot to load/modify')
    parser.include_common_args('verbosity')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    path = get_path(args.path)
    log.debug(f'Loading data from path={path.as_posix()}')
    game_data = GameData.load(path)
    slots = game_data.slots if args.slot is None else [game_data.slots[args.slot]]
    action, sub_action = args.action, args.sub_action
    if action == 'garden':
        if sub_action == 'view':
            prefix = '    ' if len(slots) > 1 else ''
            for i, slot in enumerate(slots):
                if i:
                    print()
                if prefix:
                    log.info(f'{slot}:', extra={'color': 14})
                slot.show_garden(prefix=prefix)
        elif sub_action == 'time':
            if len(slots) > 1:
                raise ValueError('--slot is required for setting garden plant times')
            slots[0].set_plant_times(args.time, args.hours)
            log.info('Updated plant times:')
            slots[0].show_garden()
            game_data.save(path)
        else:
            raise ValueError(f'Unexpected {sub_action=}')
    else:
        raise ValueError(f'Unexpected {action=}')


def get_path(path):
    if path:
        path = Path(path).expanduser()
    else:
        steam_dir = Path('~/Documents/My Games/NieR Replicant ver.1.22474487139/Steam/').expanduser()
        if not steam_dir.exists():
            raise PathRequired(f'steam_dir={steam_dir.as_posix()} does not exist')
        steam_dirs = list(steam_dir.iterdir())
        if len(steam_dirs) != 1:
            raise PathRequired(f'a single directory under steam_dir={steam_dir.as_posix()} does not exist')
        path = steam_dirs[0].joinpath('GAMEDATA')
    if not path.exists():
        raise PathRequired(f'path={path.as_posix()} does not exist')
    return path


class PathRequired(Exception):
    def __init__(self, reason: str):
        self.reason = reason

    def __str__(self):
        return f'--path is required because {self.reason}'


if __name__ == '__main__':
    main()
