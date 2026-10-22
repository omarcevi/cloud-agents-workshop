#!/usr/bin/env bash
# One-time: let the E2E GitHub workflow act in a TEST project through Workload Identity
# Federation (no service account keys).
#
# Creates a deployer service account with roles/owner on the project (the lab grants IAM
# roles and binds access policies, so it needs broad rights: use a dedicated test project),
# a workload identity pool and a GitHub OIDC provider that only accepts tokens from the
# E2E workflow (.github/workflows/e2e.yml) running on main of REPO, and lets that
# repository impersonate the service account. Prints the three repository variables;
# with --github it also sets them with the gh CLI. Also create a GitHub environment named
# "e2e" with required reviewers (Settings → Environments): the workflow runs in it.
#
# Usage: scripts/dev/setup_wif.sh PROJECT_ID [owner/repo] [--github]
set -euo pipefail

PROJECT_ID="${1:?usage: setup_wif.sh PROJECT_ID [owner/repo] [--github]}"
REPO="${2:-omarcevi/cloud-agents-workshop}"
SET_GITHUB="${3:-}"
POOL=github-e2e
PROVIDER=github
SA_NAME=workshop-e2e
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project "${PROJECT_ID}" --quiet

gcloud iam service-accounts describe "${SA}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${SA_NAME}" --project "${PROJECT_ID}" \
       --display-name "Workshop E2E deployer (GitHub Actions)"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member "serviceAccount:${SA}" \
  --role roles/owner --condition None --quiet >/dev/null

gcloud iam workload-identity-pools describe "${POOL}" --location global --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "${POOL}" --location global --project "${PROJECT_ID}" \
       --display-name "GitHub Actions (workshop E2E)"
gcloud iam workload-identity-pools providers describe "${PROVIDER}" --workload-identity-pool "${POOL}" \
    --location global --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "${PROVIDER}" \
       --workload-identity-pool "${POOL}" --location global --project "${PROJECT_ID}" \
       --issuer-uri https://token.actions.githubusercontent.com \
       --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.workflow_ref=assertion.workflow_ref" \
       --attribute-condition "assertion.repository == '${REPO}' && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == '${REPO}/.github/workflows/e2e.yml@refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding "${SA}" --project "${PROJECT_ID}" \
  --role roles/iam.workloadIdentityUser --quiet >/dev/null \
  --member "principalSet://iam.googleapis.com/projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"

PROVIDER_NAME="projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
echo "E2E_PROJECT_ID=${PROJECT_ID}"
echo "E2E_WIF_PROVIDER=${PROVIDER_NAME}"
echo "E2E_SERVICE_ACCOUNT=${SA}"
if [[ "${SET_GITHUB}" == "--github" ]]; then
  gh variable set E2E_PROJECT_ID --repo "${REPO}" --body "${PROJECT_ID}"
  gh variable set E2E_WIF_PROVIDER --repo "${REPO}" --body "${PROVIDER_NAME}"
  gh variable set E2E_SERVICE_ACCOUNT --repo "${REPO}" --body "${SA}"
fi
