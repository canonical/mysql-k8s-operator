#!/bin/bash

S3_BUCKET=$1
if [ -z "${S3_BUCKET}" ]; then
    echo "Missing argument: S3 Bucket"
    exit 1
fi

S3_PATH=$2
if [ -z "${S3_PATH}" ]; then
    echo "Missing argument: S3 Path"
    exit 1
fi

S3_ACCESS_KEY=$3
if [ -z "${S3_ACCESS_KEY}" ]; then
    echo "Missing argument: S3 Access Key"
    exit 1
fi

S3_SECRET_KEY=$4
if [ -z "${S3_SECRET_KEY}" ]; then
    echo "Missing argument: S3 Secret Key"
    exit 1
fi

MYSQL_USER=$5
if [ -z "${MYSQL_USER}" ]; then
    echo "Missing argument: MySQL User"
    exit 1
fi

MYSQL_PASSWORD=$6
if [ -z "${MYSQL_PASSWORD}" ]; then
    echo "Missing argument: MySQL Password"
    exit 1
fi

MYSQL_SOCKET=/run/mysqld/mysqld.sock
TMP_DIRECTORY=$(mktemp --tmpdir --directory xtra_backup_XXXX)

# TODO: remove flag --no-server-version-check once all (mysql, xtrabackup) versions in sync
xtrabackup --defaults-file=/etc/mysql \
            --defaults-group=mysqld \
            --no-version-check \
            --parallel="$(nproc)" \
            --user="$MYSQL_USER" \
            --password="$MYSQL_PASSWORD" \
            --socket="$MYSQL_SOCKET" \
            --lock-ddl \
            --backup \
            --stream=xbstream \
            --xtrabackup-plugin-dir=/usr/lib64/xtrabackup/plugin \
            --target-dir="$TMP_DIRECTORY" \
            --no-server-version-check | \
    xbcloud put \
            --curl-retriable-errors=7 \
            --insecure \
            --storage=s3 \
            --parallel=10 \
            --md5 \
            --s3-bucket="$S3_BUCKET" \
            --s3-access-key="$S3_ACCESS_KEY" \
            --s3-secret-key="$S3_SECRET_KEY" \
            "$S3_PATH"
