"""
Convert DDCA_Feature_Value_Entry code to the format used in :mod:`ds_tools.ddc.features`

:author: Doug Skrypa
"""

import re
from pathlib import Path


def parse_features() -> dict[tuple[int, str], dict[int, str]]:
    content = Path(__file__).resolve().parent.joinpath('vcp_feature_codes.c').read_text('utf-8').splitlines()

    start_match = re.compile(r'(?:static)?\s*DDCA_Feature_Value_Entry\s+x([\da-fA-F]{2})_(\w+)_values\[').match
    entry_search = re.compile(r'{\s*0x([\da-fA-F]{2}),\s*"([^"]+)"\s*}').search

    features = {}
    feat_key = None
    for line in content:
        if m := start_match(line):
            code, name = m.groups()  # code, name
            feat_key = (int(code, 16), name)
            features[feat_key] = {}
        elif feat_key and (m := entry_search(line)):
            key, val = m.groups()
            features[feat_key][int(key, 16)] = val
        elif feat_key and line.startswith('};'):
            feat_key = None

    return features


def write_feature_classes(features: dict[tuple[int, str], dict[int, str]]):
    classes = []
    for (code, name), values in sorted(features.items()):
        split_name = name.replace('_', ' ')
        cls_name = split_name.title().replace(' ', '')
        value_lines = '\n'.join(f"        0x{key:02X}: '{val}'," for key, val in values.items())
        classes.append(
            f"class {cls_name}(Feature, code=0x{code:02X}, name='{split_name}'):\n"
            f'    value_names = {{\n{value_lines}\n    }}\n'
        )

    path = Path(__file__).resolve().parent.joinpath('vcp_converted_features.py')
    with path.open('w', encoding='utf-8', newline='\n') as f:
        f.write('\n\n'.join(classes))


if __name__ == '__main__':
    features = parse_features()
    print(f'Parsed {len(features)} features')
    write_feature_classes(features)
