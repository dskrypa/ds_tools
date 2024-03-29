"""
Classes representing a Rubik's Cube

:author: Doug Skrypa
"""

import re
import logging
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from enum import Flag, auto, _decompose
from functools import cached_property, reduce
from operator import xor, or_
from random import Random
from typing import Optional, Union, Iterator, Collection, Iterable, Any

from ..output.color import colored

log = logging.getLogger(__name__)

Bool = Union[bool, Any]
Pos = tuple[int, int, int]
Faces = tuple['Color', 'Color', 'Color']
Seed = Union[int, float, str, bytes, None]
COLOR_TO_ANSI = {'white': 15, 'green': 10, 'red': 9, 'blue': 14, 'orange': 13, 'yellow': 11, 'none': None}
COLOR_TO_AXIS = {
    'white': ('z', 1), 'green': ('x', 1), 'red': ('y', -1), 'blue': ('x', -1), 'orange': ('y', 1), 'yellow': ('z', -1)
}
NODE_TYPES = ['core', 'center', 'edge', 'corner']

# region Colors


class Color(Flag):
    none = 0            # core
    white = auto()      # z
    green = auto()      # x
    red = auto()        # y
    blue = auto()       # x
    orange = auto()     # y
    yellow = auto()     # z

    @classmethod
    def _missing_(cls, value) -> 'Color':
        if isinstance(value, str) and value and value.isupper():
            try:
                letter_inst_map = cls._letter_inst_map
            except AttributeError:
                cls._letter_inst_map = letter_inst_map = {n[0].upper(): i for n, i in cls._member_map_.items()}

            if len(value) == 1:
                return letter_inst_map[value]
            else:
                return reduce(or_, (letter_inst_map[v] for v in value))
        else:
            return super()._missing_(value)

    def __str__(self) -> str:
        return colored(self.name, self.ansi)

    @cached_property
    def ansi(self) -> Optional[int]:
        return COLOR_TO_ANSI[self.name]

    @cached_property
    def letter(self) -> str:
        return self.name[0].upper()

    @cached_property
    def short(self) -> str:
        return colored(self.letter, self.ansi)

    @cached_property
    def parts(self) -> tuple['Color', ...]:
        members, uncovered = _decompose(self.__class__, self._value_)
        return tuple(members)

    @cached_property
    def non_none_parts(self) -> tuple['Color', ...]:
        return tuple(c for c in self.parts if c != Color.none)

    @cached_property
    def home_axis(self) -> Optional[str]:
        try:
            return COLOR_TO_AXIS[self.name][0]
        except KeyError:
            return None

    @cached_property
    def home_axis_value(self) -> Optional[int]:
        try:
            return COLOR_TO_AXIS[self.name][1]
        except KeyError:
            return None

    @cached_property
    def home_faces(self) -> Faces:
        x = y = z = Color.none
        for part in self.parts:
            if (axis := part.home_axis) == 'x':
                x = part
            elif axis == 'y':
                y = part
            elif axis == 'z':
                z = part
        return x, y, z

    @cached_property
    def home_pos(self) -> Optional[Pos]:
        return HOMES.get(self)


N = Color.none
W = Color.white
G = Color.green
R = Color.red
B = Color.blue
O = Color.orange
Y = Color.yellow

HOMES: dict[Color, Pos] = {
    B | R | W: (-1, -1, 1),
    R | W: (0, -1, 1),
    G | R | W: (1, -1, 1),
    B | W: (-1, 0, 1),
    W: (0, 0, 1),
    G | W: (1, 0, 1),
    B | O | W: (-1, 1, 1),
    O | W: (0, 1, 1),
    G | O | W: (1, 1, 1),
    B | R: (-1, -1, 0),
    R: (0, -1, 0),
    G | R: (1, -1, 0),
    B: (-1, 0, 0),
    N: (0, 0, 0),
    G: (1, 0, 0),
    B | O: (-1, 1, 0),
    O: (0, 1, 0),
    G | O: (1, 1, 0),
    B | R | Y: (-1, -1, -1),
    R | Y: (0, -1, -1),
    G | R | Y: (1, -1, -1),
    B | Y: (-1, 0, -1),
    Y: (0, 0, -1),
    G | Y: (1, 0, -1),
    B | O | Y: (-1, 1, -1),
    O | Y: (0, 1, -1),
    G | O | Y: (1, 1, -1),
}

# endregion


class Node:
    __slots__ = ('cube', 'pos', 'faces', 'color', 'home')

    def __init__(self, cube: 'Cube', pos: Pos, faces: Faces):
        self.cube = cube
        self.pos = pos
        self.faces = faces
        self.color = color = reduce(or_, faces)
        self.home = HOMES[color]

    @property
    def type(self) -> str:
        return NODE_TYPES[len(self.color.non_none_parts)]

    def __repr__(self) -> str:
        fx, fy, fz = self.faces
        home = '\u25cb' if self.is_home() else '\u2715'
        return f'<Node[{home}][{self.type} @ {self.pos}, x={fx}, y={fy}, z={fz}]>'

    def __eq__(self, other: 'Node') -> bool:
        return self.pos == other.pos and self.faces == other.faces

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.pos) ^ hash(self.faces)

    def copy(self) -> 'Node':
        cls = self.__class__
        clone = cls.__new__(cls)
        clone.cube = self.cube
        clone.pos = self.pos
        clone.faces = self.faces
        clone.color = self.color
        clone.home = self.home
        return clone

    def sq_str_parts(self):
        x, y, z = self.pos
        fx, fy, fz = self.faces
        filler = '   '
        y_str = f' {fy.short} ' if fy else filler
        a, c = ((fx.short, ' ') if x == -1 else (' ', fx.short)) if fx else (' ', ' ')
        xz_str = '{}{}{}'.format(a, fz.short if fz else ' ', c)
        return (y_str, xz_str, filler) if y == -1 else (filler, xz_str, y_str)

    # region Position Methods

    def is_home(self) -> bool:
        return self.pos == self.home and all(axis == (f.home_axis or axis) for f, axis in zip(self.faces, 'xyz'))

    @property
    def x(self) -> int:
        return self.pos[0]

    @property
    def y(self) -> int:
        return self.pos[1]

    @property
    def z(self) -> int:
        return self.pos[2]

    # endregion

    # region Rotation Methods

    def rotate_x(self, clockwise: Bool):
        x, y, z = self.pos
        self.pos = (x, z, -y) if clockwise else (x, -z, y)
        fx, fy, fz = self.faces
        self.faces = (fx, fz, fy)

    def rotate_y(self, clockwise: Bool):
        x, y, z = self.pos
        self.pos = (z, y, -x) if clockwise else (-z, y, x)
        fx, fy, fz = self.faces
        self.faces = (fz, fy, fx)

    def rotate_z(self, clockwise: Bool):
        x, y, z = self.pos
        self.pos = (-y, x, z) if clockwise else (y, -x, z)
        fx, fy, fz = self.faces
        self.faces = (fy, fx, fz)

    def rotate(self, axis: str, clockwise: Bool):
        self._axis_to_rotate_method[axis](self, clockwise)

    _axis_to_rotate_method = {'x': rotate_x, 'y': rotate_y, 'z': rotate_z}

    def maybe_rotate(self, axis: str, clockwise: Bool, plane: int):
        if getattr(self, axis) == plane:
            self.rotate(axis, clockwise)

    def rotate_cube(self, axis: str, clockwise: Bool):
        plane = getattr(self, axis)
        self.cube.rotate(axis, plane, clockwise)

    def solve(self, seed: Seed = None):
        randbelow = Random(seed)._randbelow  # noqa
        axes = ('x', 'y', 'z')
        while not self.is_home():
            self.rotate_cube(axes[randbelow(3)], randbelow(2))

    # endregion


class Cube:
    def __init__(self, pos_faces_iter: Iterable[tuple[Pos, Union[Faces, Color]]] = None):
        if pos_faces_iter is None:
            pos_faces_iter = ((pos, col.home_faces) for col, pos in HOMES.items())
        self.nodes = tuple(Node(self, pos, faces) for pos, faces in pos_faces_iter)
        self._init_pct = self.percent_solved()
        self._pos_node_map = None
        self.history = []

    @classmethod
    def from_colors(cls, colors: Union[str, Iterable[Union[str, Color, Collection[Color]]]]):
        if isinstance(colors, str):
            colors = re.split(r'[\s,;]+', colors)

        coord_iter = ((x, y, z) for z in (-1, 0, 1) for y in (-1, 0, 1) for x in (-1, 0, 1))
        groups = []
        for color in colors:
            if isinstance(color, str):
                color = tuple(Color(c) for c in color.strip().upper())
            elif isinstance(color, Color):
                color = (color,)
            if any(c not in Color for c in color):
                raise ValueError(f'Invalid {color=} - must be one of the primary 6 colors or Color.none')
            groups.append(color)

        return cls(zip(coord_iter, groups))

    @classmethod
    def from_random(cls, steps: int = 30, seed: Seed = None):
        self = cls()
        self.randomize(steps, seed)
        self._init_pct = self.percent_solved()
        self.history = []
        return self

    # region Internal Methods

    @cached_property
    def _color_node_map(self) -> dict[Color, Node]:
        return {node.color: node for node in self.nodes}

    @property
    def pos_node_map(self) -> dict[Pos, Node]:
        if self._pos_node_map is None:
            self._pos_node_map = {node.pos: node for node in self.nodes}
        return self._pos_node_map

    def __getitem__(self, pos_or_color: Union[Pos, Color, str]) -> Node:
        if isinstance(pos_or_color, str):
            pos_or_color = Color(pos_or_color)
        if isinstance(pos_or_color, Color):
            return self._color_node_map[pos_or_color]
        return self.pos_node_map[pos_or_color]

    def __repr__(self) -> str:
        moves = len(self.history)
        lines = [f'<Cube[{moves=}, solved={self.percent_solved():.2%}, nodes=[']
        pos_node_map = self.pos_node_map
        for z in (-1, 0, 1):
            if z != -1:
                lines.append('')
            for y in (-1, 0, 1):
                if y != -1:
                    lines.append('')
                for x in (-1, 0, 1):
                    lines.append(f'    {pos_node_map[(x, y, z)]},')
        lines.append(']>')
        return '\n'.join(lines)

    def __eq__(self, other: 'Cube') -> bool:
        return self.nodes == other.nodes

    def __hash__(self) -> int:
        return hash(self.__class__) ^ reduce(xor, map(hash, self.nodes))

    def copy(self) -> 'Cube':
        cls = self.__class__
        clone = cls.__new__(cls)
        clone.nodes = tuple(map(Node.copy, self.nodes))
        clone._init_pct = self._init_pct
        clone._pos_node_map = None
        history = self.history
        clone.history = history.copy() if history else []
        return clone

    # endregion

    def solved(self) -> bool:
        return all(map(Node.is_home, self.nodes))

    def percent_solved(self) -> float:
        return sum(map(Node.is_home, self.nodes)) / 27

    # region Rotation Methods

    def rotate(self, axis: str, plane: int, clockwise: Bool = True) -> float:
        return self._axis_to_rotate_method[axis](self, plane, clockwise)

    def _record_rotation(self, axis: str, plane: int, clockwise: Bool) -> float:
        self._node_dict = None
        pct_solved = self.percent_solved()
        self.history.append((axis, plane, clockwise, pct_solved))
        return pct_solved

    def rotate_x(self, x_plane: int, clockwise: Bool = True) -> float:
        """Rotate around the x axis"""
        for node in self.nodes:
            # if node.x == x_plane:
            if node.pos[0] == x_plane:
                node.rotate_x(clockwise)
        return self._record_rotation('x', x_plane, clockwise)

    def rotate_y(self, y_plane: int, clockwise: Bool = True) -> float:
        """Rotate around the y axis"""
        for node in self.nodes:
            # if node.y == y_plane:
            if node.pos[1] == y_plane:
                node.rotate_y(clockwise)
        return self._record_rotation('y', y_plane, clockwise)

    def rotate_z(self, z_plane: int, clockwise: Bool = True) -> float:
        """Rotate around the z axis"""
        for node in self.nodes:
            # if node.z == z_plane:
            if node.pos[2] == z_plane:
                node.rotate_z(clockwise)
        return self._record_rotation('z', z_plane, clockwise)

    _axis_to_rotate_method = {'x': rotate_x, 'y': rotate_y, 'z': rotate_z}

    # endregion

    def randomize(self, steps: int, seed: Seed = None):
        randbelow = Random(seed)._randbelow  # noqa
        # axes[randbelow(3)] == choice(axes); randbelow(2) == randint(0, 1); randbelow(3) - 1 == randrange(-1, 2)
        axes = ('x', 'y', 'z')
        axis_to_rotate_method = self._axis_to_rotate_method
        for _ in range(steps):
            axis_to_rotate_method[axes[randbelow(3)]](self, randbelow(3) - 1, randbelow(2))
            # self.rotate(axes[randbelow(3)], randbelow(3) - 1, randbelow(2))

    def format_history(self) -> Iterator[str]:
        last_pct = self._init_pct
        for axis, plane, clockwise, pct_solved in self.history:
            cw_str = 'CW' if clockwise else 'CCW'
            yield f'Rotate {axis}={plane} {cw_str} around {axis=!s} [solved: {last_pct:.2%} \u001a {pct_solved:.2%}]'
            last_pct = pct_solved

    def print_history(self):
        for line in self.format_history():
            print(line)

    def pprint(self, compact: bool = True):
        rows = [
            [], [],
            [], [],  # no
            [],
            [], [],  # no
            [], []
        ]
        row_groups = {-1: rows[:3], 0: rows[3:6], 1: rows[6:]}
        nodes = {node.pos: node for node in self.nodes}  # type: dict[Pos, Node]
        for z in (-1, 0, 1):
            for row in rows:
                row.append('   ')

            for y in (-1, 0, 1):
                group = row_groups[y]
                for x in (-1, 0, 1):
                    for row, line in zip(group, nodes[(x, y, z)].sq_str_parts()):
                        row.append(line)

        for i, row in enumerate(rows):
            if not compact or i not in {2, 3, 5, 6}:
                print(''.join(row))

    def find_random_solution(self, max_moves: int = 80, max_attempts: int = 1_000_000, workers: int = 14):
        # w_attempts = max_attempts // workers
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = (
                executor.submit(self.copy()._find_random_solution, max_moves, max_attempts, use_print=True)
                for _ in range(workers)
            )
            for i, future in enumerate(as_completed(futures)):
                try:
                    solved = future.result()
                except NoSolutionFound:
                    log.info(f'No solution found in process={i}')
                else:
                    log.info('Found solution:')
                    solved.print_history()
                    executor.shutdown(False, cancel_futures=True)
                    return solved

        raise NoSolutionFound(f'No random solution was found with {max_moves=} in {max_attempts=} with {workers=}')

    def _find_random_solution(
        self, max_moves: int = 80, max_attempts: int = 1_000_000, seed: Seed = None, use_print: bool = False
    ) -> 'Cube':
        cube = self.copy()
        copy_node = Node.copy
        orig_nodes = tuple(map(copy_node, cube.nodes))
        # make_copy = self.copy
        axes = ('x', 'y', 'z')
        getrandbits = Random(seed).getrandbits  # See Cube.randomize() for additional notes

        def rand_2_or_3(n: int) -> int:  # Equivalent to random._randbelow for n=2..3; used by both choice & randrange
            r = getrandbits(2)
            while r >= n:
                r = getrandbits(2)
            return r

        report_func = print if use_print else log.info
        axis_to_rotate_method = cube._axis_to_rotate_method
        report_interval = _report_interval(max_attempts)
        for attempt in range(1, max_attempts + 1):
            if attempt % report_interval == 0:
                report_func(f'Beginning random solution {attempt=:,d}')
            # cube = make_copy()
            cube.nodes = tuple(map(copy_node, orig_nodes))
            cube.history = []

            for _ in range(max_moves):
                # solved_pct = cube.rotate(axes[rand_2_or_3(3)], rand_2_or_3(3) - 1, rand_2_or_3(2))
                solved_pct = axis_to_rotate_method[axes[rand_2_or_3(3)]](cube, rand_2_or_3(3) - 1, rand_2_or_3(2))
                # cube.rotate(axes[rand_2_or_3(3)], rand_2_or_3(3) - 1, True)
                if solved_pct == 1:
                # if cube.solved():
                    report_func(f'Found random solution with moves={len(cube.history)} on {attempt=}')
                    cube.print_history()
                    return cube

        raise NoSolutionFound(f'No random solution was found with {max_moves=} in {max_attempts=}')

    def find_semi_random_solution(self, seed: Seed = None):
        cube = self.copy()
        while not cube.solved():
            node = next(n for n in cube.nodes if not n.is_home())
            node.solve(seed)
        return cube

    def find_semi_random_solution_2(self, seed: Seed = None):
        cube = self.copy()
        while not cube.solved():
            unsolved_colors = tuple(n.color for n in cube.nodes if not n.is_home())
            copies = [cube.copy() for color in unsolved_colors]
            for color, _cube in zip(unsolved_colors, copies):
                _cube[color].solve(seed)

            cube = max(copies, key=lambda c: c.percent_solved() / len(c.history))
            # cube = min(copies, key=lambda c: len(c.history))

        return cube

    # def find_solution(self, max_moves: int = 20) -> 'Cube':
    #     """
    #     :param max_moves: Max moves to allow for a solution (20 was apparently proven to be the max necessary)
    #     :return:
    #     """
    #     axes = ('x', 'y', 'z')
    #     planes = (-1, 0, 1)
    #     bools = (True, False)
    #     visited = set()
    #     original = self.copy()
    #     active = self.copy()
    #     for axis in axes:
    #         for clockwise in bools:
    #             for plane in planes:
    #                 active.rotate(axis, plane, clockwise)
    #                 if active.solved():
    #                     return active
    #                 # else:


def _report_interval(attempts: int) -> int:
    return 100_000 if attempts >= 1_000_000 else round(attempts, -int(math.log(attempts, 10))) / 10


class NoSolutionFound(Exception):
    pass
