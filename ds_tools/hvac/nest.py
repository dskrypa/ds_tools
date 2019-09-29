"""
Library for interacting with the Nest thermostat via the cloud API

:author: Doug Skrypa
"""

import logging
import time
from collections import defaultdict
from configparser import ConfigParser
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

try:
    import keyring
except ImportError:
    keyring = None

from ..core import datetime_with_tz, now, localize, format_duration, get_input
from ..http import RestClient
from .utils import celsius_to_fahrenheit as c2f, fahrenheit_to_celsius as f2c

__all__ = ['NestWebClient']
log = logging.getLogger(__name__)


class NestWebClient(RestClient):
    def __init__(self, email=None, serial=None, no_store_prompt=False, update_password=False):
        """
        :param str email: The email address to be used for login
        :param str serial: The serial number of the thermostat to be managed by this client
        :param bool no_store_prompt: Do not prompt to store the password securely
        :param bool update_password: Prompt to update the stored password, even if one already exists
        """
        super().__init__('home.nest.com', proto='https')
        if email is None or serial is None:
            cfg_path = Path('~/.config/nest.cfg').expanduser()
            if cfg_path.exists():
                config = ConfigParser()
                with cfg_path.open('r', encoding='utf-8') as f:
                    config.read_file(f)
                email = email or config['credentials'].get('email')
                serial = serial or config['device'].get('serial')
        if email is None:
            raise ValueError('An email address associated with a Nest account is required')
        if keyring is not None:
            password = keyring.get_password(type(self).__name__, email)
            if update_password and password:
                keyring.delete_password(type(self).__name__, email)
                password = None
            if password is None:
                password = getpass()
                if not no_store_prompt and get_input('Store password in keyring (https://pypi.org/project/keyring/)?'):
                    keyring.set_password(type(self).__name__, email, password)
                    log.info('Stored password in keyring')
            else:
                log.debug('Using password from keyring')
        else:
            password = getpass()

        self.__password = password
        self._lock = RLock()
        self._email = email
        self._session_info = None
        self._session_expiry = None
        self._userid = None
        self._nest_host_port = ('home.nest.com', None)
        self._transport_host_port = None
        self.serial = serial

    def _init_session(self):
        with self._lock:
            if self._session_info is None or self._session_expiry < now(as_datetime=True):
                log.debug('Initializing session for email={!r}'.format(self._email))
                resp = self.post('session', json={'email': self._email, 'password': self.__password})
                self._session_info = info = resp.json()
                self._userid = info['userid']
                self.session.headers['Authorization'] = 'Basic {}'.format(info['access_token'])
                self.session.headers['X-nl-user-id'] = self._userid
                self._session_expiry = expiry = datetime_with_tz(info['expires_in'], '%a, %d-%b-%Y %H:%M:%S %Z')
                log.debug('Session for user={!r} initialized; expiry: {}'.format(self._userid, localize(expiry)))
                transport_url = urlparse(info['urls']['transport_url'])
                self._transport_host_port = (transport_url.hostname, transport_url.port)

    @contextmanager
    def transport_url(self):
        with self._lock:
            self._init_session()
            try:
                log.debug('Updating host & port to {}:{}'.format(*self._transport_host_port))
                self.host, self.port = self._transport_host_port
                yield self
            finally:
                pass

    @contextmanager
    def nest_url(self):
        with self._lock:
            self._init_session()
            try:
                log.debug('Updating host & port to {}:{}'.format(*self._nest_host_port))
                self.host, self.port = self._nest_host_port
                yield self
            finally:
                pass

    def app_launch(self, bucket_types=None):
        """
        Interesting info by section::\n
            {
                '{serial}': {
                    'shared': {
                        "target_temperature_type": "cool",
                        "target_temperature_high": 24.0, "target_temperature_low": 20.0,
                        "current_temperature": 20.84, "target_temperature": 22.59464,
                    },
                    'device': {
                        "current_humidity": 51, "backplate_temperature": 20.84, "fan_current_speed": "off",
                        "target_humidity": 35.0, "current_schedule_mode": "COOL", "leaf_threshold_cool": 23.55441,
                        "weave_device_id": "...", "backplate_serial_number": "...", "serial_number": "...",
                        "local_ip": "...", "mac_address": "...", "postal_code": "...",
                    },
                    'schedule': {
                        "ver": 2, "schedule_mode": "COOL", "name": "Current Schedule",
                        "days": {
                            "4": {
                                "4": {
                                    "touched_by": 4, "temp": 22.9444, "touched_tzo": -14400,
                                    "touched_user_id": "user....", "touched_at": 1501809124, "time": 18900,
                                    "type": "COOL", "entry_type": "setpoint"
                                }, ...
                            }, ...
            }}}}

        :param list bucket_types: The bucket_types to retrieve (such as device, shared, schedule, etc.)
        :return dict: Mapping of {serial:{bucket_type:{bucket['value']}}}
        """
        bucket_types = bucket_types or ['device', 'shared', 'schedule']
        with self.nest_url():
            payload = {'known_bucket_types': bucket_types, 'known_bucket_versions': []}
            resp = self.post('api/0.1/user/{}/app_launch'.format(self._userid), json=payload)

        info = defaultdict(dict)
        for bucket in resp.json()['updated_buckets']:
            bucket_type, serial = bucket['object_key'].split('.')
            info[serial][bucket_type] = bucket['value']
        return info

    def get_state(self, serial=None):
        serial = self._validate_serial(serial)
        resp = self.app_launch(['device', 'shared'])
        info = resp[serial]
        temps = {
            'shared': (
                'target_temperature_high', 'target_temperature_low', 'target_temperature', 'current_temperature'
            ),
            'device': ('backplate_temperature', 'leaf_threshold_cool')
        }
        non_temps = {
            'shared': ('target_temperature_type',),
            'device': ('current_humidity', 'fan_current_speed', 'target_humidity', 'current_schedule_mode')
        }
        state = {}
        for section, keys in temps.items():
            for key in keys:
                state[key] = c2f(info[section][key])
        for section, keys in non_temps.items():
            for key in keys:
                state[key] = info[section][key]

        return state

    def get_mobile_info(self):
        with self.transport_url():
            return self.get('v2/mobile/user.{}'.format(self._userid)).json()

    def _validate_serial(self, serial):
        serial = serial or self.serial
        if not serial:
            raise ValueError('A Nest thermostat serial number must be provided as a param or set for the client object')
        return serial

    def _put_value(self, serial, value):
        serial = self._validate_serial(serial)
        with self.transport_url():
            payload = {'objects': [{'object_key': f'shared.{serial}', 'op': 'MERGE', 'value': value}]}
            return self.post('v5/put', json=payload)

    def set_temp_range(self, low, high, serial=None, unit='f'):
        """
        :param float low: Minimum temperature to maintain in Celsius (heat will turn on if the temp drops below this)
        :param float high: Maximum temperature to allow in Celsius (air conditioning will turn on above this)
        :param str serial: A Nest thermostat serial number
        :param str unit: Either 'f' or 'c' for fahrenheit/celsius
        :return: The parsed response
        """
        unit = unit.lower()
        if unit[0] == 'f':
            low = f2c(low)
            high = f2c(high)
        elif unit[0] != 'c':
            raise ValueError('Unit must be either \'f\' or \'c\' for fahrenheit/celsius')
        resp = self._put_value(serial, {'target_temperature_low': low, 'target_temperature_high': high})
        return resp.json()

    def set_temp(self, temp, serial=None, unit='f'):
        """
        :param float temp: The target temperature to maintain in Celsius
        :param str serial: A Nest thermostat serial number
        :param str unit: Either 'f' or 'c' for fahrenheit/celsius
        :return: The parsed response
        """
        unit = unit.lower()
        if unit[0] == 'f':
            temp = f2c(temp)
        elif unit[0] != 'c':
            raise ValueError('Unit must be either \'f\' or \'c\' for fahrenheit/celsius')
        resp = self._put_value(serial, {'target_temperature': temp})
        return resp.json()

    def set_mode(self, mode, serial=None):
        """
        :param str mode: One of 'cool', 'heat', 'range', or 'off'
        :param str serial: A Nest thermostat serial number
        :return: The parsed response
        """
        mode = mode.lower()
        if mode not in ('cool', 'heat', 'range', 'off'):
            raise ValueError(f'Invalid mode: {mode!r}')
        resp = self._put_value(serial, {'target_temperature_type': mode})
        return resp.json()

    def start_fan(self, duration, serial=None):
        """
        :param int duration: Number of seconds for which the fan should run
        :param str serial: A Nest thermostat serial number
        :return: The parsed response
        """
        timeout = int(time.time()) + duration
        fmt = 'Submitting fan start request with duration={} => end time of {}'
        log.debug(fmt.format(format_duration(duration), timeout))
        resp = self._put_value(serial, {'fan_timer_timeout': timeout})
        return resp.json()

    def stop_fan(self, serial=None):
        """
        :param str serial: A Nest thermostat serial number
        :return: The parsed response
        """
        resp = self._put_value(serial, {'fan_timer_timeout': 0})
        return resp.json()

    def get_energy_usage_history(self, serial=None):
        """
        Response example::
            {
                "objects": [{
                    "object_revision": 1, "object_timestamp": 1, "object_key": "energy_latest.{serial}",
                    "value": {
                        "recent_max_used": 39840,
                        "days": [{
                            "day": "2019-09-19", "device_timezone_offset": -14400, "total_heating_time": 0,
                            "total_cooling_time": 25860, "total_fan_cooling_time": 2910,
                            "total_humidifier_time": 0, "total_dehumidifier_time": 0,
                            "leafs": 0, "whodunit": -1, "recent_avg_used": 32060, "usage_over_avg": -6200,
                            "cycles": [{"start": 0, "duration": 3180, "type": 65792},...],
                            "events": [{
                                "start": 0, "end": 899, "type": 1, "touched_by": 4, "touched_when": 1557106673,
                                "touched_timezone_offset": -14400, "touched_where": 1, "touched_id": "...@gmail.com",
                                "cool_temp": 20.333, "event_touched_by": 0, "continuation": true
                            },...],
                            "rates": [], "system_capabilities": 2817, "incomplete_fields": 0
                        }, ...]
                    }
                }]
            }

        :param str serial: A Nest thermostat serial number
        :return: The parsed response
        """
        serial = self._validate_serial(serial)
        with self.transport_url():
            payload = {'objects': [{'object_key': f'energy_latest.{serial}'}]}
            resp = self.post('v5/subscribe', json=payload)
            return resp.json()

    def get_weather(self, zip_code, country_code):
        """
        Get the weather forecast.  Response format::
            {
              "display_city":"...", "city":"...",
              "forecast":{
                "hourly":[{"time":1569769200, "temp":74.0, "humidity":55},...],
                "daily":[{
                  "conditions":"Partly Cloudy", "date":1569729600, "high_temperature":77.0, "icon":"partlycloudy",
                  "low_temperature":60.0
                },...]
              },
              "now":{
                "station_id":"unknown", "conditions":"Mostly Cloudy", "current_humidity":60, "current_temperature":22.8,
                "current_wind":12, "gmt_offset":"-04.00", "icon":"mostlycloudy", "sunrise":1569754260,
                "sunset":1569796920, "wind_direction":"N"
              }
            }

        :param int|str zip_code: A 5-digit zip code
        :param str country_code: A 2-letter country code (such as 'US')
        :return dict: The parsed response
        """
        with self.nest_url():
            resp = self.get('api/0.1/weather/forecast/{},{}'.format(zip_code, country_code))
            return resp.json()
