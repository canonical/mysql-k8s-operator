#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers to manage interactions with S3."""

import logging
import tempfile
from typing import List

import boto3

logger = logging.getLogger(__name__)


def upload_content_to_s3(
    content: str,
    s3_bucket: str,
    s3_path: str,
    s3_region: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
) -> bool:
    """Uploads the provided contents to the provided S3 bucket.

    Args:
        content: The content to upload to S3
        s3_bucket: The S3 bucket to upload content to
        s3_path: The S3 path to upload content to
        s3_region: The S3 region to upload content to
        s3_endpoint: The S3 endpoint to upload content to
        s3_access_key: The S3 access key
        s3_secret_key: The S3 secret key

    Returns: a boolean indicating success.
    """
    try:
        logger.info(f"Uploading content to bucket={s3_bucket}, path={s3_path}")
        session = boto3.session.Session(
            aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key,
            region_name=s3_region,
        )

        s3 = session.resource("s3", endpoint_url=s3_endpoint)
        bucket = s3.Bucket(s3_bucket)

        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(content.encode("utf-8"))
            temp_file.flush()

            bucket.upload_file(temp_file.name, f"{s3_path}")
    except Exception as e:
        logger.exception(
            f"Failed to upload content to S3 bucket={s3_bucket}, path={s3_path}", exc_info=e
        )
        return False

    return True


def list_backups_in_s3_path(
    s3_bucket: str,
    s3_path: str,
    s3_region: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
) -> List[str]:
    """Retrieve subdirectories in an S3 path.

    Args:
        content: The content to upload to S3
        s3_bucket: The S3 bucket to upload content to
        s3_path: The S3 path to upload content to
        s3_region: The S3 region to upload content to
        s3_endpoint: The S3 endpoint to upload content to
        s3_access_key: The S3 access key
        s3_secret_key: The S3 secret key

    Returns: a list of subdirectories directly after the S3 path.
    """
    try:
        logger.info(f"Listing subdirectories from S3 bucket={s3_bucket}, path={s3_path}")
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key,
            endpoint_url=s3_endpoint,
            region_name=s3_region,
        )
        list_objects_v2_paginator = s3_client.get_paginator("list_objects_v2")
        s3_path_directory = s3_path if s3_path[-1] == "/" else f"{s3_path}/"

        directories = []
        for page in list_objects_v2_paginator.paginate(
            Bucket=s3_bucket,
            Prefix=s3_path_directory,
            Delimiter="/",
        ):
            for common_prefix in page.get("CommonPrefixes", []):
                # Confirm that the directory has a valid backup
                response = s3_client.list_objects_v2(
                    Bucket=s3_bucket, Prefix=f"{common_prefix['Prefix']}backup", Delimiter="/"
                )
                if response.get("KeyCount", 0) > 0:
                    directories.append(
                        common_prefix["Prefix"].lstrip(s3_path_directory).split("/")[0]
                    )

        return directories
    except Exception as e:
        logger.exception(
            f"Failed to list subdirectories in S3 bucket={s3_bucket}, path={s3_path}", exc_info=e
        )
        raise
