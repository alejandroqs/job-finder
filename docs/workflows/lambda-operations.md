# Lambda operations

Purpose: document the scheduled/serverless path, packaging assumptions, and external side effects.

Read when: changing the Lambda handler, deployment workflow, runtime environment, notification channels, or temporary storage.

Source of truth: `src/job_finder/main.py`, `requirements.txt`, `.github/workflows/deploy.yml`, `.env.example`, and `notifier.py`.

## Runtime path

Configure the Lambda handler as `job_finder.main.lambda_handler`. The handler accepts an event such as `{"sources": ["ALL"], "no_ai": false}`. It scans with `is_lambda=True`, applies date-aware fallback safeguards, and sends findings through configured Discord and/or Telegram channels. The event's `no_ai` flag controls Gemini validation only; it does not suppress notifications.

The code uses `/tmp` for temporary downloaded PDFs because the Lambda filesystem is read-only elsewhere. Temporary BOP and Aena files are removed in cleanup paths. The repository does not define the EventBridge schedule; scheduling and runtime environment variables are infrastructure configuration outside this codebase.

## Deployment workflow

`.github/workflows/deploy.yml` runs on pushes to `main` that touch `src/**`, `requirements.txt`, or the workflow itself. It:

1. checks out the repository;
2. obtains AWS credentials through GitHub OIDC and repository variables;
3. builds dependencies inside `public.ecr.aws/sam/build-python3.14`;
4. copies `src/job_finder` into the package and creates a ZIP inside the Linux container;
5. uploads the archive to the configured S3 bucket;
6. updates the configured Lambda function and waits for the update;
7. invokes the function with all sources and AI enabled.

The workflow therefore has production side effects after a qualifying push. Bucket, function, role, and region values are configuration in the workflow or GitHub variables, not portable defaults for another deployment.

## Operational checks

Before changing this path, verify the handler name, Python runtime/image alignment, pinned requirements, `/tmp` usage, notification variables, and IAM/OIDC configuration. A local test suite does not validate AWS permissions, image availability, S3, Lambda, or live notifications.
