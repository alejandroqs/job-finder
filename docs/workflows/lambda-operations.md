# Lambda operations

Purpose: document the scheduled/serverless path, packaging assumptions, and external side effects.

Read when: changing the Lambda handler, deployment workflow, runtime environment, notification channels, or temporary storage.

Source of truth: [`main.py`](../../src/job_finder/main.py), [`requirements.txt`](../../requirements.txt), [`deploy.yml`](../../.github/workflows/deploy.yml), [`run-scan.yml`](../../.github/workflows/run-scan.yml), [`.env.example`](../../.env.example), and [`notifier.py`](../../src/job_finder/notifier.py).

## Runtime path

Configure the Lambda handler as `job_finder.main.lambda_handler`. The handler accepts an event such as `{"sources": ["ALL"], "no_ai": false}`. It scans with `is_lambda=True`, applies date-aware fallback safeguards, and sends findings through configured Discord and/or Telegram channels. The event's `no_ai` flag controls Gemini validation only; it does not suppress notifications.

The code uses `/tmp` for temporary downloaded PDFs because the Lambda filesystem is read-only elsewhere. Temporary BOP and Aena files are removed in cleanup paths. The repository does not define the EventBridge schedule; scheduling and runtime environment variables are infrastructure configuration outside this codebase.

The current source groups mean that a future deployment will make `ALL`/default Lambda scans and `ES` scans include GSC, Indra Group, and FULP. `EU` and explicit selections of other individual sources do not include them. Indra's default blank catalogue traversal can issue one request per discovered search page plus one detail request per deduplicated listing. FULP adds one current listing request, serial detail requests, and manual redirect hops, bounded by 200 scheduled HTTP attempts and a 180-second scheduling deadline per scan; an in-flight request can still extend wall-clock duration. Runtime suitability, portal reachability, complete detail coverage, Gemini classification, and notification behaviour for FULP remain unverified. This source change does not alter the EventBridge schedule and no deployment or schedule operation is performed by the implementation task.

The deployment workflow reads `AWS_ROLE_ARN` and `AWS_REGION` from GitHub Actions repository variables for OIDC authentication. The S3 bucket name and Lambda function name are currently literal values in the workflow. The EventBridge schedule, Lambda environment variables, IAM role permissions, handler setting, and runtime configuration are not defined by this repository's workflow and must be checked in the AWS or GitHub configuration.

## Deployment workflow

`.github/workflows/deploy.yml` runs on pushes to `main` that touch `src/**`, `requirements.txt`, or the workflow itself. It:

1. checks out the repository;
2. obtains AWS credentials through GitHub OIDC and repository variables;
3. builds dependencies inside `public.ecr.aws/sam/build-python3.14`;
4. installs `libffi-devel`, copies `src/job_finder` into the package, and creates a ZIP inside the Linux container;
5. uploads the archive to the configured S3 bucket;
6. updates the configured Lambda function and waits for the update;
7. checks that the function is Active and its last update Successful, without invoking it.

The workflow updates production code after a qualifying push, but does not run a scan or publish offers. Bucket, function, role, and region values are configuration in the workflow or GitHub variables, not portable defaults for another deployment.

## Manual production scans and retries

After `run-scan.yml` reaches the default branch, use GitHub Actions → Manual
Production Scan → Run workflow on `main`. Select `ALL`, `ES` or `EU`, and
explicitly enable `publish_notifications`. Leaving it false skips the scan.
This runs the already-deployed Lambda code with AI enabled and sends real
notifications; it does not deploy the selected repository revision.

The invocation step sets `AWS_MAX_ATTEMPTS=1` and `AWS_RETRY_MODE=standard` to
prevent AWS CLI retries, uses synchronous `RequestResponse`, and sets a
960-second client read timeout with a 20-minute job limit. This does not change
Lambda's configured timeout. It checks both invocation metadata (`FunctionError`)
and the handler's `statusCode`, so a returned function error fails the workflow.
A successful handler response does not prove delivery: the notifier currently
catches channel errors.

Deployment and manual scans share a GitHub concurrency group with automatic
cancellation disabled. This prevents these workflow runs from executing
concurrently; it does not serialize EventBridge or other direct invocations.
If the client disconnects or a workflow is cancelled, Lambda may still be
running. Check CloudWatch START/REPORT records before manually rerunning.
There is no persistent notification deduplication, and a deliberate rerun can
republish offers. EventBridge scheduling and its retry policy remain unchanged.

For deliberate CLI invocations outside this workflow, set `AWS_MAX_ATTEMPTS=1`
in that command's environment too. [AWS retry settings](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-retries.html)
count the initial call as an attempt. Do not use `--no-ai` as a notification
suppression mechanism.

`requirements.txt` is intended to contain exact `==` pins. The current `python-dotenv>=1.2.2` entry is a documented policy mismatch. Do not use Windows-native ZIP creation or a generic Linux image for Lambda packages; the required packaging policy is recorded in [`AGENTS.md`](../../AGENTS.md).

## Operational checks

Before changing this path, verify the handler name, Python runtime/image alignment, pinned requirements, `/tmp` usage, notification variables, and IAM/OIDC configuration. A local test suite does not validate AWS permissions, image availability, S3, Lambda, or live notifications.
