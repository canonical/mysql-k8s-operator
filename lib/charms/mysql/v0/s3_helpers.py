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
import pathlib
import tempfile
import time
from contextlib import nullcontext
from io import BytesIO

import boto3
import botocore
import botocore.exceptions

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "bb85c0c01b454bd48898d680e3f3ce4d"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 12

S3_GROUP_REPLICATION_ID_FILE = "group_replication_id.txt"

# botocore/urllib3 clutter the logs when on debug
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def _construct_endpoint(s3_parameters: dict) -> str:
    """Construct the S3 service endpoint using the region.

    This is needed when the provided endpoint is from AWS, and it doesn't contain the region.
    """
    # Use the provided endpoint if a region is not needed.
    endpoint = s3_parameters["endpoint"]

    # Load endpoints data.
    loader = botocore.loaders.create_loader()
    data = loader.load_data("endpoints")

    # Construct the endpoint using the region.
    resolver = botocore.regions.EndpointResolver(data)
    endpoint_data = resolver.construct_endpoint("s3", s3_parameters["region"])

    # Use the built endpoint if it is an AWS endpoint.
    if endpoint_data and endpoint.endswith(endpoint_data["dnsSuffix"]):
        endpoint = f"{endpoint.split('://')[0]}://{endpoint_data['hostname']}"

    return endpoint


def _get_bucket(s3_parameters: dict) -> boto3.resources.base.ServiceResource:
    """Get an S3 bucket resource.

    Args:
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, region,
            endpoint, access-key and secret-key

    Returns: an S3 bucket resource
    """
    session = boto3.session.Session(
        aws_access_key_id=s3_parameters["access-key"],
        aws_secret_access_key=s3_parameters["secret-key"],
        region_name=s3_parameters["region"] or None,
    )

    ca_chain = s3_parameters.get("tls-ca-chain")

    with tempfile.NamedTemporaryFile() if ca_chain else nullcontext() as ca_file:
        if ca_file:
            ca = "\n".join([base64.b64decode(s).decode() for s in ca_chain])
            ca_file.write(ca.encode())
            ca_file.flush()

        s3 = session.resource(
            "s3",
            endpoint_url=_construct_endpoint(s3_parameters),
            verify=ca_file.name if ca_file else True,
        )

    return s3.Bucket(s3_parameters["bucket"])


def upload_content_to_s3(content: str, content_path: str, s3_parameters: dict) -> bool:
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

        bucket = _get_bucket(s3_parameters)

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


def _read_content_from_s3(content_path: str, s3_parameters: dict) -> str | None:
    """Reads specified content from the provided S3 bucket.

    Args:
        content_path: The S3 path from which download the content
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, region,
            endpoint, access-key and secret-key

    Returns:
        a string with the content if object is successfully downloaded and None if file is not existing or error
        occurred during download.
    """
    try:
        logger.info(f"Reading content from bucket={s3_parameters['bucket']}, path={content_path}")

        bucket = _get_bucket(s3_parameters)

        with BytesIO() as buf:
            bucket.download_fileobj(content_path, buf)
            return buf.getvalue().decode("utf-8")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.info(
                f"No such object to read from S3 bucket={s3_parameters['bucket']}, path={content_path}"
            )
        else:
            logger.exception(
                f"Failed to read content from S3 bucket={s3_parameters['bucket']}, path={content_path}",
                exc_info=e,
            )
    except Exception as e:
        logger.exception(
            f"Failed to read content from S3 bucket={s3_parameters['bucket']}, path={content_path}",
            exc_info=e,
        )

    return None


def _compile_backups_from_file_ids(
    metadata_ids: list[str], md5_ids: list[str], log_ids: list[str]
) -> list[tuple[str, str]]:
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


def list_backups_in_s3_path(s3_parameters: dict) -> list[tuple[str, str]]:  # noqa: C901
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
            endpoint_url=_construct_endpoint(s3_parameters),
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


def fetch_and_check_existence_of_s3_path(path: str, s3_parameters: dict[str, str]) -> bool:
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
        endpoint_url=_construct_endpoint(s3_parameters),
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


def ensure_s3_compatible_group_replication_id(
    group_replication_id: str, s3_parameters: dict[str, str]
) -> bool:
    """Checks if group replication id is equal to the one in the provided S3 repository.

    If S3 doesn't have this claim (so it's not initialized),
    then it will be populated automatically with the provided id.

    Args:
        group_replication_id: group replication id of the current cluster
        s3_parameters: A dictionary containing the S3 parameters
            The following are expected keys in the dictionary: bucket, region,
            endpoint, access-key and secret-key
    """
    s3_id_path = str(pathlib.Path(s3_parameters["path"]) / S3_GROUP_REPLICATION_ID_FILE)
    s3_id = _read_content_from_s3(s3_id_path, s3_parameters)
    if s3_id and s3_id != group_replication_id:
        logger.info(
            f"s3 repository is not compatible based on group replication id: {group_replication_id} != {s3_id}"
        )
        return False
    upload_content_to_s3(group_replication_id, s3_id_path, s3_parameters)
    return True
