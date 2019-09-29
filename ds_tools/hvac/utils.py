"""
Library for interacting with the Nest thermostat via the cloud API

:author: Doug Skrypa
"""

import logging


__all__ = ['celsius_to_fahrenheit', 'fahrenheit_to_celsius']
log = logging.getLogger(__name__)


def celsius_to_fahrenheit(deg_c):
    return (deg_c * 9 / 5) + 32


def fahrenheit_to_celsius(deg_f):
    return (deg_f - 32) * 5 / 9
