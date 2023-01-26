#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage interactions with S3."""

import logging
import tempfile

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
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(content.encode("utf-8"))
            temp_file.flush()

            session = boto3.session.Session(
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
                region_name=s3_region,
            )

            s3 = session.resource("s3", endpoint_url=s3_endpoint)
            bucket = s3.Bucket(s3_bucket)

            bucket.upload_file(temp_file.name, f"{s3_path}")
    except Exception as e:
        logger.exception(
            f"Failed to upload content to s3 bucket={s3_bucket}, path={s3_path}", exc_info=e
        )
        return False

    return True