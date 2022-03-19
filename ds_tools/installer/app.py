"""
Base app template

:author: Doug Skrypa
"""

from abc import ABC

from .app_info import AppInfo
from .services import Service


class Application(ABC):
    app: AppInfo

    def download_and_install(self):
        service = Service(self.app)
        service.env_user_check()
        service.ensure_user_exists()
        service.ensure_user_is_in_group()
        self.download_binary()
        self.create_config_file()
        service.write_service_config()
        service.enable_and_start()

    def download_binary(self):
        pass

    def create_config_file(self):
        pass
