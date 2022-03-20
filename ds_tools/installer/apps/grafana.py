"""
App config for Promtail, Tempo, etc

:author: Doug Skrypa
"""

import logging
import platform
from distutils.spawn import find_executable
from pathlib import Path
from shutil import unpack_archive
from subprocess import check_call, check_output, SubprocessError
from tempfile import TemporaryDirectory
from typing import Optional, Iterable

import os

from ..app import Application
from ..app_info import AppInfo
from ..download import get_json, save_file

__all__ = ['Promtail', 'Tempo']
log = logging.getLogger(__name__)


class GrafanaApp(Application):
    name: str

    def __init_subclass__(cls, app_name: str, repo: str):
        cls.name = app_name
        cls.repo = repo

    def __init__(
        self,
        name: str = None,
        user: str = None,
        group: str = None,
        version: str = None,
        bin_path: str = None,
        config_path: str = None,
    ):
        if name:
            self.name = name
        if not bin_path:
            bin_path = f'/usr/local/bin/{self.name}-{{system}}-{{arch}}'
        self.app = AppInfo(
            name=self.name,
            user=user or self.name,
            group=group or self.name,
            bin_path_tmpl=bin_path,
        )
        self.version = version
        self.bin_path = Path(self.app.bin_path)
        self.config_path = Path(config_path or f'/usr/local/etc/{self.name}/{self.name}.yaml')

    def get_installed_version(self) -> Optional[str]:
        if not self.bin_path.exists():
            return None
        try:
            stdout = check_output([self.bin_path.as_posix(), '-version'], text=True)  # type: str
        except (SubprocessError, OSError):
            return None
        else:
            return stdout.splitlines()[0].split('(', 1)[0].partition('version')[-1].strip()

    def get_latest_version(self) -> str:
        gh_api_url = f'https://api.github.com/repos/grafana/{self.repo}/releases'
        return get_json(gh_api_url)[0]['tag_name']

    def download_binary(self):
        version = self.version
        if version is None:
            version = self.get_latest_version()

        current = self.get_installed_version()
        if current and version in (current, f'v{current}'):
            log.info(f'Skipping download - version={version!r} is already installed')
            return

        self.validate_install_dependencies()
        self._download(version)

    def get_download_url_and_file(self, version: str):
        zip_name = self.bin_path.name + '.zip'
        return f'https://github.com/grafana/{self.repo}/releases/download/{version}/{zip_name}', zip_name

    def _download(self, version: str):
        download_url, zip_name = self.get_download_url(version)
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            zip_path = tmp_path.joinpath(zip_name)  # type: Path
            self._save_file(tmp_path, zip_path, download_url, version)
            self._prepare_binaries(zip_path, tmp_path, tmp_dir)
            self._finalize_install(zip_path, tmp_path, tmp_dir)

    def validate_install_dependencies(self):
        return

    def _save_file(self, tmp_path: Path, zip_path: Path, download_url: str, version: str):
        log.info(f'Downloading {self.name} version={version!r}')
        save_file(download_url, ('--location',), save_path=zip_path)

    def _prepare_binaries(self, zip_path: Path, tmp_path: Path, tmp_dir: str):
        log.info(f'Unpacking {zip_path.name}')
        unpack_archive(zip_path.as_posix(), tmp_dir)

    def _finalize_install(self, zip_path: Path, tmp_path: Path, tmp_dir: str):
        tmp_bin_path = next((p for p in tmp_path.iterdir() if p != zip_path))  # type: Path
        if self.bin_path.exists():
            log.info(f'Removing old {self.bin_path.as_posix()}')
            self.bin_path.unlink()

        tmp_bin_path.rename(self.bin_path)
        log.info(f'Created {self.bin_path.as_posix()}')
        self.bin_path.chmod(0o755)

    def prepare_config(self) -> Optional[str]:
        return None

    def create_config_file(self):
        config = self.prepare_config()
        if config is None:
            log.debug(f'No config for {self.name}')
            return

        if not self.config_path.parent.exists():
            self.config_path.parent.mkdir(parents=True)

        log.info(f'Writing config to {self.config_path.as_posix()}')
        self.config_path.write_text(config, encoding='utf-8')
        self.config_path.chmod(0o644)


class Promtail(GrafanaApp, app_name='promtail', repo='loki'):
    def __init__(
        self,
        name: str = None,
        user: str = None,
        group: str = None,
        version: str = None,
        bin_path: str = None,
        http_port: int = 9080,
        grpc_port: int = 0,
        pos_path: str = '/tmp/positions.yaml',
        loki_scheme: str = 'http',
        loki_netloc: str = 'localhost:3100',
        config_path: str = None,
        logs: Iterable[str] = None,
    ):
        super().__init__(
            name=name,
            user=user,
            group=group,
            version=version,
            bin_path=bin_path,
            config_path=config_path,
        )
        self.http_port = http_port
        self.grpc_port = grpc_port
        self.pos_path = pos_path
        self.loki_scheme = loki_scheme
        self.loki_netloc = loki_netloc
        self.app.cmd_args = f'-config.file {self.config_path}'
        if logs:
            log_configs = {}
            for entry in logs:
                try:
                    job, path_pattern = entry.split(':', 1)
                except ValueError as e:
                    raise ValueError(f'Invalid --logs entry={entry!r} - expected JOB:PATH_PATTERN') from e
                else:
                    log_configs[job] = path_pattern
            self.log_configs = log_configs
        else:
            self.log_configs = None

    def prepare_config(self) -> str:
        config = f"""
server:
  http_listen_port: {self.http_port}
  grpc_listen_port: {self.grpc_port}
positions:
  filename: {self.pos_path}
clients:
  - url: {self.loki_scheme}://{self.loki_netloc}/loki/api/v1/push
""".lstrip()
        if self.log_configs:
            parts = [config, 'scrape_configs:', '- job_name: local_logs', '  static_configs:']
            for job, path_pattern in self.log_configs.items():
                parts.append(f'  - labels: {{job: {job!r}, __path__: {path_pattern!r}}}\n')
            config = '\n'.join(parts)
        else:
            config += (
                '#scrape_configs:\n'
                '#- job_name: example\n'
                '#  static_configs:\n'
                '#  - labels: {{job: example, __path__: /var/log/*log}}\n'
            )

        return config


EXAMPLE_PROMTAIL_CONFIG = r"""
server:
  http_listen_port: 9080
  grpc_listen_port: 0
positions:
  filename: /tmp/positions.yaml
clients:
  - url: http://192.168.0.194:3100/loki/api/v1/push

scrape_configs:
- job_name: local_logs
  static_configs:
  - labels: {job: 'temp_sensor', __path__: '/var/tmp/root/temp_sensor_logs/*.log'}
  pipeline_stages:
  - regex: {expression: '^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.\d{6} \S+) (?P<level>\S+) (?P<pid>\d+) (?P<thread>\S+) (?P<module>\S+) (?P<line>\d+) \[(?P<uid>.+?)\] (?P<message>.*)'}
  - timestamp: {source: time, format: '2006-01-02 15:04:05.000000 MST'}
  - labels:
      time:
      level:
      pid:
      thread:
      module:
      line:
      uid:
"""


class Loki(GrafanaApp, app_name='loki', repo='loki'):
    pass


class Tempo(GrafanaApp, app_name='tempo', repo='tempo'):
    def __init__(
        self,
        name: str = None,
        user: str = None,
        group: str = None,
        version: str = None,
        bin_path: str = None,
        config_path: str = None,
        http_port: int = 3200,
    ):
        super().__init__(
            name=name,
            user=user,
            group=group,
            version=version,
            bin_path=bin_path,
            config_path=config_path,
        )
        self.http_port = http_port
        self.app.cmd_args = f'-config.file {self.config_path}'

    def validate_install_dependencies(self):
        bsd = platform.system().lower() == 'freebsd'
        pkgs = ('git', 'go', 'gmake') if bsd else ('git', 'go')
        missing = [pkg for pkg in pkgs if find_executable(pkg) is None]
        if missing:
            cmd = 'pkg' if bsd else 'apt'
            pkg_str = ' '.join(missing)
            raise RuntimeError(f'Missing dependencies - please run `{cmd} install {pkg_str}`')

    def _save_file(self, tmp_path: Path, zip_path: Path, download_url: str, version: str):
        log.info(f'Cloning the git repo for {self.name}')
        os.chdir(tmp_path)
        check_call(['git', 'clone', 'https://github.com/grafana/tempo.git'])

    def _prepare_binaries(self, zip_path: Path, tmp_path: Path, tmp_dir: str):
        os.chdir(tmp_path.joinpath('tempo'))
        bsd = platform.system().lower() == 'freebsd'
        log.info(f'Compiling {self.name}')
        check_call(['gmake' if bsd else 'make', 'tempo'])

    def _finalize_install(self, zip_path: Path, tmp_path: Path, tmp_dir: str):
        bin_dir = next(tmp_path.joinpath('tempo', 'bin').iterdir())
        tmp_bin_path = next(bin_dir.iterdir())
        if self.bin_path.exists():
            log.info(f'Removing old {self.bin_path.as_posix()}')
            self.bin_path.unlink()

        tmp_bin_path.rename(self.bin_path)
        log.info(f'Created {self.bin_path.as_posix()}')
        self.bin_path.chmod(0o755)

    def prepare_config(self) -> str:
        """
        The config for Tempo.  Example mostly copied from:
        https://github.com/grafana/tempo/blob/main/example/docker-compose/local/tempo-local.yaml
        """
        config = f"""
server:
  http_listen_port: {self.http_port}
distributor:
  receivers:                           # This config will listen on all ports and protocols that tempo is capable of.
    jaeger:                            # The receives all come from the OpenTelemetry collector. More config info can be
      protocols:                       # found here:
        thrift_http:                   # https://github.com/open-telemetry/opentelemetry-collector/tree/main/receiver
        grpc:                          #
        thrift_binary:                 # For a production deployment you should only enable the receivers you need!
        thrift_compact:
    zipkin:
    otlp:
      protocols:
        http:
        grpc:
    opencensus:
ingester:
  trace_idle_period: 10s               # Time after a trace has not received spans to consider it complete and flush it
  max_block_bytes: 1_000_000           # Cut the head block when it hits this size or ...
  max_block_duration: 5m               #   this much time passes
compactor:
  compaction:
    compaction_window: 1h              # Blocks in this time window will be compacted together
    max_block_bytes: 100_000_000       # Maximum size of compacted blocks
    block_retention: 1h
    compacted_block_retention: 10m
storage:                               # Encoding/compression opts: none, gzip, lz4-[64k|256k|1M], lz4, snappy, zstd, s2
  trace:
    backend: local                     # Backend configuration to use
    block:
      bloom_filter_false_positive: .05 # Bloom filter false positive rate. Lower->larger filters, fewer false positives
      index_downsample_bytes: 1000     # Number of bytes per index record
      encoding: zstd                   # Block encoding/compression.
    wal:
      path: /tmp/tempo/wal             # Where to store the the wal locally
      encoding: snappy                 # Wal encoding/compression.
    local:
      path: /tmp/tempo/blocks
    pool:
      max_workers: 100                 # Worker pool determines the num of parallel requests to the object store backend
      queue_depth: 10000
""".lstrip()
        return config


class Grafana(GrafanaApp, app_name='grafana', repo='grafana'):  # Source only
    pass
