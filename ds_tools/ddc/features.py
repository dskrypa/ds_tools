"""
Most classes automatically generated from https://github.com/rockowitz/ddcutil/blob/master/src/vcp/vcp_feature_codes.c

Alternate versions of feature code:name maps based on mccs version are not supported.

:author: Doug Skrypa
"""

from __future__ import annotations

from functools import cached_property
from typing import Optional, Union, TypeVar

T = TypeVar('T')


class Feature:
    _code_feat_map = {}
    _name_feat_map = {}
    _cls_model_inst_map = {}
    code: int
    name: str
    model: Optional[str] = None
    value_names: dict[int, Optional[str]]
    hide_extras = False

    def __init_subclass__(cls, code: int, name: str, **kwargs):  # noqa
        super().__init_subclass__(**kwargs)
        cls.code = code
        cls.name = name
        cls._code_feat_map[code] = cls
        cls._name_feat_map[name] = cls

    def __new__(cls, model=None, value_names=None):
        try:
            model_inst_map = cls._cls_model_inst_map[cls]
        except KeyError:
            cls._cls_model_inst_map[cls] = model_inst_map = {}
        try:
            return model_inst_map[model]
        except KeyError:
            if not value_names:  # Only
                model = None
                try:
                    return model_inst_map[model]
                except KeyError:
                    pass

            model_inst_map[model] = inst = super().__new__(cls)
            return inst

    def __init__(self, model: Optional[str] = None, value_names: Optional[dict[int, Optional[str]]] = None):
        if value_names:
            self.model = model
            self.value_names = value_names

    def __repr__(self) -> str:
        if self.model:
            return f'<{self.__class__.__name__}[0x{self.code:02X} / {self.name} for {self.model}]>'
        return f'<{self.__class__.__name__}[0x{self.code:02X} / {self.name}]>'

    def __hash__(self) -> int:
        return hash(self.code) ^ hash(self.__class__)

    def __eq__(self, other: Feature) -> bool:
        return self.code == other.code

    def __lt__(self, other: Feature) -> bool:
        return self.code < other.code

    @classmethod
    def for_code(cls, code: Union[str, int], model: Optional[str] = None) -> Feature:
        try:
            return cls._code_feat_map[code](model)
        except KeyError:
            try:
                code = code if isinstance(code, int) else int(code, 16)
            except (TypeError, ValueError):
                raise ValueError(f'Invalid feature {code=!r}')

            class UnknownFeature(Feature, code=code, name=f'unknown feature 0x{code:02X}'):
                value_names = {}

            return UnknownFeature()

    @classmethod
    def for_name(cls, name: str, model: Optional[str] = None) -> Feature:
        return cls._name_feat_map[name](model)

    @cached_property
    def name_value_map(self) -> dict[str, int]:
        return {v: k for k, v in self.value_names.items()}

    def code_for(self, str_value: str) -> int:
        return self.name_value_map[str_value]

    def name_for(self, code: int, default: T = None) -> str | T:
        return self.value_names.get(code, default)


FeatureOrId = Union[str, int, Feature]


# region Feature Classes


class InputSource(Feature, code=0x60, name='input'):
    value_names = {
        0x01: 'VGA-1',
        0x02: 'VGA-2',
        0x03: 'DVI-1',
        0x04: 'DVI-2',
        0x05: 'Composite video 1',
        0x06: 'Composite video 2',
        0x07: 'S-Video-1',
        0x08: 'S-Video-2',
        0x09: 'Tuner-1',
        0x0A: 'Tuner-2',
        0x0B: 'Tuner-3',
        0x0C: 'Component video (YPrPb/YCrCb) 1',
        0x0D: 'Component video (YPrPb/YCrCb) 2',
        0x0E: 'Component video (YPrPb/YCrCb) 3',
        0x0F: 'DisplayPort-1',
        0x10: 'DisplayPort-2',
        0x11: 'HDMI-1',
        0x12: 'HDMI-2',
    }


class NewControl(Feature, code=0x02, name='new control'):
    value_names = {
        0x01: 'No new control values',
        0x02: 'One or more new control values have been saved',
        0xFF: 'No user controls are present',
    }


class SoftControls(Feature, code=0x03, name='soft controls'):
    value_names = {
        0x00: 'No button active',
        0x01: 'Button 1 active',
        0x02: 'Button 2 active',
        0x03: 'Button 3 active',
        0x04: 'Button 4 active',
        0x05: 'Button 5 active',
        0x06: 'Button 6 active',
        0x07: 'Button 7 active',
        0xFF: 'No user controls are present',
    }


class ColorTemperature(Feature, code=0x14, name='color temperature'):
    value_names = {
        0x01: 'sRGB',
        0x02: 'Display Native',
        0x03: '4000 K',
        0x04: '5000 K',
        0x05: '6500 K',
        0x06: '7500 K',
        0x07: '8200 K',
        0x08: '9300 K',
        0x09: '10000 K',
        0x0A: '11500 K',
        0x0B: 'User 1',
        0x0C: 'User 2',
        0x0D: 'User 3',
    }


class AutoSetup(Feature, code=0x1E, name='auto setup'):
    value_names = {
        0x00: 'Auto setup not active',
        0x01: 'Performing auto setup',
        0x02: 'Enable continuous/periodic auto setup',
    }


class AutoSetup2(Feature, code=0x1F, name='auto setup 2'):
    value_names = AutoSetup.value_names


class SpeakerSelect(Feature, code=0x63, name='speaker select'):
    value_names = {
        0x00: 'Front L/R',
        0x01: 'Side L/R',
        0x02: 'Rear L/R',
        0x03: 'Center/Subwoofer',
    }


class AmbientLightSensor(Feature, code=0x66, name='ambient light sensor'):
    value_names = {
        0x01: 'Disabled',
        0x02: 'Enabled',
    }


class HorizontalFlip(Feature, code=0x82, name='horizontal flip'):
    value_names = {
        0x00: 'Normal mode',
        0x01: 'Mirrored horizontally mode',
    }


class VerticalFlip(Feature, code=0x84, name='vertical flip'):
    value_names = {
        0x00: 'Normal mode',
        0x01: 'Mirrored vertically mode',
    }


class DisplayScaling(Feature, code=0x86, name='display scaling'):
    value_names = {
        0x01: 'No scaling',
        0x02: 'Max image, no aspect ration distortion',
        0x03: 'Max vertical image, no aspect ratio distortion',
        0x04: 'Max horizontal image, no aspect ratio distortion',
        0x05: 'Max vertical image with aspect ratio distortion',
        0x06: 'Max horizontal image with aspect ratio distortion',
        0x07: 'Linear expansion (compression) on horizontal axis',
        0x08: 'Linear expansion (compression) on h and v axes',
        0x09: 'Squeeze mode',
        0x0A: 'Non-linear expansion',
    }


class Sharpness(Feature, code=0x87, name='sharpness'):
    value_names = {
        0x01: 'Filter function 1',
        0x02: 'Filter function 2',
        0x03: 'Filter function 3',
        0x04: 'Filter function 4',
    }


class TvChannel(Feature, code=0x8B, name='tv channel'):
    value_names = {
        0x01: 'Increment channel',
        0x02: 'Decrement channel',
    }


# class ShBlankScreen(Feature, code=0x8D, name='sh blank screen'):  # 2.2
#     value_names = {
#         0x01: 'Blank the screen',
#         0x02: 'Unblank the screen',
#     }


class TvAudioMuteSource(Feature, code=0x8D, name='tv audio mute source'):
    value_names = {
        0x01: 'Mute the audio',
        0x02: 'Unmute the audio',
    }


class AudioStereoMode(Feature, code=0x94, name='audio stereo mode'):
    value_names = {
        0x00: 'Speaker off/Audio not supported',
        0x01: 'Mono',
        0x02: 'Stereo',
        0x03: 'Stereo expanded',
        0x11: 'SRS 2.0',
        0x12: 'SRS 2.1',
        0x13: 'SRS 3.1',
        0x14: 'SRS 4.1',
        0x15: 'SRS 5.1',
        0x16: 'SRS 6.1',
        0x17: 'SRS 7.1',
        0x21: 'Dolby 2.0',
        0x22: 'Dolby 2.1',
        0x23: 'Dolby 3.1',
        0x24: 'Dolby 4.1',
        0x25: 'Dolby 5.1',
        0x26: 'Dolby 6.1',
        0x27: 'Dolby 7.1',
        0x31: 'THX 2.0',
        0x32: 'THX 2.1',
        0x33: 'THX 3.1',
        0x34: 'THX 4.1',
        0x35: 'THX 5.1',
        0x36: 'THX 6.1',
        0x37: 'THX 7.1',
    }


class WindowControl(Feature, code=0x99, name='window control'):
    value_names = {
        0x00: 'No effect',
        0x01: 'Off',
        0x02: 'On',
    }


class AutoSetup3(Feature, code=0xA2, name='auto setup'):
    value_names = {
        0x01: 'Off',
        0x02: 'On',
    }


class WindowSelect(Feature, code=0xA5, name='window select'):
    value_names = {
        0x00: 'Full display image area selected except active windows',
        0x01: 'Window 1 selected',
        0x02: 'Window 2 selected',
        0x03: 'Window 3 selected',
        0x04: 'Window 4 selected',
        0x05: 'Window 5 selected',
        0x06: 'Window 6 selected',
        0x07: 'Window 7 selected',
    }


class ScreenOrientation(Feature, code=0xAA, name='screen orientation'):
    value_names = {
        0x01: '0 degrees',
        0x02: '90 degrees',
        0x03: '180 degrees',
        0x04: '270 degrees',
        0xFF: 'Display cannot supply orientation',
    }


class Settings(Feature, code=0xB0, name='settings'):
    value_names = {
        0x01: 'Store current settings in the monitor',
        0x02: 'Restore factory defaults for current mode',
    }


class FlatPanelSubpixelLayout(Feature, code=0xB2, name='flat panel subpixel layout'):
    value_names = {
        0x00: 'Sub-pixel layout not defined',
        0x01: 'Red/Green/Blue vertical stripe',
        0x02: 'Red/Green/Blue horizontal stripe',
        0x03: 'Blue/Green/Red vertical stripe',
        0x04: 'Blue/Green/Red horizontal stripe',
        0x05: 'Quad pixel, red at top left',
        0x06: 'Quad pixel, red at bottom left',
        0x07: 'Delta (triad)',
        0x08: 'Mosaic',
    }


# class DisplayTechnologyType(Feature, code=0xB6, name='display technology type'):
#     value_names = {
#         0x01: 'CRT (shadow mask)',
#         0x02: 'CRT (aperture grill)',
#         0x03: 'LCD (active matrix)',
#         0x04: 'LCos',
#         0x05: 'Plasma',
#         0x06: 'OLED',
#         0x07: 'EL',
#         0x08: 'Dynamic MEM',
#         0x09: 'Static MEM',
#     }


class V20DisplayTechnologyType(Feature, code=0xB6, name='display technology type'):
    hide_extras = True
    value_names = {
        0x01: 'CRT (shadow mask)',
        0x02: 'CRT (aperture grill)',
        0x03: 'LCD (active matrix)',
        0x04: 'LCos',
        0x05: 'Plasma',
        0x06: 'OLED',
        0x07: 'EL',
        0x08: 'MEM',
    }


class DisplayControllerType(Feature, code=0xC8, name='display controller type'):
    hide_extras = True
    value_names = {
        0x01: 'Conexant',
        0x02: 'Genesis',
        0x03: 'Macronix',
        0x04: 'IDT',
        0x05: 'Mstar',
        0x06: 'Myson',
        0x07: 'Phillips',
        0x08: 'PixelWorks',
        0x09: 'RealTek',
        0x0A: 'Sage',
        0x0B: 'Silicon Image',
        0x0C: 'SmartASIC',
        0x0D: 'STMicroelectronics',
        0x0E: 'Topro',
        0x0F: 'Trumpion',
        0x10: 'Welltrend',
        0x11: 'Samsung',
        0x12: 'Novatek',
        0x13: 'STK',
        0x14: 'Silicon Optics',
        0x15: 'Texas Instruments',
        0x16: 'Analogix',
        0x17: 'Quantum Data',
        0x18: 'NXP Semiconductors',
        0x19: 'Chrontel',
        0x1A: 'Parade Technologies',
        0x1B: 'THine Electronics',
        0x1C: 'Trident',
        0x1D: 'Micros',
        0xFF: 'Not defined - a manufacturer designed controller',
    }


class Osd(Feature, code=0xCA, name='osd'):
    value_names = {
        0x01: 'OSD Disabled',
        0x02: 'OSD Enabled',
        0xFF: 'Display cannot supply this information',
    }


# class V22OsdButtonSh(Feature, code=0xCA, name='v22 osd button sh'):
#     value_names = {
#         0x00: 'Host control of power unsupported',
#         0x01: 'Power button disabled, power button events enabled',
#         0x02: 'Power button enabled, power button events enabled',
#         0x03: 'Power button disabled, power button events disabled',
#     }
#
#
# class V22OsdButtonSl(Feature, code=0xCA, name='v22 osd button sl'):
#     value_names = {
#         0x00: 'Host OSD control unsupported',
#         0x01: 'OSD disabled, button events enabled',
#         0x02: 'OSD enabled, button events enabled',
#         0x03: 'OSD disabled, button events disabled',
#         0xFF: 'Display cannot supply this information',
#     }


class OsdLanguage(Feature, code=0xCC, name='osd language'):
    value_names = {
        0x00: 'Reserved value, must be ignored',
        0x01: 'Chinese (traditional, Hantai)',
        0x02: 'English',
        0x03: 'French',
        0x04: 'German',
        0x05: 'Italian',
        0x06: 'Japanese',
        0x07: 'Korean',
        0x08: 'Portuguese (Portugal)',
        0x09: 'Russian',
        0x0A: 'Spanish',
        0x0B: 'Swedish',
        0x0C: 'Turkish',
        0x0D: 'Chinese (simplified / Kantai)',
        0x0E: 'Portuguese (Brazil)',
        0x0F: 'Arabic',
        0x10: 'Bulgarian ',
        0x11: 'Croatian',
        0x12: 'Czech',
        0x13: 'Danish',
        0x14: 'Dutch',
        0x15: 'Estonian',
        0x16: 'Finnish',
        0x17: 'Greek',
        0x18: 'Hebrew',
        0x19: 'Hindi',
        0x1A: 'Hungarian',
        0x1B: 'Latvian',
        0x1C: 'Lithuanian',
        0x1D: 'Norwegian ',
        0x1E: 'Polish',
        0x1F: 'Romanian ',
        0x20: 'Serbian',
        0x21: 'Slovak',
        0x22: 'Slovenian',
        0x23: 'Thai',
        0x24: 'Ukranian',
        0x25: 'Vietnamese',
    }


class V2OutputSelect(Feature, code=0xD0, name='v2 output select'):
    value_names = {
        0x01: 'Analog video (R/G/B) 1',
        0x02: 'Analog video (R/G/B) 2',
        0x03: 'Digital video (TDMS) 1',
        0x04: 'Digital video (TDMS) 22',
        0x05: 'Composite video 1',
        0x06: 'Composite video 2',
        0x07: 'S-Video-1',
        0x08: 'S-Video-2',
        0x09: 'Tuner-1',
        0x0A: 'Tuner-2',
        0x0B: 'Tuner-3',
        0x0C: 'Component video (YPrPb/YCrCb) 1',
        0x0D: 'Component video (YPrPb/YCrCb) 2',
        0x0E: 'Component video (YPrPb/YCrCb) 3',
        0x0F: 'DisplayPort-1',
        0x10: 'DisplayPort-2',
        0x11: 'HDMI-1',
        0x12: 'HDMI-2',
    }


class PowerMode(Feature, code=0xD6, name='power mode'):
    # DPM: (Could not find info)
    # DPMS = Display Power Management Signaling - https://en.wikipedia.org/wiki/VESA_Display_Power_Management_Signaling
    value_names = {
        0x01: 'DPM: On,  DPMS: Off',
        0x02: 'DPM: Off, DPMS: Standby',
        0x03: 'DPM: Off, DPMS: Suspend',
        0x04: 'DPM: Off, DPMS: Off',
        0x05: 'Write only value to turn off display',
    }


class AuxPowerOutput(Feature, code=0xD7, name='aux power output'):
    value_names = {
        0x01: 'Disable auxiliary power',
        0x02: 'Enable Auxiliary power',
    }


class ScanMode(Feature, code=0xDA, name='scan mode'):
    value_names = {
        0x00: 'Normal operation',
        0x01: 'Underscan',
        0x02: 'Overscan',
    }


class ImageMode(Feature, code=0xDB, name='image mode'):
    value_names = {
        0x00: 'No effect',
        0x01: 'Full mode',
        0x02: 'Zoom mode',
        0x04: 'Variable',
    }


class DisplayApplication(Feature, code=0xDC, name='display application'):
    value_names = {
        0x00: 'Standard/Default mode',
        0x01: 'Productivity',
        0x02: 'Mixed',
        0x03: 'Movie',
        0x04: 'User defined',
        0x05: 'Games',
        0x06: 'Sports',
        0x07: 'Professional (all signal processing disabled)',
        0x08: 'Standard/Default mode with intermediate power consumption',
        0x09: 'Standard/Default mode with low power consumption',
        0x0A: 'Demonstration',
        0xF0: 'Dynamic contrast',
    }


class WoOperationMode(Feature, code=0xDE, name='wo operation mode'):
    value_names = {
        0x01: 'Stand alone',
        0x02: 'Follower (full PC control)',
    }


# endregion

# region Model-Specific Overrides

# TODO: Use a config file to make it easier?

InputSource('CRG9_C49RG9xSS (DP)', {0x06: 'HDMI-1', 0x09: 'DisplayPort-1'})
PowerMode('CRG9_C49RG9xSS (DP)', {0x01: 'On', 0x04: 'Off'})

InputSource('LG FULLHD(HDMI)', {0x01: 'VGA-1', 0x04: 'HDMI-1'})
PowerMode('LG FULLHD(HDMI)', {0x01: 'On', 0x04: 'Off'})

# endregion
