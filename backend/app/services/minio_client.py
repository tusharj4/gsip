"""MinIO client factory — returns a configured boto3 S3 client pointed at MinIO."""

import logging

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


def get_minio_client() -> BaseClient:
    """Return a boto3 S3 client configured for the MinIO instance."""
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_url,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",  # MinIO ignores region but boto3 requires it
    )


def ensure_bucket(client: BaseClient, bucket: str) -> None:
    """Create the bucket if it doesn't already exist."""
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            logger.info("Created MinIO bucket: %s", bucket)
        else:
            raise
