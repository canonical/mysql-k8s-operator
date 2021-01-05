"""Kubernetes utils library."""

import logging
import os
import random
import string

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

logger = logging.getLogger(__name__)


def _load_kube_config():
    # TODO: Remove this workaround when bug LP:1892255 is fixed
    from pathlib import Path
    os.environ.update(
        {
            e.split("=")
            for e in Path("/proc/1/environ").read_text().split("\x00")
            if "KUBERNETES_SERVICE" in e
        }
    )
    # end workaround
    config.load_incluster_config()
