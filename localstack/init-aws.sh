#!/bin/bash
# Runs inside LocalStack when it starts. Creates the local stand-ins for the
# S3 bucket, queues and table that Terraform will create on real AWS.
set -euo pipefail

export AWS_DEFAULT_REGION=eu-west-2

awslocal s3 mb s3://trueframe-uploads

# The dead-letter queue collects jobs that failed three times.
awslocal sqs create-queue --queue-name trueframe-scans-dlq
awslocal sqs create-queue --queue-name trueframe-scans --attributes '{
  "VisibilityTimeout": "300",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:eu-west-2:000000000000:trueframe-scans-dlq\",\"maxReceiveCount\":\"3\"}"
}'

awslocal dynamodb create-table \
  --table-name trueframe-scans \
  --attribute-definitions AttributeName=scan_id,AttributeType=S \
  --key-schema AttributeName=scan_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
awslocal dynamodb update-time-to-live \
  --table-name trueframe-scans \
  --time-to-live-specification Enabled=true,AttributeName=expires_at

# The health check waits for this file, so nothing starts before setup is done.
touch /tmp/trueframe-ready
