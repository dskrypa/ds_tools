"""
Utilities for generating documentation from argparse.ArgumentParser objects

:author: Doug Skrypa
"""

from collections import defaultdict, OrderedDict

__all__ = ['help_as_rst']


def help_as_rst(parser, description=True, epilog=True, as_list=False):
    i = ' ' * 3
    lines = []
    if parser.description and description:
        lines += [parser.description, '']

    formatter = parser._get_formatter()
    usage = formatter._format_usage(parser.usage, parser._actions, parser._mutually_exclusive_groups, None)
    lines += ['::\n']
    lines += [i + line for line in usage.splitlines()]

    for action_group in parser._action_groups:
        if not action_group._group_actions:
            continue
        desc = action_group.description
        title = action_group.title[0].upper() + action_group.title[1:]
        lines += ['', '{}{}'.format(title, (': ' + desc) if desc else ''), '', '.. list-table::']
        agi = ' ' * 3
        actions = []
        for action in action_group._group_actions:
            positional = not any(a.startswith('-') for a in action.option_strings)
            if action.help != '==SUPPRESS==':
                if action.option_strings:
                    if action.nargs == 0:
                        meta = None
                    elif action.metavar is not None:
                        meta = action.metavar
                    else:
                        meta = action.dest

                    opts = ('{} {}'.format(opt, meta) if meta else opt for opt in sorted(action.option_strings))
                    act_options = ', '.join('``{}``'.format(opt) for opt in opts)
                else:
                    act_options = action.dest

                act_help = _interpolated_help(parser, action)
                if (not positional) and action.required and ('required' not in act_help.lower()):
                    act_help += ' (required)'
                act_choices = ', '.join(sorted(str(choice) for choice in action.choices)) if action.choices else ''
                actions.append((act_options, act_help, act_choices))

        if actions:
            opts_width = max(len(action[0]) for action in actions)
            desc_width = max(len(action[i]) for i in (1, 2) for action in actions) + 20
            lines += [agi + ':widths: {} {}'.format(opts_width, desc_width), '']

            for act_options, act_help, act_choices in actions:
                lines += [agi + '* - | {}'.format(act_options)]
                if act_help:
                    lines += [agi + '  - | {}'.format(act_help)]
                if act_choices:
                    fmt = '  - | Choices: {}' if not act_help else '    | Choices: {}'
                    lines += [agi + fmt.format(act_choices)]
                if not (act_help or act_choices):
                    lines += [agi + '  - | ']

    subparsers = get_subparsers(parser)
    if subparsers:
        lines += ['', 'Sub-Commands', '=' * 12, '']
        for sp_dest, sp in subparsers.items():
            sp_unique = OrderedDict()
            aliases = defaultdict(set)
            for choice_name, sp_choice in sp.choices.items():
                primary = sp_choice.prog.split()[-1]
                if primary != choice_name:
                    aliases[primary].add(choice_name)
                else:
                    sp_unique[choice_name] = sp_choice

            for choice_name, sp_choice in sp_unique.items():
                sp_aliases = sorted(aliases[choice_name])
                if sp_aliases:
                    choice_name = '{} / {}'.format(choice_name, ' / '.join(sp_aliases))
                sp_title = '{}: {}'.format(sp_dest, choice_name)
                lines += ['', sp_title, '-' * len(sp_title), '']
                lines += help_as_rst(sp_choice, True, False, True)

    if parser.epilog and epilog:
        lines += ['', parser.epilog]
    return lines if as_list else '\n'.join(lines)


def get_subparsers(parser):
    try:
        return {sp.dest: sp for sp in parser._subparsers._group_actions}
    except AttributeError:
        return {}


def _interpolated_help(parser, action):
    if not action.help:
        return ''
    params = dict(vars(action), prog=parser.prog)
    for name in list(params):
        if params[name] == '==SUPPRESS==':
            del params[name]
    for name in list(params):
        if hasattr(params[name], '__name__'):
            params[name] = params[name].__name__
    if params.get('choices') is not None:
        choices_str = ', '.join([str(c) for c in params['choices']])
        params['choices'] = choices_str
    help_text = action.help % params
    return help_text[0].upper() + help_text[1:]
