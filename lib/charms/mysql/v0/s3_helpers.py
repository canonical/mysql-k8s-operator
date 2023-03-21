# Copyright 2022 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""S3 helper functions for the MySQL charms."""

import logging
import tempfile
from typing import Dict, List

import boto3

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "bb85c0c01b454bd48898d680e3f3ce4d"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


def upload_content_to_s3(content: str, content_path: str, s3_parameters: Dict) -> bool:
    """Uploads the provided contents to the provided S3 bucket.

    Args:
        content: The content to upload to S3
        content_path: The path to which to upload the content
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, region,
            endpoint, access-key and secret-key

    Returns: a boolean indicating success.
    """
    try:
        logger.info(f"Uploading content to bucket={s3_parameters['bucket']}, path={content_path}")
        session = boto3.session.Session(
            aws_access_key_id=s3_parameters["access-key"],
            aws_secret_access_key=s3_parameters["secret-key"],
            region_name=s3_parameters["region"],
        )

        s3 = session.resource("s3", endpoint_url=s3_parameters["endpoint"])
        bucket = s3.Bucket(s3_parameters["bucket"])

        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(content.encode("utf-8"))
            temp_file.flush()

            bucket.upload_file(temp_file.name, content_path)
    except Exception as e:
        logger.exception(
            f"Failed to upload content to S3 bucket={s3_parameters['bucket']}, path={content_path}",
            exc_info=e,
        )
        return False

    return True


def list_backups_in_s3_path(s3_parameters: Dict) -> List[str]:
    """Retrieve subdirectories in an S3 path.

    Args:
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, path,
            region, endpoint, access-key and secret-key

    Returns: a list of subdirectories directly after the S3 path.

    Raises: any exception raised by boto3
    """
    try:
        logger.info(
            f"Listing subdirectories from S3 bucket={s3_parameters['bucket']}, path={s3_parameters['path']}"
        )
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=s3_parameters["access-key"],
            aws_secret_access_key=s3_parameters["secret-key"],
            endpoint_url=s3_parameters["endpoint"],
            region_name=s3_parameters["region"],
        )
        list_objects_v2_paginator = s3_client.get_paginator("list_objects_v2")
        s3_path_directory = (
            s3_parameters["path"]
            if s3_parameters["path"][-1] == "/"
            else f"{s3_parameters['path']}/"
        )

        directories = []
        for page in list_objects_v2_paginator.paginate(
            Bucket=s3_parameters["bucket"],
            Prefix=s3_path_directory,
            Delimiter="/",
        ):
            for content in page.get("Contents", []):
                key = content["Key"]
                if ".md5" in key:
                    directories.append(
                        key.lstrip(s3_path_directory).split("/")[0].split(".md5")[0]
                    )

        return directories
    except Exception as e:
        logger.exception(
            f"Failed to list subdirectories in S3 bucket={s3_parameters['bucket']}, path={s3_parameters['path']}",
            exc_info=e,
        )
        raise


def fetch_and_check_existence_of_s3_path(s3_parameters: Dict, path: str) -> bool:
    """Checks the existence of a provided S3 path by fetching the object.

    Args:
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, region,
            endpoint, access-key and secret-key
        path: The path to check the existence of

    Returns: a boolean indicating the existence of the s3 path

    Raises: any exceptions raised by boto3
    """
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=s3_parameters["access-key"],
        aws_secret_access_key=s3_parameters["secret-key"],
        endpoint_url=s3_parameters["endpoint"],
        region_name=s3_parameters["region"],
    )

    try:
        response = s3_client.get_object(Bucket=s3_parameters["bucket"], Key=path, Range="0-1")
        return "ContentLength" in response  # return True even if object is empty
    except s3_client.exceptions.NoSuchKey:
        return False
    except Exception as e:
        logger.exception(
            f"Failed to fetch and check existence of path {path} in S3 bucket {s3_parameters['bucket']}",
            exc_info=e,
        )
        raise
