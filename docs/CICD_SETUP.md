# Data Match — CI/CD setup checklist

This project ships with a GitHub Actions workflow that deploys to three tiers
on branch events:

| Branch | Tier | GCP project |
|---|---|---|
| `dev` | dev | `horizon-ai-462013` |
| `staging` | staging | `horizon-ai-462013` |
| `main` | prod | `horizon-ai-462013` |

The actual deploy logic lives in [`HorizonMedia/agentq-actions`](https://github.com/HorizonMedia/agentq-actions). This project's `.github/workflows/agentq-deploy.yml`
is a thin caller of that reusable workflow.

## One-time bootstrap (ops checklist)

Run **once per GCP project** by someone with project-level IAM authority.

### 1. Bootstrap the dev GCP

```bash
agentq setup-cicd \
  --gcp-project horizon-ai-462013 \
  --github-org <YOUR_ORG> \
  --github-repo <THIS_REPO_NAME> \
  --tiers dev
```

This creates:
- WIF pool `agentq-pool` + provider `github`
- Service accounts: `agentq-deploy-dev`, `agentq-runtime-dev`, `agentq-plan`
- State bucket `gs://horizon-ai-462013-agentq-state`
- IAM bindings (deploy SA can impersonate runtime SA, etc.)

The command prints the `workload_identity_provider` URI. **Copy it.**

### 2. Bootstrap the prod GCP



```bash
agentq setup-cicd \
  --gcp-project horizon-ai-462013 \
  --github-org <YOUR_ORG> \
  --github-repo <THIS_REPO_NAME> \
  --tiers staging --tiers prod
```


Creates the same shape on the prod GCP, with one deploy SA per tier
(staging + prod) so each has its own IAM scope.

### 3. Paste the WIF URI into `.github/workflows/agentq-deploy.yml`

Replace `REPLACE_ME_with_value_printed_by_agentq_setup-cicd` with the full
provider resource name. Use the prod GCP's value (the workflow handles routing
to the right GCP per tier automatically).

### 4. Bootstrap KB datastores (per AgentQ project, not per GCP)

Datastores are per-agent-use-case, not bootstrap. Run from your laptop with
the appropriate `--allow-prod-kb-mutation` if staging/prod:

```bash
# dev
agentq kb create-datastore --tier dev
agentq kb create-bucket    --tier dev
agentq kb upload           --tier dev
agentq kb import           --tier dev

# staging + prod (only on initial setup; subsequent KB updates flow through GitOps)
agentq kb create-datastore --tier staging --allow-prod-kb-mutation
agentq kb create-bucket    --tier staging --allow-prod-kb-mutation
agentq kb create-datastore --tier prod    --allow-prod-kb-mutation
agentq kb create-bucket    --tier prod    --allow-prod-kb-mutation
```

### 5. Configure GitHub branch protections

For each protected branch:

| Branch | Protection rules |
|---|---|
| `main` | Require PR before merge. Require status check `agentq-deploy / deploy` (on the staging tier) to be passing. Restrict who can push. |
| `staging` | Require PR. Require `agentq-deploy / deploy` (on dev) passing. |
| `dev` | Require PR check passing. |

### 6. Migrate an existing engine (optional)

If you already have a deployed engine you want to bring under GitOps:

```bash
agentq state import \
  --tier prod \
  --resource-name projects/.../reasoningEngines/123 \
  --with-kb
```

This stamps the existing engine into the prod tier's state file so the next
CI run sees no drift.

## Daily workflow

1. Open a PR against `dev`. CI runs `agentq state plan` and posts the diff as a PR comment.
2. Merge → CI deploys to the dev tier.
3. Open a PR `dev` → `staging`. Plan-only on the staging tier.
4. Merge → CI deploys to staging.
5. Open a PR `staging` → `main`. Plan-only on prod. **Gate**: CI verifies that the staging tier was deployed from an ancestor of the prod branch HEAD; if not, the workflow fails.
6. Merge → CI deploys to prod. KB mutations are allowed only on this merge.

## Drift detection

If the deployed engine diverges from the state file (e.g. someone manually
edits in the Cloud console), CI fails with a clear diff. To override on the
PR, add the label `force-apply`. To override on a push, re-run with
`workflow_dispatch` and pass `dry_run: false`.

## Rollback

Roll back the engine by reverting the merge that deployed the bad change. CI
will re-deploy the reverted state. State files are versioned in GCS (30-day
noncurrent retention) so you can also `gsutil ls -a gs://.../state.yaml` and
restore an older generation if needed.

