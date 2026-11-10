#!/bin/bash
# Fails unless both services are really running the given image tag.
# ECS reports a rolled-back service as stable, so that alone proves nothing.
# Usage: scripts/verify-release.sh <image tag>
set -euo pipefail

tag="$1"
cluster="trueframe"

for service in api worker; do
  read -r task_definition desired running < <(
    aws ecs describe-services --cluster "$cluster" --services "$service" \
      --query 'services[0].[taskDefinition,desiredCount,runningCount]' --output text
  )
  image="$(aws ecs describe-task-definition --task-definition "$task_definition" \
    --query 'taskDefinition.containerDefinitions[0].image' --output text)"

  if [[ "$image" != *":$tag" ]]; then
    echo "$service is not on the new version, so the deployment was rolled back." >&2
    exit 1
  fi
  if [[ "$running" != "$desired" ]]; then
    echo "$service has $running of $desired tasks running." >&2
    exit 1
  fi
  echo "$service: running $desired task(s) on $tag"
done
