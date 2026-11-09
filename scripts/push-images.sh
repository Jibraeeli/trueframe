#!/bin/bash
# Builds the ARM images and pushes them to ECR, tagged with the current commit.
# Usage: AWS_PROFILE=<profile> scripts/push-images.sh
set -euo pipefail

cd "$(dirname "$0")/.."

tag="$(git rev-parse --short=12 HEAD)"
api_repo="$(terraform -chdir=infra output -raw api_repository_url)"
worker_repo="$(terraform -chdir=infra output -raw worker_repository_url)"
registry="${api_repo%%/*}"
region="$(cut -d. -f4 <<<"$registry")"

aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

docker buildx build --platform linux/arm64 --provenance=false --push \
  -f app/api/Dockerfile -t "$api_repo:$tag" .
docker buildx build --platform linux/arm64 --provenance=false --push \
  -f app/worker/Dockerfile --target runtime -t "$worker_repo:$tag" .

echo "Pushed image tag: $tag"
