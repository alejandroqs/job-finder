# Lambda operations

Purpose: document the scheduled/serverless path, packaging assumptions, and external side effects.

Read when: changing the Lambda handler, deployment workflow, runtime environment, notification channels, or temporary storage.

Source of truth: [`main.py`](../../src/job_finder/main.py), [`requirements.txt`](../../requirements.txt), [`deploy.yml`](../../.github/workflows/deploy.yml), [`.env.example`](../../.env.example), and [`notifier.py`](../../src/job_finder/notifier.py).

## Runtime path

Configure the Lambda handler as `job_finder.main.lambda_handler`. The handler accepts an event such as `{"sources": ["ALL"], "no_ai": false}`. It scans with `is_lambda=True`, applies date-aware fallback safeguards, and sends findings through configured Discord and/or Telegram channels. The event's `no_ai` flag controls Gemini validation only; it does not suppress notifications.

The code uses `/tmp` for temporary downloaded PDFs because the Lambda filesystem is read-only elsewhere. Temporary BOP and Aena files are removed in cleanup paths. The repository does not define the EventBridge schedule; scheduling and runtime environment variables are infrastructure configuration outside this codebase.

The deployment workflow reads `AWS_ROLE_ARN` and `AWS_REGION` from GitHub Actions repository variables for OIDC authentication. The S3 bucket name and Lambda function name are currently literal values in the workflow. The EventBridge schedule, Lambda environment variables, IAM role permissions, handler setting, and runtime configuration are not defined by this repository's workflow and must be checked in the AWS or GitHub configuration.

## Deployment workflow

`.github/workflows/deploy.yml` runs on pushes to `main` that touch `src/**`, `requirements.txt`, or the workflow itself. It:

1. checks out the repository;
2. obtains AWS credentials through GitHub OIDC and repository variables;
3. builds dependencies inside `public.ecr.aws/sam/build-python3.14`;
4. installs `libffi-devel`, copies `src/job_finder` into the package, and creates a ZIP inside the Linux container;
5. uploads the archive to the configured S3 bucket;
6. updates the configured Lambda function and waits for the update;
7. invokes the function with all sources and AI enabled.

The workflow therefore has production side effects after a qualifying push. Bucket, function, role, and region values are configuration in the workflow or GitHub variables, not portable defaults for another deployment.

`requirements.txt` is intended to contain exact `==` pins. The current `python-dotenv>=1.2.2` entry is a documented policy mismatch. Do not use Windows-native ZIP creation or a generic Linux image for Lambda packages; the required packaging policy is recorded in [`AGENTS.md`](../../AGENTS.md).

## Operational checks

Before changing this path, verify the handler name, Python runtime/image alignment, pinned requirements, `/tmp` usage, notification variables, and IAM/OIDC configuration. A local test suite does not validate AWS permissions, image availability, S3, Lambda, or live notifications.
