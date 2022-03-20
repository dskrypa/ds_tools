#!/usr/bin/env python3.8

import logging
import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.installer.apps.grafana import Promtail, Tempo


def parser():
    parser = ArgParser(description='Install Grafana-related apps')

    with parser.add_subparser('app', 'promtail') as promtail_parser:
        app = 'promtail'
        promtail_parser.add_argument('--name', '-n', default=app, help='The name of the service to create')
        promtail_parser.add_argument('--user', '-u', default=app, help=f'The user that should be configured to run {app}')
        promtail_parser.add_argument('--group', '-g', default=app, help='The group that the specified user should be added to')
        promtail_parser.add_argument('--install_path', '-i', help=f'The path to install the {app} binary')
        promtail_parser.add_argument('--config_path', '-c', help=f'The path to install the {app} config file')
        promtail_parser.add_argument('--version', '-V', help=f'The version of {app} to install (default: latest)')

        cfg_group = promtail_parser.add_argument_group('Promtail Config')
        cfg_group.add_argument('--http_port', '-p', type=int, default=9080, help='Promtail server listen port')
        cfg_group.add_argument('--grpc_port', type=int, default=0, help='Promtail GRPC listen port')
        cfg_group.add_argument('--pos_path', default='/tmp/positions.yaml', help='Path to store log tail positions')
        cfg_group.add_argument('--loki_scheme', default='http', choices=('http', 'https'), help='Scheme for Loki push client')
        cfg_group.add_argument('--loki_netloc', '-L', default='localhost:3100', help='Host and port for Loki push client')

        log_group = promtail_parser.add_argument_group('Log Scrape Config')
        log_group.add_argument('--logs', metavar='JOB:PATH_PATTERN', nargs='+', help='One or more paths to monitor')

    with parser.add_subparser('app', 'tempo') as tempo_parser:
        app = 'tempo'
        tempo_parser.add_argument('--name', '-n', default=app, help='The name of the service to create')
        tempo_parser.add_argument('--user', '-u', default=app, help=f'The user that should be configured to run {app}')
        tempo_parser.add_argument('--group', '-g', default=app, help='The group that the specified user should be added to')
        tempo_parser.add_argument('--install_path', '-i', help=f'The path to install the {app} binary')
        tempo_parser.add_argument('--config_path', '-c', help=f'The path to install the {app} config file')
        # tempo_parser.add_argument('--version', '-V', help=f'The version of {app} to install (default: latest)')

        cfg_group = tempo_parser.add_argument_group('Tempo Config')
        cfg_group.add_argument('--http_port', '-p', type=int, default=3200, help='Tempo server listen port')

    parser.include_common_args('verbose')
    return parser


def main():
    args = parser().parse_args()
    log_fmt = '%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s' if args.verbose > 1 else '%(message)s'
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format=log_fmt)

    if args.app == 'promtail':
        app = Promtail(
            name=args.name,
            user=args.user,
            group=args.group,
            bin_path=args.install_path,
            http_port=args.http_port,
            grpc_port=args.grpc_port,
            pos_path=args.pos_path,
            loki_scheme=args.loki_scheme,
            loki_netloc=args.loki_netloc,
            config_path=args.config_path,
            logs=args.logs,
        )
    elif args.app == 'tempo':
        app = Tempo(
            name=args.name,
            user=args.user,
            group=args.group,
            bin_path=args.install_path,
            config_path=args.config_path,
            http_port=args.http_port,
        )
    else:
        raise ValueError(f'Unexpected app={args.app!r}')

    app.download_and_install()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
