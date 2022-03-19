"""
App config for Promtail

:author: Doug Skrypa
"""

from pathlib import Path
from shutil import unpack_archive
from subprocess import check_output, SubprocessError
from tempfile import TemporaryDirectory
from typing import Optional, Iterable

from ..app import Application
from ..app_info import AppInfo
from ..download import get_json, save_file


class GrafanaApp(Application):
    name: str

    def __init_subclass__(cls, app_name: str, repo: str):
        cls.name = app_name
        cls.repo = repo

    def __init__(
        self, name: str = None, user: str = None, group: str = None, version: str = None, bin_path: str = None
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
            print(f'Skipping download - version={version!r} is already installed')
            return

        self._download(version)

    def _download(self, version: str):
        zip_name = self.bin_path.name + '.zip'
        download_url = f'https://github.com/grafana/{self.repo}/releases/download/{version}/{zip_name}'

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            zip_path = tmp_path.joinpath(zip_name)  # type: Path

            print(f'Downloading {self.name} version={version!r}')
            save_file(download_url, ('--location',), save_path=zip_path)

            print(f'Unpacking {zip_path.name}')
            unpack_archive(zip_path.as_posix(), tmp_dir)

            tmp_bin_path = next((p for p in tmp_path.iterdir() if p != zip_path))  # type: Path
            if self.bin_path.exists():
                print(f'Removing old {self.bin_path.as_posix()}')
                self.bin_path.unlink()

            tmp_bin_path.rename(self.bin_path)
            print(f'Created {self.bin_path.as_posix()}')
            self.bin_path.chmod(0o755)


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
        super().__init__(name=name, user=user, group=group, version=version, bin_path=bin_path)
        self.http_port = http_port
        self.grpc_port = grpc_port
        self.pos_path = pos_path
        self.loki_scheme = loki_scheme
        self.loki_netloc = loki_netloc
        self.config_path = config_path or f'/usr/local/etc/{self.name}/{self.name}.yaml'
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

    def create_config_file(self):
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
                parts.append(f'  - labels: {{job: {job!r}, __path__: {path_pattern!r}}}')
            config = '\n'.join(parts)
        else:
            config += (
                '#scrape_configs:\n'
                '#- job_name: example\n'
                '#  static_configs:\n'
                '#  - labels: {{job: example, __path__: /var/log/*log}}\n'
            )

        path = Path(self.config_path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True)

        print(f'Writing config to {path.as_posix()}')
        path.write_text(config, encoding='utf-8')
        path.chmod(0o644)


class Loki(GrafanaApp, app_name='loki', repo='loki'):
    pass


class Grafana(GrafanaApp, app_name='grafana', repo='grafana'):  # Source only
    pass
