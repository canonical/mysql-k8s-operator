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
import base64
import logging
import tempfile
import time
from typing import Dict, List, Tuple

import boto3

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "bb85c0c01b454bd48898d680e3f3ce4d"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 7

# botocore/urllib3 clutter the logs when on debug
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


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
        ca_file = tempfile.NamedTemporaryFile()
        session = boto3.session.Session(
            aws_access_key_id=s3_parameters["access-key"],
            aws_secret_access_key=s3_parameters["secret-key"],
            region_name=s3_parameters["region"] or None,
        )
        verif = True
        ca_chain = s3_parameters.get("tls-ca-chain")
        if ca_chain:
            ca = "\n".join([base64.b64decode(s).decode() for s in ca_chain])
            ca_file.write(ca.encode())
            ca_file.flush()
            verif = ca_file.name

        s3 = session.resource(
            "s3",
            endpoint_url=s3_parameters["endpoint"],
            verify=verif,
        )

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
    finally:
        ca_file.close()

    return True


def _compile_backups_from_file_ids(
    metadata_ids: List[str], md5_ids: List[str], log_ids: List[str]
) -> List[Tuple[str, str]]:
    """Helper function that compiles tuples of (backup_id, status) from file ids."""
    backups = []
    for backup_id in metadata_ids:
        backup_status = "in progress"
        if backup_id in md5_ids:
            backup_status = "finished"
        elif backup_id in log_ids:
            backup_status = "failed"

        backups.append((backup_id, backup_status))

    return backups


def list_backups_in_s3_path(s3_parameters: Dict) -> List[Tuple[str, str]]:  # noqa: C901
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
            region_name=s3_parameters["region"] or None,
        )
        list_objects_v2_paginator = s3_client.get_paginator("list_objects_v2")
        s3_path_directory = (
            s3_parameters["path"]
            if s3_parameters["path"][-1] == "/"
            else f"{s3_parameters['path']}/"
        )

        metadata_ids = []
        md5_ids = []
        log_ids = []

        for page in list_objects_v2_paginator.paginate(
            Bucket=s3_parameters["bucket"],
            Prefix=s3_path_directory,
            Delimiter="/",
        ):
            for content in page.get("Contents", []):
                key = content["Key"]

                filename = key.removeprefix(s3_path_directory)

                if ".metadata" in filename:
                    try:
                        backup_id = filename.split(".metadata")[0]
                        time.strptime(backup_id, "%Y-%m-%dT%H:%M:%SZ")
                        metadata_ids.append(backup_id)
                    except ValueError:
                        pass
                elif ".md5" in key:
                    md5_ids.append(filename.split(".md5")[0])
                elif ".backup.log" in key:
                    log_ids.append(filename.split(".backup.log")[0])

        return _compile_backups_from_file_ids(metadata_ids, md5_ids, log_ids)
    except Exception as e:
        try:
            # botocore raises dynamically generated exceptions
            # with a response attribute. We can use this to
            # set a more meaningful error message.
            if e.response["Error"]["Code"] == "NoSuchBucket":
                message = f"Bucket {s3_parameters['bucket']} does not exist"
                setattr(e, "message", message)
                raise
        except (KeyError, AttributeError):
            pass
        # default handling exposes exception
        logger.exception(
            f"Failed to list subdirectories in S3 bucket={s3_parameters['bucket']}, path={s3_parameters['path']}"
        )
        raise


def fetch_and_check_existence_of_s3_path(path: str, s3_parameters: Dict[str, str]) -> bool:
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
        region_name=s3_parameters["region"] or None,
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
