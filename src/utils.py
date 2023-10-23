# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A collection of utility functions that are used in the charm."""

import hashlib
import re
import secrets
import string


def generate_random_password(length: int) -> str:
    """Randomly generate a string intended to be used as a password.

    Args:
        length: length of the randomly generated string to be returned
    Returns:
        A randomly generated string intended to be used as a password.
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for _ in range(length)])


def generate_random_hash() -> str:
    """Generate a hash based on a random string.

    Returns:
        A hash based on a random string.
    """
    random_characters = generate_random_password(10)
    return hashlib.md5(random_characters.encode("utf-8")).hexdigest()


def split_mem(mem_str) -> tuple:
    """Split a memory string into a number and a unit.

    Args:
        mem_str: a string representing a memory value, e.g. "1Gi"
    """
    pattern = r"^(\d+)(\w+)$"
    parts = re.match(pattern, mem_str)
    if parts:
        return parts.groups()
    return None, "No unit found"


def any_memory_to_bytes(mem_str) -> int:
    """Convert a memory string to bytes.

    Args:
        mem_str: a string representing a memory value, e.g. "1Gi"
    """
    units = {
        "KI": 1024,
        "K": 10**3,
        "MI": 1048576,
        "M": 10**6,
        "GI": 1073741824,
        "G": 10**9,
        "TI": 1099511627776,
        "T": 10**12,
    }
    try:
        num = int(mem_str)
        return num
    except ValueError:
        memory, unit = split_mem(mem_str)
        unit = unit.upper()
        if unit not in units:
            raise ValueError(f"Invalid memory definition in '{mem_str}'")

        num = int(memory)
        return int(num * units[unit])


def compare_dictionaries(dict1: dict, dict2: dict) -> set:
    """Compare two dictionaries and return a set of keys that are different."""
    different_keys = set()

    # exiting keys with different values
    for key in dict1.keys():
        if key in dict2 and dict1[key] != dict2[key]:
            different_keys.add(key)

    # non existent keys
    different_keys = different_keys | dict2.keys() ^ dict1.keys()

    return different_keys
