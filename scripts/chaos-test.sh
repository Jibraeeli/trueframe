#!/bin/bash
# Kills a worker in the middle of a scan and checks that no job is lost.
#
# A normal stop gives a running scan two minutes to finish, so this first swaps
# in a copy of the worker that is force-killed after two seconds. Everything is
# put back at the end, even if the test fails.
#
# Usage: scripts/chaos-test.sh <base url> <large video> <small image>
# Needs the AWS CLI, curl and jq. CURL_ARGS can add options for curl.
set -euo pipefail

base_url="$1"
big_file="$2"
small_file="$3"
cluster="trueframe"
service="worker"
dimension="ecs:service:DesiredCount"
resource="service/$cluster/$service"
small_jobs=3
recovery_limit_seconds=900

read -r -a curl_args <<< "${CURL_ARGS:-}"

api() { curl -sS --max-time 240 "${curl_args[@]}" "$@"; }
now() { date +%s; }
say() { echo "[$(date +%H:%M:%S)] $*"; }

upload() {
  api -F "file=@$1" "$base_url/api/scans" | jq -r .scan_id
}

status_of() {
  api "$base_url/api/scans/$1" | jq -r .status
}

suspend_scale_in() {
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension "$dimension" --resource-id "$resource" \
    --suspended-state "DynamicScalingInSuspended=$1"
}

original_task_definition="$(aws ecs describe-services --cluster "$cluster" --services "$service" \
  --query 'services[0].taskDefinition' --output text)"
original_count="$(aws ecs describe-services --cluster "$cluster" --services "$service" \
  --query 'services[0].desiredCount' --output text)"

restore() {
  say "Putting the original worker back"
  aws ecs update-service --cluster "$cluster" --service "$service" \
    --task-definition "$original_task_definition" --desired-count "$original_count" > /dev/null
  suspend_scale_in false
}
trap restore EXIT

suspend_scale_in true

say "Registering a worker that is force-killed after 2 seconds"
fragile_task_definition="$(
  aws ecs describe-task-definition --task-definition "$original_task_definition" \
    --query taskDefinition --output json |
    jq 'del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
            .registeredAt, .registeredBy, .deregisteredAt)
        | .containerDefinitions[0].stopTimeout = 2' > chaos-task.json
  aws ecs register-task-definition --cli-input-json file://chaos-task.json \
    --query taskDefinition.taskDefinitionArn --output text
)"
rm -f chaos-task.json

aws ecs update-service --cluster "$cluster" --service "$service" \
  --task-definition "$fragile_task_definition" --desired-count 1 > /dev/null
aws ecs wait services-stable --cluster "$cluster" --services "$service"
say "Fragile worker is running"

big_scan="$(upload "$big_file")"
say "Uploaded the large video: $big_scan"
small_scans=()
for _ in $(seq 1 "$small_jobs"); do
  small_scans+=("$(upload "$small_file")")
done
say "Queued $small_jobs small images behind it"

# Two workers may have been started by the backlog, so all of them are killed.
while [[ "$(status_of "$big_scan")" == "queued" ]]; do sleep 2; done
tasks="$(aws ecs list-tasks --cluster "$cluster" --service-name "$service" \
  --query taskArns --output text)"
for task in $tasks; do
  aws ecs stop-task --cluster "$cluster" --task "$task" --reason "Chaos test" > /dev/null
done
killed_at="$(now)"
say "Killed $(wc -w <<< "$tasks") worker(s) during the scan, status was: $(status_of "$big_scan")"

failed=0
for scan in "$big_scan" "${small_scans[@]}"; do
  while :; do
    status="$(status_of "$scan")"
    [[ "$status" == "complete" || "$status" == "failed" ]] && break
    if (( "$(now)" - killed_at > recovery_limit_seconds )); then
      status="still $status after $recovery_limit_seconds seconds"
      break
    fi
    sleep 5
  done
  say "$scan: $status, $(( "$(now)" - killed_at )) seconds after the kill"
  [[ "$status" == "complete" ]] || failed=1
done

dead_letters="$(aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name "$cluster-scans-dlq" --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages \
  --query Attributes.ApproximateNumberOfMessages --output text)"
say "Dead letters: $dead_letters"

if (( failed )) || (( dead_letters > 0 )); then
  say "FAILED: a job was lost or did not finish"
  exit 1
fi
say "PASSED: every job finished after the workers were killed"
