#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the MySQL charm."""
import configparser
import logging
import re
from typing import Optional

from charms.data_platform_libs.v0.data_models import BaseConfigModel
from pydantic import validator

logger = logging.getLogger(__name__)


class MySQLConfig:
    """Configuration."""

    # Static config requires workload restart
    static_config = {
        "innodb_buffer_pool_size",
        "innodb_buffer_pool_chunk_size",
        "group_replication_message_cache_size",
        "log_error",
    }

    def keys_requires_restart(self, keys: set) -> bool:
        """Check if keys require restart."""
        return bool(keys & self.static_config)

    def filter_static_keys(self, keys: set) -> set:
        """Filter static keys."""
        return keys - self.static_config

    @staticmethod
    def custom_config(config_content: str) -> dict:
        """Convert config content to dict."""
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(config_content)

        return dict(cp["mysqld"])


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    profile: str
    cluster_name: Optional[str]
    cluster_set_name: Optional[str]
    profile_limit_memory: Optional[int]
    mysql_interface_user: Optional[str]
    mysql_interface_database: Optional[str]
    mysql_root_interface_user: Optional[str]
    mysql_root_interface_database: Optional[str]

    @validator("profile")
    @classmethod
    def profile_values(cls, value: str) -> Optional[str]:
        """Check profile config option is one of `testing` or `production`."""
        if value not in ["testing", "production"]:
            raise ValueError("Value not one of 'testing' or 'production'")

        return value

    @validator("cluster_name", "cluster_set_name")
    @classmethod
    def cluster_name_validator(cls, value: str) -> Optional[str]:
        """Check for valid cluster, cluster-set name.

        Limited to 63 characters, and must start with a letter and
        contain only alphanumeric characters, `-`, `_` and `.`
        """
        if len(value) > 63:
            raise ValueError("cluster, cluster-set name must be less than 63 characters")

        if not value[0].isalpha():
            raise ValueError("cluster, cluster-set name must start with a letter")

        if not re.match(r"^[a-zA-Z0-9-_.]*$", value):
            raise ValueError(
                "cluster, cluster-set name must contain only alphanumeric characters, "
                "hyphens, underscores and periods"
            )

        return value

    @validator("profile_limit_memory")
    @classmethod
    def profile_limit_memory_validator(cls, value: int) -> Optional[int]:
        """Check profile limit memory."""
        if value < 600:
            raise ValueError("MySQL Charm requires at least 600MB for bootstrapping")
        if value > 9999999:
            raise ValueError("`profile-limit-memory` limited to 7 digits (9999999MB)")

        return value

    @validator("mysql_interface_user", "mysql_root_interface_user")
    @classmethod
    def user_name_validator(cls, value: str) -> Optional[str]:
        """Check user name is valid."""
        if len(value) > 32:
            raise ValueError("User name constrained to 32 characters")

        return value

    @validator("mysql_interface_database", "mysql_root_interface_database")
    @classmethod
    def database_name_validator(cls, value: str) -> Optional[str]:
        """Check database name is valid."""
        if not re.match(r"^[^\\\/?%*:|\"<>.]{1,64}$", value):
            raise ValueError(
                "Database name cannot contain slashes, dots or characters not"
                " allowed for directories, and are limited to 64 characters"
            )

        return value
