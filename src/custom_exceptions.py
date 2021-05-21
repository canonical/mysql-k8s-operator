#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""
This module has custom exceptions for mysql-operator
Perhaps in the future we can generalise these exceptions to other charms.

Exception: IngressAddressUnavailableError
"""


class MySQLRootPasswordError(Exception):
    """Exception raised when MySQL root is not yet availability"""

    def __init__(self, message="MySQL root password is not available"):
        self.message = message
        super().__init__(self.message)
