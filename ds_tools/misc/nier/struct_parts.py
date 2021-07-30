"""
Slightly modified versions of https://github.com/Acurisu/NieR-Replicant-ver.1.22474487139/blob/main/Editor/src/Nier.ts
+ code used to translate them into the content in structs.
"""

import logging
import re
from typing import Union

log = logging.getLogger(__name__)


Recovery = {
    "Medicinal Herb": "uint8",
    "Health Salve": "uint8",
    "Recovery Potion": "uint8",
    "unk": ["skip", 18],
    "Strength Drop": "uint8",
    "Strength Capsule": "uint8",
    "Magic Drop": "uint8",
    "Magic Capsule": "uint8",
    "Defense Drop": "uint8",
    "Defense Capsule": "uint8",
    "Spirit Drop": "uint8",
    "Spirit Capsule": "uint8",
    "unk1": ["skip", 2],
    "Antidotal Weed": "uint8",
    "unk2": ["skip", 1],
    "Smelling Salts": "uint8",
}

Cultivation = {
    "Speed Fertilizer": "uint8",
    "Flowering Fertilizer": "uint8",
    "Bounty Fertilizer": "uint8",
    "unk": ["skip", 2],
    "Pumpkin Seed": "uint8",
    "Watermelon Seed": "uint8",
    "Melon Seed": "uint8",
    "Gourd Seed": "uint8",
    "Tomato Seed": "uint8",
    "Eggplant Seed": "uint8",
    "Bell Pepper Seed": "uint8",
    "Bean Seed": "uint8",
    "Wheat Seedling": "uint8",
    "Rice Plant Seedling": "uint8",
    "Dahlia Bulb": "uint8",
    "Tulip Bulb": "uint8",
    "Freesia Bulb": "uint8",
    "Red Moonflower Seed": "uint8",
    "Gold Moonflower Seed": "uint8",
    "Peach Moonflower Seed": "uint8",
    "Pink Moonflower Seed": "uint8",
    "Blue Moonflower Seed": "uint8",
    "Indigo Moonflower Seed": "uint8",
    "White Moonflower Seed": "uint8",
    "unk1": ["skip", 5],
    "Pumpkin": "uint8",
    "Watermelon": "uint8",
    "Melon": "uint8",
    "Gourd": "uint8",
    "Tomato": "uint8",
    "Eggplant": "uint8",
    "Bell Pepper": "uint8",
    "Beans": "uint8",
    "Wheat": "uint8",
    "Rice": "uint8",
    "Dahlia": "uint8",
    "Tulip": "uint8",
    "Freesia": "uint8",
    "Red Moonflower": "uint8",
    "Gold Moonflower": "uint8",
    "Peach Moonflower": "uint8",
    "Pink Moonflower": "uint8",
    "Blue Moonflower": "uint8",
    "Indigo Moonflower": "uint8",
    "White Moonflower": "uint8",
}

Fishing = {
    "Lugworm": "uint8",
    "Earthworm": "uint8",
    "Lure": "uint8",
    "unk": ["skip", 7],
    "Sardine": "uint8",
    "Carp": "uint8",
    "Blowfish": "uint8",
    "Bream": "uint8",
    "Shark": "uint8",
    "Blue Marlin": "uint8",
    "Dunkleosteus": "uint8",
    "Rainbow Trout": "uint8",
    "Black Bass": "uint8",
    "Giant Catfish": "uint8",
    "Royal Fish": "uint8",
    "Hyneria": "uint8",
    "Sandfish": "uint8",
    "Rhizodont": "uint8",
    "Shaman Fish": "uint8",
}

RawMaterials = {
    "Aquatic Plant": "uint8",
    "Deadwood": "uint8",
    "Rusty Bucket": "uint8",
    "Empty Can": "uint8",
    "unk": ["skip", 3],
    "Gold Ore": "uint8",
    "Silver Ore": "uint8",
    "Copper Ore": "uint8",
    "Iron Ore": "uint8",
    "Crystal": "uint8",
    "Pyrite": "uint8",
    "Moldavite": "uint8",
    "Meteorite": "uint8",
    "Amber": "uint8",
    "Fluorite": "uint8",
    "Clay": "uint8",
    "unk1": ["skip", 4],
    "Berries": "uint8",
    "Royal Fern": "uint8",
    "Tree Branch": "uint8",
    "Log": "uint8",
    "Natural Rubber": "uint8",
    "Ivy": "uint8",
    "Lichen": "uint8",
    "Mushroom": "uint8",
    "Sap": "uint8",
    "unk2": ["skip", 5],
    "Mutton": "uint8",
    "Boar Meat": "uint8",
    "Wool": "uint8",
    "Boar Hide": "uint8",
    "Wolf Hide": "uint8",
    "Wolf Fang": "uint8",
    "Giant Spider Silk": "uint8",
    "Bat Fang": "uint8",
    "Bat Wing": "uint8",
    "Goat Meat": "uint8",
    "Goat Hide": "uint8",
    "Venison": "uint8",
    "Rainbow Spider Silk": "uint8",
    "Boar Liver": "uint8",
    "Scorpion Claw": "uint8",
    "Scorpion Tail": "uint8",
    "Dented Metal Board": "uint8",
    "Stripped Bolt": "uint8",
    "Broken Lens": "uint8",
    "Severed Cable": "uint8",
    "Broken Arm": "uint8",
    "Broken Antenna": "uint8",
    "Broken Motor": "uint8",
    "Broken Battery": "uint8",
    "Mysterious Switch": "uint8",
    "Large Gear": "uint8",
    "Titanium Alloy": "uint8",
    "Memory Alloy": "uint8",
    "Rusted Clump": "uint8",
    "Machine Oil": "uint8",
    "unk3": ["skip", 4],
    "Forlorn Necklace": "uint8",
    "Twisted Ring": "uint8",
    "Broken Earring": "uint8",
    "Pretty Choker": "uint8",
    "Metal Piercing": "uint8",
    "Subdued Bracelet": "uint8",
    "Technical Guide": "uint8",
    "Grubby Book": "uint8",
    "Thick Dictionary": "uint8",
    "Closed Book": "uint8",
    "Used Coloring Book": "uint8",
    "Old Schoolbook": "uint8",
    "Dirty Bag": "uint8",
    "Flashy Hat": "uint8",
    "Leather Gloves": "uint8",
    "Silk Handkerchief": "uint8",
    "Leather Boots": "uint8",
    "Complex Machine": "uint8",
    "Elaborate Machine": "uint8",
    "Simple Machine": "uint8",
    "Stopped Clock": "uint8",
    "Broken Wristwatch": "uint8",
    "Rusty Kitchen Knife": "uint8",
    "Broken Saw": "uint8",
    "Dented Metal Bat": "uint8",
    "unk4": ["skip", 1],
    "Shell": "uint8",
    "Gastropod": "uint8",
    "Bivalve": "uint8",
    "Seaweed": "uint8",
    "Empty Bottle": "uint8",
    "Driftwood": "uint8",
    "Pearl": "uint8",
    "Black Pearl": "uint8",
    "Crab": "uint8",
    "Starfish": "uint8",
    "unk5": ["skip", 5],
    "Sea Turtle Egg": "uint8",
    "Broken Pottery": "uint8",
    "Desert Rose": "uint8",
    "Giant Egg": "uint8",
    "Damascus Steel": "uint8",
    "Eagle Egg": "uint8",
    "Chicken Egg": "uint8",
    "unk6": ["skip", 1],
    "Mouse Tail": "uint8",
    "Lizard Tail": "uint8",
    "unk7": ["skip", 3],
    "Deer Antler": "uint8",
}

KeyItems = {
    "Moon Key": "uint8",
    "Star Key": "uint8",
    "Light Key": "uint8",
    "Darkness Key": "uint8",
    "Fine Flour": "uint8",
    "Coarse Flour": "uint8",
    "Perfume Bottle": "uint8",
    "Postman's Parcel": "uint8",
    "Lover's Letter": "uint8",
    "Water Filter": "uint8",
    "Royal Compass": "uint8",
    "Vapor Moss": "uint8",
    "Valley Spider Silk": "uint8",
    "Animal Guidebook": "uint8",
    "Ore Guidebook": "uint8",
    "Plant Guidebook": "uint8",
    "Red Book": "uint8",
    "Blue Book": "uint8",
    "Old Lady's Elixir": "uint8",
    "Old Lady's Elixir+": "uint8",
    "Parcel for The Aerie": "uint8",
    "Parcel for Seafront": "uint8",
    "Cookbook": "uint8",
    "Parcel for Facade": "uint8",
    "Max's Herbs": "uint8",
    "Drifting Cargo": "uint8",
    "Drifting Cargo 2": "uint8",
    "Drifting Cargo 3": "uint8",
    "Drifting Cargo 4": "uint8",
    "Old Package": "uint8",
    "Mermaid Tear": "uint8",
    "Mandrake Leaf": "uint8",
    "Energizer": "uint8",
    "Toad Oil": "uint8",
    "Sleep-B-Gone": "uint8",
    "Antidote": "uint8",
    "Gold Bracelet": "uint8",
    "Elite Kitchen Knife": "uint8",
    "Elevator Parts": "uint8",
    "Dirty Treasure Map": "uint8",
    "Restored Treasure Map": "uint8",
    "Jade Hair Ornament": "uint8",
    "Employee List": "uint8",
    "Small Safe": "uint8",
    "Safe Key": "uint8",
    "Great Tree Root": "uint8",
    "Eye of Power": "uint8",
    "Ribbon": "uint8",
    "Yonah's Ribbon": "uint8",
    "Bronze Key": "uint8",
    "Brass Key": "uint8",
    "Boar Tusk": "uint8",
    "Pressed Freesia": "uint8",
    "Potted Freesia": "uint8",
    "Freesia (Delivery)": "uint8",
    "Pile of Junk": "uint8",
    "Old Gold Coin": "uint8",
    "Marked Map": "uint8",
    "AA Keycard": "uint8",
    "KA Keycard": "uint8",
    "SA Keycard": "uint8",
    "TA Keycard": "uint8",
    "NA Keycard": "uint8",
    "HA Keycard": "uint8",
    "MA Keycard": "uint8",
    "YA Keycard": "uint8",
    "RA Keycard": "uint8",
    "WA Keycard": "uint8",
    "Cultivator's Handbook": "uint8",
    "Red Bag": "uint8",
    "Lantern": "uint8",
    "Empty Lantern": "uint8",
    "Hold Key": "uint8",
    "Passageway Key": "uint8",
    "Goat Key": "uint8",
    "Lizard Key": "uint8",
    "Unlocking Procedure Memo": "uint8",
    "Red Jewel?": "uint8",
    "Red Flowers": "uint8",
    "Apples": "uint8",
}

Documents = {
    "Look at the Sky": "uint8",
    "Don't try so hard": "uint8",
    "My Birthday!": "uint8",
    "Love Letter 2/12/3340": "uint8",
    "Love Letter 3/28/3340": "uint8",
    "Love Letter 5/1/3340": "uint8",
    "Letter from the Mayor": "uint8",
    "The Postman's Request": "uint8",
    "The Postman's Thanks": "uint8",
    "Invitation from a Stranger": "uint8",
    "Grand Re-Opening Notice": "uint8",
    "Wedding Invitation": "uint8",
    "Letter from the King": "uint8",
    "Underground Research Record 1": "uint8",
    "Underground Research Record 2": "uint8",
    "Underground Research Record 3": "uint8",
    "Underground Research Record 4": "uint8",
    "Letter to the Chief": "uint8",
    "Letter to two Brothers Weaponry": "uint8",
    "Letter to Popola": "uint8",
    "Letter to a Faraway Lover": "uint8",
    "Letter from Emil": "uint8",
    "Weapon Upgrade Notice": "uint8",
    "Letter from the Chief of The Aerie": "uint8",
}

Maps = {
    "World Map": "uint8",
    "unk": ["skip", 2],
    "Central Village Map": "uint8",
    "Lost Shrine Area Map": "uint8",
    "Lost Shrine Map": "uint8",
    "The Aerie Map": "uint8",
    "Seafront Map": "uint8",
    "Desert Map": "uint8",
    "Facade Map": "uint8",
    "Barren Temple Map": "uint8",
    "Junk Heap Area Map": "uint8",
    "Junk Heap Map": "uint8",
    "Manor Map": "uint8",
    "Forest of Myth Map": "uint8",
    "Underground Facility Map": "uint8",
    "unk1": ["skip", 1],
    "Shadowlord's Castle Map": "uint8",
    "unk2": ["skip", 1],
    "Northern Plains Map": "uint8",
    "Southern Plains Map": "uint8",
    "Eastern Road Map": "uint8",
    "Beneath the Forest of Myth Map": "uint8",
    "Toyko Map": "uint8",
}

Weapons = {
    "Nameless Blade": "uint8",
    "Phoenix Dagger": "uint8",
    "Beastbain": "uint8",
    "Labyrinth's Whisper": "uint8",
    "Fool's Embrace": "uint8",
    "Ancient Overlord": "uint8",
    "Rebirth": "uint8",
    "Earth Wyrm's Claw": "uint8",
    "Nirvana Dagger": "uint8",
    "Moonrise": "uint8",
    "Blade of Treachery": "uint8",
    "Lily-Leaf Sword": "uint8",
    "Faith": "uint8",
    "Iron Pipe": "uint8",
    "Kainé's Sword": "uint8",
    "Virtuous Contract": "uint8",
    "Cruel Oath": "uint8",
    "unk": ["skip", 3],
    "Kusanagi": "uint8",
    "Phoenix Sword": "uint8",
    "Beastlord": "uint8",
    "Labyrinth's Song": "uint8",
    "Fool's Lament": "uint8",
    "Fang of the Twins": "uint8",
    "Axe of Beheading": "uint8",
    "Vile Axe": "uint8",
    "Iron Will": "uint8",
    "Virtuous Treaty": "uint8",
    "unk1": ["skip", 10],
    "Transience": "uint8",
    "Phoenix Spear": "uint8",
    "Beastcurse": "uint8",
    "Labyrinth's Shout": "uint8",
    "Fool's Accord": "uint8",
    "The Devil Queen": "uint8",
    "Sunrise": "uint8",
    "Spear of the Usurper": "uint8",
    "Dragoon Lance": "uint8",
    "Captain's Holy Spear": "uint8",
    "Virtuous Dignity": "uint8",
}

Savefile = {
    "Corruptness": "uint32",
    "Map": ["string0", 32],
    "Spawn": "uint32",
    "Character": "uint32",
    "Name": ["string0", 32],
    "Health": "int32",
    "Health Kaine": "int32",
    "Health Emil": "int32",
    "Magic": "float32",
    "Magic Kaine": "float32",
    "Magic Emil": "float32",
    "Level": "int32",
    "unk3": ["skip", 8],
    "XP": "int32",
    "unk4": ["skip", 12],
    "Order Kaine": "uint32",
    "Order Emil": "uint32",
    "Active Weapon": "uint32",
    "Selected One Handed Sword": "uint32",
    "Selected Two Handed Sword": "uint32",
    "Selected Spear": "uint32",
    "unk5": ["skip", 8],
    "Left Bumper": "uint32",
    "Right Bumper": "uint32",
    "Left Trigger": "uint32",
    "Right Trigger": "uint32",
    "unk6": ["skip", 12],
    "Money": "int32",
    "Recovery": "Recovery",
    "unk7": ["skip", 7],
    "Cultivation": "Cultivation",
    "unk8": ["skip", 10],
    "Fishing": "Fishing",
    "unk9": ["skip", 5],
    "Raw Materials": "RawMaterials",
    "Key Items": "KeyItems",
    "unk10": ["skip", 176],
    "Documents": "Documents",
    "unk11": ["skip", 168],
    "Maps": "Maps",
    "unk12": ["skip", 264],
    "Total Play Time": "double",
    "unk13": ["skip", 4],
    "Weapons": "Weapons",
    "unk14": ["skip", 225],
    "Quests": ["array", "uint32", 16],
    "unk15": ["skip", 312],
    "Words": ["array", "uint32", 4],
    "unk16": ["skip", 168],
    "Tutorials": ["array", "uint32", 3],

    # "unk17": ["skip", 1104],
    "unk17a": ["skip", 412],
    'Garden': 'Garden',  # 360
    "unk17b": ["skip", 332],

    "Quest": "uint32",

    # "unk18": ["skip", 0x8600],
    "unk18a": ["skip", 1326],
    'Time': ["string0", 7],
    "unk18b": ["skip", 32971],

    "Checksum": "uint32",
    "unk19": ["skip", 0xc],
}

Garden = {
    'plot_0x0': ["string0", 24],
    'plot_0x1': ["string0", 24],
    'plot_0x2': ["string0", 24],
    'plot_0x3': ["string0", 24],
    'plot_0x4': ["string0", 24],
    'plot_1x0': ["string0", 24],
    'plot_1x1': ["string0", 24],
    'plot_1x2': ["string0", 24],
    'plot_1x3': ["string0", 24],
    'plot_1x4': ["string0", 24],
    'plot_2x0': ["string0", 24],
    'plot_2x1': ["string0", 24],
    'plot_2x2': ["string0", 24],
    'plot_2x3': ["string0", 24],
    'plot_2x4': ["string0", 24],
}

GAMEDATA = {
    "unk": ["skip", 0x8160],
    "Slot 1": "Savefile",
    "Slot 2": "Savefile",
    "Slot 3": "Savefile",
    "unk2": ["skip", 0x24980],
}

parts = {
    'Recovery': Recovery,
    'Cultivation': Cultivation,
    'Fishing': Fishing,
    'RawMaterials': RawMaterials,
    'KeyItems': KeyItems,
    'Documents': Documents,
    'Maps': Maps,
    'Weapons': Weapons,
    'Garden': Garden,
    'Savefile': Savefile,
    'GAMEDATA': GAMEDATA,
}


TYPE_MAP = {
    'uint8': 'B',
    'int32': 'i',
    'double': 'd',
    'uint32': 'I',
    'float32': 'f',
    'skip': 's',
    # 'skip': 'c',
    'string0': 's',
}

BYTES_MAP = {
    'B': 1,
    'i': 4,
    'd': 8,
    'I': 4,
    'f': 4,
    # 'c': 1,
    's': 1,
}


def to_struct(data: dict[str, Union[str, list[Union[str, int]]]], struct_sizes: dict[str, int]):
    byte_count = 0
    parts = []
    for name, value in data.items():
        # arr = False
        n = 1
        if isinstance(value, str):
            t = value
        else:
            if len(value) == 3:
                # arr = True
                _, t, n = value
            else:
                t, n = value

        try:
            c_type = TYPE_MAP[t]
        except KeyError:
            c_type = 's'
            n = struct_sizes[t]

        parts.append(c_type if n == 1 else f'{n}{c_type}')
        byte_count += n * BYTES_MAP[c_type]

    return ''.join(parts), byte_count


def make_structs():
    struct_sizes = {}
    for name, data in parts.items():
        as_struct, byte_count = to_struct(data, struct_sizes)
        struct_sizes[name] = byte_count
        print()
        print(f'{name}_struct = Struct({as_struct!r})')
        print(f'{name}_fields = {list(data.keys())}')
        # print()
        # print(f'class {name}:')
        # print(f'    _struct = Struct({as_struct!r})')
        # print(f'    _fields = {list(data.keys())}')


TYPE_CONSTRUCT_MAP = {
    'uint8': 'Int8ul',
    'int32': 'Int32sl',
    'uint32': 'Int32ul',
    'double': 'Float64l',
    'float32': 'Float32l',
    'skip': 'Bytes',
    # 'skip': 'c',
    'string0': 'PaddedString',
}


def to_construct(name: str, data: dict[str, Union[str, list[Union[str, int]]]]):
    to_call = {'PaddedString', 'Bytes'}
    parts = []
    for orig_key, value in data.items():
        basic_key = orig_key.replace(' ', '_').lower()
        key = re.sub(r'\W+', '', basic_key.replace('-', '_').replace('+', '_plus'))
        n = 1
        if isinstance(value, str):
            t = value
        else:
            if len(value) == 3:
                _, t, n = value
            else:
                t, n = value

        c_type = TYPE_CONSTRUCT_MAP.get(t, t)
        suffix = f'({n})' if c_type in to_call else '' if n == 1 else f'[{n}]'
        comment = '' if basic_key == key else f'  # {orig_key}'
        # parts.append(f"    '{key}' / {c_type}{suffix},{comment}")
        parts.append(f"    {key}={c_type}{suffix},{comment}")

    return '{} = Struct(\n{}\n)\n'.format(name, '\n'.join(parts))


def make_constructs():
    for name, data in parts.items():
        print(to_construct(name, data))
