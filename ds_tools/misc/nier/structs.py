from enum import IntFlag, _decompose
from struct import Struct

from ...core.itertools import partitioned
from .constants import WORDS

# region Item Structs
Recovery_struct = Struct('BBB18sBBBBBBBB2sBsB')
Recovery_fields = [
    'Medicinal Herb', 'Health Salve', 'Recovery Potion', 'unk', 'Strength Drop', 'Strength Capsule', 'Magic Drop',
    'Magic Capsule', 'Defense Drop', 'Defense Capsule', 'Spirit Drop', 'Spirit Capsule', 'unk1', 'Antidotal Weed',
    'unk2', 'Smelling Salts'
]

Cultivation_struct = Struct('BBB2sBBBBBBBBBBBBBBBBBBBB5sBBBBBBBBBBBBBBBBBBBB')
Cultivation_fields = [
    'Speed Fertilizer', 'Flowering Fertilizer', 'Bounty Fertilizer', 'unk', 'Pumpkin Seed', 'Watermelon Seed',
    'Melon Seed', 'Gourd Seed', 'Tomato Seed', 'Eggplant Seed', 'Bell Pepper Seed', 'Bean Seed', 'Wheat Seedling',
    'Rice Plant Seedling', 'Dahlia Bulb', 'Tulip Bulb', 'Freesia Bulb', 'Red Moonflower Seed', 'Gold Moonflower Seed',
    'Peach Moonflower Seed', 'Pink Moonflower Seed', 'Blue Moonflower Seed', 'Indigo Moonflower Seed',
    'White Moonflower Seed', 'unk1', 'Pumpkin', 'Watermelon', 'Melon', 'Gourd', 'Tomato', 'Eggplant', 'Bell Pepper',
    'Beans', 'Wheat', 'Rice', 'Dahlia', 'Tulip', 'Freesia', 'Red Moonflower', 'Gold Moonflower', 'Peach Moonflower',
    'Pink Moonflower', 'Blue Moonflower', 'Indigo Moonflower', 'White Moonflower'
]

Fishing_struct = Struct('BBB7sBBBBBBBBBBBBBBB')
Fishing_fields = [
    'Lugworm', 'Earthworm', 'Lure', 'unk', 'Sardine', 'Carp', 'Blowfish', 'Bream', 'Shark', 'Blue Marlin',
    'Dunkleosteus', 'Rainbow Trout', 'Black Bass', 'Giant Catfish', 'Royal Fish', 'Hyneria', 'Sandfish', 'Rhizodont',
    'Shaman Fish'
]

RawMaterials_struct = Struct('BBBB3sBBBBBBBBBBB4sBBBBBBBBB5sBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB4sBBBBBBBBBBBBBBBBBBBBBBBBBsBBBBBBBBBB5sBBBBBBBsBB3sB')
RawMaterials_fields = [
    'Aquatic Plant', 'Deadwood', 'Rusty Bucket', 'Empty Can',
    'unk',
    'Gold Ore', 'Silver Ore', 'Copper Ore', 'Iron Ore', 'Crystal', 'Pyrite', 'Moldavite', 'Meteorite', 'Amber', 'Fluorite', 'Clay',
    'unk1',
    'Berries', 'Royal Fern', 'Tree Branch', 'Log', 'Natural Rubber', 'Ivy', 'Lichen', 'Mushroom', 'Sap',
    'unk2',
    'Mutton', 'Boar Meat', 'Wool', 'Boar Hide', 'Wolf Hide', 'Wolf Fang', 'Giant Spider Silk', 'Bat Fang', 'Bat Wing',
    'Goat Meat', 'Goat Hide', 'Venison', 'Rainbow Spider Silk', 'Boar Liver', 'Scorpion Claw', 'Scorpion Tail',
    'Dented Metal Board', 'Stripped Bolt', 'Broken Lens', 'Severed Cable', 'Broken Arm', 'Broken Antenna',
    'Broken Motor', 'Broken Battery', 'Mysterious Switch', 'Large Gear', 'Titanium Alloy', 'Memory Alloy',
    'Rusted Clump', 'Machine Oil',
    'unk3',
    'Forlorn Necklace', 'Twisted Ring', 'Broken Earring', 'Pretty Choker', 'Metal Piercing', 'Subdued Bracelet',
    'Technical Guide', 'Grubby Book', 'Thick Dictionary', 'Closed Book', 'Used Coloring Book', 'Old Schoolbook',
    'Dirty Bag', 'Flashy Hat', 'Leather Gloves', 'Silk Handkerchief', 'Leather Boots', 'Complex Machine',
    'Elaborate Machine', 'Simple Machine', 'Stopped Clock', 'Broken Wristwatch', 'Rusty Kitchen Knife', 'Broken Saw',
    'Dented Metal Bat',
    'unk4',
    'Shell', 'Gastropod', 'Bivalve', 'Seaweed', 'Empty Bottle', 'Driftwood', 'Pearl',
    'Black Pearl', 'Crab', 'Starfish',
    'unk5',
    'Sea Turtle Egg', 'Broken Pottery', 'Desert Rose', 'Giant Egg', 'Damascus Steel', 'Eagle Egg', 'Chicken Egg',
    'unk6',
    'Mouse Tail', 'Lizard Tail',
    'unk7',
    'Deer Antler',
]

KeyItems_struct = Struct('BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB')
KeyItems_fields = [
    'Moon Key', 'Star Key', 'Light Key', 'Darkness Key', 'Fine Flour', 'Coarse Flour', 'Perfume Bottle',
    "Postman's Parcel", "Lover's Letter", 'Water Filter', 'Royal Compass', 'Vapor Moss', 'Valley Spider Silk',
    'Animal Guidebook', 'Ore Guidebook', 'Plant Guidebook', 'Red Book', 'Blue Book', "Old Lady's Elixir",
    "Old Lady's Elixir+", 'Parcel for The Aerie', 'Parcel for Seafront', 'Cookbook', 'Parcel for Facade', "Max's Herbs",
    'Drifting Cargo', 'Drifting Cargo 2', 'Drifting Cargo 3', 'Drifting Cargo 4', 'Old Package', 'Mermaid Tear',
    'Mandrake Leaf', 'Energizer', 'Toad Oil', 'Sleep-B-Gone', 'Antidote', 'Gold Bracelet', 'Elite Kitchen Knife',
    'Elevator Parts', 'Dirty Treasure Map', 'Restored Treasure Map', 'Jade Hair Ornament', 'Employee List',
    'Small Safe', 'Safe Key', 'Great Tree Root', 'Eye of Power', 'Ribbon', "Yonah's Ribbon", 'Bronze Key', 'Brass Key',
    'Boar Tusk', 'Pressed Freesia', 'Potted Freesia', 'Freesia (Delivery)', 'Pile of Junk', 'Old Gold Coin',
    'Marked Map', 'AA Keycard', 'KA Keycard', 'SA Keycard', 'TA Keycard', 'NA Keycard', 'HA Keycard', 'MA Keycard',
    'YA Keycard', 'RA Keycard', 'WA Keycard', "Cultivator's Handbook", 'Red Bag', 'Lantern', 'Empty Lantern',
    'Hold Key', 'Passageway Key', 'Goat Key', 'Lizard Key', 'Unlocking Procedure Memo', 'Red Jewel?', 'Red Flowers',
    'Apples'
]

Documents_struct = Struct('BBBBBBBBBBBBBBBBBBBBBBBB')
Documents_fields = [
    'Look at the Sky', "Don't try so hard", 'My Birthday!', 'Love Letter 2/12/3340', 'Love Letter 3/28/3340',
    'Love Letter 5/1/3340', 'Letter from the Mayor', "The Postman's Request", "The Postman's Thanks",
    'Invitation from a Stranger', 'Grand Re-Opening Notice', 'Wedding Invitation', 'Letter from the King',
    'Underground Research Record 1', 'Underground Research Record 2', 'Underground Research Record 3',
    'Underground Research Record 4', 'Letter to the Chief', 'Letter to two Brothers Weaponry', 'Letter to Popola',
    'Letter to a Faraway Lover', 'Letter from Emil', 'Weapon Upgrade Notice', 'Letter from the Chief of The Aerie'
]

Maps_struct = Struct('B2sBBBBBBBBBBBBBsBsBBBBB')
Maps_fields = [
    'World Map', 'unk', 'Central Village Map', 'Lost Shrine Area Map', 'Lost Shrine Map', 'The Aerie Map',
    'Seafront Map', 'Desert Map', 'Facade Map', 'Barren Temple Map', 'Junk Heap Area Map', 'Junk Heap Map', 'Manor Map',
    'Forest of Myth Map', 'Underground Facility Map', 'unk1', "Shadowlord's Castle Map", 'unk2', 'Northern Plains Map',
    'Southern Plains Map', 'Eastern Road Map', 'Beneath the Forest of Myth Map', 'Toyko Map'
]

Weapons_struct = Struct('BBBBBBBBBBBBBBBBB3sBBBBBBBBBB10sBBBBBBBBBBB')
Weapons_fields = [
    'Nameless Blade', 'Phoenix Dagger', 'Beastbain', "Labyrinth's Whisper", "Fool's Embrace", 'Ancient Overlord',
    'Rebirth', "Earth Wyrm's Claw", 'Nirvana Dagger', 'Moonrise', 'Blade of Treachery', 'Lily-Leaf Sword', 'Faith',
    'Iron Pipe', "Kainé's Sword", 'Virtuous Contract', 'Cruel Oath',
    'unk',
    'Kusanagi', 'Phoenix Sword', 'Beastlord', "Labyrinth's Song", "Fool's Lament", 'Fang of the Twins',
    'Axe of Beheading', 'Vile Axe', 'Iron Will', 'Virtuous Treaty',
    'unk1',
    'Transience', 'Phoenix Spear', 'Beastcurse', "Labyrinth's Shout", "Fool's Accord", 'The Devil Queen', 'Sunrise',
    'Spear of the Usurper', 'Dragoon Lance', "Captain's Holy Spear", 'Virtuous Dignity'
]

# endregion

Garden_struct = Struct('24s24s24s24s24s24s24s24s24s24s24s24s24s24s24s')
Garden_fields = [
    'plot_0x0', 'plot_0x1', 'plot_0x2', 'plot_0x3', 'plot_0x4',
    'plot_1x0', 'plot_1x1', 'plot_1x2', 'plot_1x3', 'plot_1x4',
    'plot_2x0', 'plot_2x1', 'plot_2x2', 'plot_2x3', 'plot_2x4',
]

GardenPlot_struct = Struct('B 3s B 3s B 7s 7s x')
GardenPlot_fields = ['Seed', 'unk1', 'Fertilizer', 'unk2', 'Water', 'unk3', 'Time']

Savefile_struct = Struct(
    'I 32s II 32s' 'iii fff' 'i 8s i 12s II' 'IIII 8s'
    'IIII 12s' 'i 34s 7s 50s 10s 25s 5s 125s 80s 176s' '24s 168s 24s 264s d 4s' '51s 225s 16I 312s 4I 168s 3I'
    '412s 360s 332s' 'I' '1326s 7s 32971s' 'I 12s'
)

Savefile_fields = [
    'Corruptness', 'Map', 'Spawn', 'Character', 'Name',
    'Health', 'Health Kaine', 'Health Emil', 'Magic', 'Magic Kaine', 'Magic Emil',
    'Level', 'unk3', 'XP', 'unk4', 'Order Kaine', 'Order Emil',
    'Active Weapon', 'Selected One Handed Sword', 'Selected Two Handed Sword', 'Selected Spear', 'unk5',

    'Left Bumper', 'Right Bumper', 'Left Trigger', 'Right Trigger', 'unk6',
    'Money', 'Recovery', 'unk7', 'Cultivation', 'unk8', 'Fishing', 'unk9', 'Raw Materials', 'Key Items', 'unk10',
    'Documents', 'unk11', 'Maps', 'unk12', 'Total Play Time', 'unk13',
    'Weapons', 'unk14', 'Quests', 'unk15', 'Words', 'unk16', 'Tutorials',

    'unk17a', 'Garden', 'unk17b',
    'Quest',
    'unk18a', 'Time', 'unk18b',
    'Checksum', 'unk19'
]

GAMEDATA_struct = Struct('33120s37472s37472s37472s149888s')
GAMEDATA_fields = ['unk', 'Slot 1', 'Slot 2', 'Slot 3', 'unk2']

FIELD_STRUCT_MAP = {
    'Recovery': (Recovery_struct, Recovery_fields),
    'Cultivation': (Cultivation_struct, Cultivation_fields),
    'Fishing': (Fishing_struct, Fishing_fields),
    'Raw Materials': (RawMaterials_struct, RawMaterials_fields),
    'Key Items': (KeyItems_struct, KeyItems_fields),
    'Documents': (Documents_struct, Documents_fields),
    'Maps': (Maps_struct, Maps_fields),
    'Weapons': (Weapons_struct, Weapons_fields),
    'Garden': (Garden_struct, Garden_fields),
    'GardenPlot': (GardenPlot_struct, GardenPlot_fields),
}

Time = Struct('HBBBBB')


class IterIntFlag(IntFlag):
    def __iter__(self):
        members, uncovered = _decompose(self.__class__, self._value_)
        yield from members


WORD_FLAGS = [
    IterIntFlag._create_(f'Words_{c}', [w if w else f'WORD_{32 * c + i}' for i, w in enumerate(chunk)])
    for c, chunk in enumerate(partitioned(WORDS, 32))
]
