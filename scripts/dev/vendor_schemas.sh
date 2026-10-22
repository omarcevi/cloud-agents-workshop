#!/usr/bin/env bash
# Refresh the gcloud import schemas in tests/schemas/ from the installed Google Cloud SDK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$(gcloud info --format='value(installation.sdk_root)')/lib/googlecloudsdk/schemas"
cp "${SRC}"/networkservices/v1/{AgentGateway,AgentGatewayGoogleManaged,AgentGatewaySelfManaged,AgentGatewayNetworkConfig,AgentGatewayNetworkConfigEgress,AgentGatewayNetworkConfigDnsPeeringConfig,AuthzExtension,LabelsValue}.yaml \
  "${ROOT}/tests/schemas/networkservices/"
cp "${SRC}"/networksecurity/v1/AuthzPolicy*.yaml "${SRC}"/networksecurity/v1/LabelsValue.yaml "${ROOT}/tests/schemas/networksecurity/"
echo "Schemas refreshed from $(gcloud version --format='value("Google Cloud SDK")')."
