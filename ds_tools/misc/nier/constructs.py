"""

"""

import logging
from enum import IntFlag, _decompose

from construct import Struct, Int8ul, Int32sl, Int32ul, Float64l, Float32l, PaddedString, Bytes, Int16ul
from construct import Enum, FlagsEnum

from ...core.itertools import partitioned
from .constants import WORDS, CHARACTERS, PLANTS, FERTILIZER

log = logging.getLogger(__name__)
__all__ = []


Time = Struct('year'/Int16ul, 'month'/Int8ul, 'day'/Int8ul, 'hour'/Int8ul, 'minute'/Int8ul, 'second'/Int8ul)  # noqa
Character = Enum(Int32ul, **{k: i for i, k in enumerate(CHARACTERS)})
Seed = Enum(Int8ul, **{k: i for i, k in enumerate(PLANTS)})
Fertilizer = Enum(Int8ul, **{k: i for i, k in enumerate(FERTILIZER)})
Water = FlagsEnum(Int8ul, once=1, twice=2)

Plot = Struct(
    'seed' / Seed,
    'unk1' / Bytes(3),
    'fertilizer' / Fertilizer,
    'unk2' / Bytes(3),
    'water' / Water,
    'unk3' / Bytes(7),
    'time' / Time,
    'unk4' / Bytes(1),
)
Garden = Struct(
    'plot_0x0' / Plot, 'plot_0x1' / Plot, 'plot_0x2' / Plot, 'plot_0x3' / Plot, 'plot_0x4' / Plot,
    'plot_1x0' / Plot, 'plot_1x1' / Plot, 'plot_1x2' / Plot, 'plot_1x3' / Plot, 'plot_1x4' / Plot,
    'plot_2x0' / Plot, 'plot_2x1' / Plot, 'plot_2x2' / Plot, 'plot_2x3' / Plot, 'plot_2x4' / Plot,
)


# region item structs

# noinspection PyUnresolvedReferences
Recovery = Struct(
    'medicinal_herb' / Int8ul,
    'health_salve' / Int8ul,
    'recovery_potion' / Int8ul,
    'unk' / Bytes(18),
    'strength_drop' / Int8ul,
    'strength_capsule' / Int8ul,
    'magic_drop' / Int8ul,
    'magic_capsule' / Int8ul,
    'defense_drop' / Int8ul,
    'defense_capsule' / Int8ul,
    'spirit_drop' / Int8ul,
    'spirit_capsule' / Int8ul,
    'unk1' / Bytes(2),
    'antidotal_weed' / Int8ul,
    'unk2' / Bytes(1),
    'smelling_salts' / Int8ul,
)

# noinspection PyUnresolvedReferences
Cultivation = Struct(
    'speed_fertilizer' / Int8ul,
    'flowering_fertilizer' / Int8ul,
    'bounty_fertilizer' / Int8ul,
    'unk' / Bytes(2),
    'pumpkin_seed' / Int8ul,
    'watermelon_seed' / Int8ul,
    'melon_seed' / Int8ul,
    'gourd_seed' / Int8ul,
    'tomato_seed' / Int8ul,
    'eggplant_seed' / Int8ul,
    'bell_pepper_seed' / Int8ul,
    'bean_seed' / Int8ul,
    'wheat_seedling' / Int8ul,
    'rice_plant_seedling' / Int8ul,
    'dahlia_bulb' / Int8ul,
    'tulip_bulb' / Int8ul,
    'freesia_bulb' / Int8ul,
    'red_moonflower_seed' / Int8ul,
    'gold_moonflower_seed' / Int8ul,
    'peach_moonflower_seed' / Int8ul,
    'pink_moonflower_seed' / Int8ul,
    'blue_moonflower_seed' / Int8ul,
    'indigo_moonflower_seed' / Int8ul,
    'white_moonflower_seed' / Int8ul,
    'unk1' / Bytes(5),
    'pumpkin' / Int8ul,
    'watermelon' / Int8ul,
    'melon' / Int8ul,
    'gourd' / Int8ul,
    'tomato' / Int8ul,
    'eggplant' / Int8ul,
    'bell_pepper' / Int8ul,
    'beans' / Int8ul,
    'wheat' / Int8ul,
    'rice' / Int8ul,
    'dahlia' / Int8ul,
    'tulip' / Int8ul,
    'freesia' / Int8ul,
    'red_moonflower' / Int8ul,
    'gold_moonflower' / Int8ul,
    'peach_moonflower' / Int8ul,
    'pink_moonflower' / Int8ul,
    'blue_moonflower' / Int8ul,
    'indigo_moonflower' / Int8ul,
    'white_moonflower' / Int8ul,
)

# noinspection PyUnresolvedReferences
Fishing = Struct(
    'lugworm' / Int8ul,
    'earthworm' / Int8ul,
    'lure' / Int8ul,
    'unk' / Bytes(7),
    'sardine' / Int8ul,
    'carp' / Int8ul,
    'blowfish' / Int8ul,
    'bream' / Int8ul,
    'shark' / Int8ul,
    'blue_marlin' / Int8ul,
    'dunkleosteus' / Int8ul,
    'rainbow_trout' / Int8ul,
    'black_bass' / Int8ul,
    'giant_catfish' / Int8ul,
    'royal_fish' / Int8ul,
    'hyneria' / Int8ul,
    'sandfish' / Int8ul,
    'rhizodont' / Int8ul,
    'shaman_fish' / Int8ul,
)

# noinspection PyUnresolvedReferences
RawMaterials = Struct(
    'aquatic_plant' / Int8ul,
    'deadwood' / Int8ul,
    'rusty_bucket' / Int8ul,
    'empty_can' / Int8ul,
    'unk' / Bytes(3),
    'gold_ore' / Int8ul,
    'silver_ore' / Int8ul,
    'copper_ore' / Int8ul,
    'iron_ore' / Int8ul,
    'crystal' / Int8ul,
    'pyrite' / Int8ul,
    'moldavite' / Int8ul,
    'meteorite' / Int8ul,
    'amber' / Int8ul,
    'fluorite' / Int8ul,
    'clay' / Int8ul,
    'unk1' / Bytes(4),
    'berries' / Int8ul,
    'royal_fern' / Int8ul,
    'tree_branch' / Int8ul,
    'log' / Int8ul,
    'natural_rubber' / Int8ul,
    'ivy' / Int8ul,
    'lichen' / Int8ul,
    'mushroom' / Int8ul,
    'sap' / Int8ul,
    'unk2' / Bytes(5),
    'mutton' / Int8ul,
    'boar_meat' / Int8ul,
    'wool' / Int8ul,
    'boar_hide' / Int8ul,
    'wolf_hide' / Int8ul,
    'wolf_fang' / Int8ul,
    'giant_spider_silk' / Int8ul,
    'bat_fang' / Int8ul,
    'bat_wing' / Int8ul,
    'goat_meat' / Int8ul,
    'goat_hide' / Int8ul,
    'venison' / Int8ul,
    'rainbow_spider_silk' / Int8ul,
    'boar_liver' / Int8ul,
    'scorpion_claw' / Int8ul,
    'scorpion_tail' / Int8ul,
    'dented_metal_board' / Int8ul,
    'stripped_bolt' / Int8ul,
    'broken_lens' / Int8ul,
    'severed_cable' / Int8ul,
    'broken_arm' / Int8ul,
    'broken_antenna' / Int8ul,
    'broken_motor' / Int8ul,
    'broken_battery' / Int8ul,
    'mysterious_switch' / Int8ul,
    'large_gear' / Int8ul,
    'titanium_alloy' / Int8ul,
    'memory_alloy' / Int8ul,
    'rusted_clump' / Int8ul,
    'machine_oil' / Int8ul,
    'unk3' / Bytes(4),
    'forlorn_necklace' / Int8ul,
    'twisted_ring' / Int8ul,
    'broken_earring' / Int8ul,
    'pretty_choker' / Int8ul,
    'metal_piercing' / Int8ul,
    'subdued_bracelet' / Int8ul,
    'technical_guide' / Int8ul,
    'grubby_book' / Int8ul,
    'thick_dictionary' / Int8ul,
    'closed_book' / Int8ul,
    'used_coloring_book' / Int8ul,
    'old_schoolbook' / Int8ul,
    'dirty_bag' / Int8ul,
    'flashy_hat' / Int8ul,
    'leather_gloves' / Int8ul,
    'silk_handkerchief' / Int8ul,
    'leather_boots' / Int8ul,
    'complex_machine' / Int8ul,
    'elaborate_machine' / Int8ul,
    'simple_machine' / Int8ul,
    'stopped_clock' / Int8ul,
    'broken_wristwatch' / Int8ul,
    'rusty_kitchen_knife' / Int8ul,
    'broken_saw' / Int8ul,
    'dented_metal_bat' / Int8ul,
    'unk4' / Bytes(1),
    'shell' / Int8ul,
    'gastropod' / Int8ul,
    'bivalve' / Int8ul,
    'seaweed' / Int8ul,
    'empty_bottle' / Int8ul,
    'driftwood' / Int8ul,
    'pearl' / Int8ul,
    'black_pearl' / Int8ul,
    'crab' / Int8ul,
    'starfish' / Int8ul,
    'unk5' / Bytes(5),
    'sea_turtle_egg' / Int8ul,
    'broken_pottery' / Int8ul,
    'desert_rose' / Int8ul,
    'giant_egg' / Int8ul,
    'damascus_steel' / Int8ul,
    'eagle_egg' / Int8ul,
    'chicken_egg' / Int8ul,
    'unk6' / Bytes(1),
    'mouse_tail' / Int8ul,
    'lizard_tail' / Int8ul,
    'unk7' / Bytes(3),
    'deer_antler' / Int8ul,
)

# noinspection PyUnresolvedReferences
KeyItems = Struct(
    'moon_key' / Int8ul,
    'star_key' / Int8ul,
    'light_key' / Int8ul,
    'darkness_key' / Int8ul,
    'fine_flour' / Int8ul,
    'coarse_flour' / Int8ul,
    'perfume_bottle' / Int8ul,
    'postmans_parcel' / Int8ul,  # Postman's Parcel
    'lovers_letter' / Int8ul,  # Lover's Letter
    'water_filter' / Int8ul,
    'royal_compass' / Int8ul,
    'vapor_moss' / Int8ul,
    'valley_spider_silk' / Int8ul,
    'animal_guidebook' / Int8ul,
    'ore_guidebook' / Int8ul,
    'plant_guidebook' / Int8ul,
    'red_book' / Int8ul,
    'blue_book' / Int8ul,
    'old_ladys_elixir' / Int8ul,  # Old Lady's Elixir
    'old_ladys_elixir_plus' / Int8ul,  # Old Lady's Elixir+
    'parcel_for_the_aerie' / Int8ul,
    'parcel_for_seafront' / Int8ul,
    'cookbook' / Int8ul,
    'parcel_for_facade' / Int8ul,
    'maxs_herbs' / Int8ul,  # Max's Herbs
    'drifting_cargo' / Int8ul,
    'drifting_cargo_2' / Int8ul,
    'drifting_cargo_3' / Int8ul,
    'drifting_cargo_4' / Int8ul,
    'old_package' / Int8ul,
    'mermaid_tear' / Int8ul,
    'mandrake_leaf' / Int8ul,
    'energizer' / Int8ul,
    'toad_oil' / Int8ul,
    'sleep_b_gone' / Int8ul,  # Sleep-B-Gone
    'antidote' / Int8ul,
    'gold_bracelet' / Int8ul,
    'elite_kitchen_knife' / Int8ul,
    'elevator_parts' / Int8ul,
    'dirty_treasure_map' / Int8ul,
    'restored_treasure_map' / Int8ul,
    'jade_hair_ornament' / Int8ul,
    'employee_list' / Int8ul,
    'small_safe' / Int8ul,
    'safe_key' / Int8ul,
    'great_tree_root' / Int8ul,
    'eye_of_power' / Int8ul,
    'ribbon' / Int8ul,
    'yonahs_ribbon' / Int8ul,  # Yonah's Ribbon
    'bronze_key' / Int8ul,
    'brass_key' / Int8ul,
    'boar_tusk' / Int8ul,
    'pressed_freesia' / Int8ul,
    'potted_freesia' / Int8ul,
    'freesia_delivery' / Int8ul,  # Freesia (Delivery)
    'pile_of_junk' / Int8ul,
    'old_gold_coin' / Int8ul,
    'marked_map' / Int8ul,
    'aa_keycard' / Int8ul,
    'ka_keycard' / Int8ul,
    'sa_keycard' / Int8ul,
    'ta_keycard' / Int8ul,
    'na_keycard' / Int8ul,
    'ha_keycard' / Int8ul,
    'ma_keycard' / Int8ul,
    'ya_keycard' / Int8ul,
    'ra_keycard' / Int8ul,
    'wa_keycard' / Int8ul,
    'cultivators_handbook' / Int8ul,  # Cultivator's Handbook
    'red_bag' / Int8ul,
    'lantern' / Int8ul,
    'empty_lantern' / Int8ul,
    'hold_key' / Int8ul,
    'passageway_key' / Int8ul,
    'goat_key' / Int8ul,
    'lizard_key' / Int8ul,
    'unlocking_procedure_memo' / Int8ul,
    'red_jewel' / Int8ul,  # Red Jewel?
    'red_flowers' / Int8ul,
    'apples' / Int8ul,
)

# noinspection PyUnresolvedReferences
Documents = Struct(
    'look_at_the_sky' / Int8ul,
    'dont_try_so_hard' / Int8ul,  # Don't try so hard
    'my_birthday' / Int8ul,  # My Birthday!
    'love_letter_2123340' / Int8ul,  # Love Letter 2/12/3340
    'love_letter_3283340' / Int8ul,  # Love Letter 3/28/3340
    'love_letter_513340' / Int8ul,  # Love Letter 5/1/3340
    'letter_from_the_mayor' / Int8ul,
    'the_postmans_request' / Int8ul,  # The Postman's Request
    'the_postmans_thanks' / Int8ul,  # The Postman's Thanks
    'invitation_from_a_stranger' / Int8ul,
    'grand_re_opening_notice' / Int8ul,  # Grand Re-Opening Notice
    'wedding_invitation' / Int8ul,
    'letter_from_the_king' / Int8ul,
    'underground_research_record_1' / Int8ul,
    'underground_research_record_2' / Int8ul,
    'underground_research_record_3' / Int8ul,
    'underground_research_record_4' / Int8ul,
    'letter_to_the_chief' / Int8ul,
    'letter_to_two_brothers_weaponry' / Int8ul,
    'letter_to_popola' / Int8ul,
    'letter_to_a_faraway_lover' / Int8ul,
    'letter_from_emil' / Int8ul,
    'weapon_upgrade_notice' / Int8ul,
    'letter_from_the_chief_of_the_aerie' / Int8ul,
)

# noinspection PyUnresolvedReferences
Maps = Struct(
    'world_map' / Int8ul,
    'unk' / Bytes(2),
    'central_village_map' / Int8ul,
    'lost_shrine_area_map' / Int8ul,
    'lost_shrine_map' / Int8ul,
    'the_aerie_map' / Int8ul,
    'seafront_map' / Int8ul,
    'desert_map' / Int8ul,
    'facade_map' / Int8ul,
    'barren_temple_map' / Int8ul,
    'junk_heap_area_map' / Int8ul,
    'junk_heap_map' / Int8ul,
    'manor_map' / Int8ul,
    'forest_of_myth_map' / Int8ul,
    'underground_facility_map' / Int8ul,
    'unk1' / Bytes(1),
    'shadowlords_castle_map' / Int8ul,  # Shadowlord's Castle Map
    'unk2' / Bytes(1),
    'northern_plains_map' / Int8ul,
    'southern_plains_map' / Int8ul,
    'eastern_road_map' / Int8ul,
    'beneath_the_forest_of_myth_map' / Int8ul,
    'toyko_map' / Int8ul,
)

# noinspection PyUnresolvedReferences
Weapons = Struct(
    'nameless_blade' / Int8ul,
    'phoenix_dagger' / Int8ul,
    'beastbain' / Int8ul,
    'labyrinths_whisper' / Int8ul,  # Labyrinth's Whisper
    'fools_embrace' / Int8ul,  # Fool's Embrace
    'ancient_overlord' / Int8ul,
    'rebirth' / Int8ul,
    'earth_wyrms_claw' / Int8ul,  # Earth Wyrm's Claw
    'nirvana_dagger' / Int8ul,
    'moonrise' / Int8ul,
    'blade_of_treachery' / Int8ul,
    'lily_leaf_sword' / Int8ul,  # Lily-Leaf Sword
    'faith' / Int8ul,
    'iron_pipe' / Int8ul,
    'kainés_sword' / Int8ul,  # Kainé's Sword
    'virtuous_contract' / Int8ul,
    'cruel_oath' / Int8ul,
    'unk' / Bytes(3),
    'kusanagi' / Int8ul,
    'phoenix_sword' / Int8ul,
    'beastlord' / Int8ul,
    'labyrinths_song' / Int8ul,  # Labyrinth's Song
    'fools_lament' / Int8ul,  # Fool's Lament
    'fang_of_the_twins' / Int8ul,
    'axe_of_beheading' / Int8ul,
    'vile_axe' / Int8ul,
    'iron_will' / Int8ul,
    'virtuous_treaty' / Int8ul,
    'unk1' / Bytes(10),
    'transience' / Int8ul,
    'phoenix_spear' / Int8ul,
    'beastcurse' / Int8ul,
    'labyrinths_shout' / Int8ul,  # Labyrinth's Shout
    'fools_accord' / Int8ul,  # Fool's Accord
    'the_devil_queen' / Int8ul,
    'sunrise' / Int8ul,
    'spear_of_the_usurper' / Int8ul,
    'dragoon_lance' / Int8ul,
    'captains_holy_spear' / Int8ul,  # Captain's Holy Spear
    'virtuous_dignity' / Int8ul,
)

# endregion

# noinspection PyUnresolvedReferences
Savefile = Struct(
    'corruptness' / Int32ul,
    'map' / PaddedString(32, 'utf-8'),
    'spawn' / Int32ul,
    'character' / Character,
    'name' / PaddedString(32, 'utf-8'),
    'health' / Int32sl, 'health_kaine' / Int32sl, 'health_emil' / Int32sl,
    'magic' / Float32l, 'magic_kaine' / Float32l, 'magic_emil' / Float32l,
    'level' / Int32sl,
    'unk3' / Bytes(8),
    'xp' / Int32sl,
    'unk4' / Bytes(12),
    'order_kaine' / Int32ul, 'order_emil' / Int32ul,
    'active_weapon' / Int32ul,
    'selected_one_handed_sword' / Int32ul, 'selected_two_handed_sword' / Int32ul, 'selected_spear' / Int32ul,
    'unk5' / Bytes(8),
    'left_bumper' / Int32ul, 'right_bumper' / Int32ul, 'left_trigger' / Int32ul, 'right_trigger' / Int32ul,
    'unk6' / Bytes(12),
    'money' / Int32sl,
    'recovery' / Recovery,
    'unk7' / Bytes(7),
    'cultivation' / Cultivation,
    'unk8' / Bytes(10),
    'fishing' / Fishing,
    'unk9' / Bytes(5),
    'raw_materials' / RawMaterials,
    'key_items' / KeyItems,
    'unk10' / Bytes(176),
    'documents' / Documents,
    'unk11' / Bytes(168),
    'maps' / Maps,
    'unk12' / Bytes(264),
    'total_play_time' / Float64l,
    'unk13' / Bytes(4),
    'weapons' / Weapons,
    'unk14' / Bytes(225),
    'quests' / Int32ul[16],
    'unk15' / Bytes(312),
    'words' / Int32ul[4],  # TODO
    'unk16' / Bytes(168),
    'tutorials' / Int32ul[3],
    'unk17a' / Bytes(412),
    'garden' / Garden,
    'unk17b' / Bytes(332),
    'quest' / Int32ul,
    'unk18a' / Bytes(1326),
    'time' / Time,
    'unk18b' / Bytes(32971),
    'checksum' / Int32ul,
    'unk19' / Bytes(12),
)


GameData = Struct('unk'/Bytes(33120), 'slot_1'/Savefile, 'slot_2'/Savefile, 'slot_3'/Savefile, 'unk2'/Bytes(149888))
