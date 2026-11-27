# Aidevops

A local workspace that helps you turn an existing app into a Docker image and open a preview in your browser, with optional approval-gated AWS deployment. Add your project, review the suggested setup, approve the build, and launch it locally.

Aidevops includes a FastAPI backend and a Streamlit frontend. AI planning and general assistant replies use the configured provider: OpenAI-compatible APIs (including Groq) or Anthropic Claude. Administrator-only Docker and AWS status questions use current backend readings directly; allowlisted AWS management commands run through the FastAPI backend. Without a provider key, general chat is unavailable and planning uses clearly labelled rule-based example plans.

## Quick navigation

- [Requirements](#requirements)
- [Quick start](#quick-start-windows-powershell)
- [Use the workspace](#use-the-workspace)
- [Docker monitoring and management](#docker-monitoring-and-management)
- [AWS deployment and monitoring](#aws-deployment-and-monitoring)
- [AWS management dashboard](#aws-management-dashboard)
- [Supported projects](#supported-projects)
- [Configuration and AI privacy](#configuration-and-ai-privacy)
- [Troubleshooting](#troubleshooting)
- [API example](#api-example-powershell)
- [Tests and developer documentation](#tests-and-developer-documentation)

## Requirements

| Requirement | Purpose |
| --- | --- |
| Python 3.11 or newer | Runs the backend and UI. Python 3.14.2 was tested locally. |
| Git | Downloads the project on the first run. |
| Docker Desktop with Linux containers (optional) | Required only to build images, start previews, and run container tests. |
| LocalStack (optional) | Emulates AWS APIs for local monitoring and deployment tests; defaults to `http://localhost:4566`. |
| Internet access | Needed on first run to download the project and Python packages. |
| Your app's source code | Upload a ZIP/TAR archive or use a folder on the backend computer. |
| AI provider key (optional) | Enables external AI planning. The project works without one. |

## Quick start (Windows PowerShell)

Open PowerShell in the project folder (or its parent folder), paste this whole block, and press Enter. It downloads the project if needed, creates the Python environment, installs dependencies, starts both services, waits for them to respond, and opens the login page. It reuses services that are already listening on the default ports.

```powershell
$ErrorActionPreference = 'Stop'

if (Test-Path '.\aidevops\api\main.py') {
    $project = (Get-Location).Path
} elseif (Test-Path '.\AiDevops\aidevops\api\main.py') {
    $project = (Resolve-Path '.\AiDevops').Path
} else {
    git clone https://github.com/abhishekallipur/AiDevops.git
    if ($LASTEXITCODE -ne 0) { throw 'Could not download Aidevops. Check that Git and internet access are available.' }
    $project = (Resolve-Path '.\AiDevops').Path
}

Set-Location $project
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer, then paste this block again.' }

if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access and paste this block again.' }

$env:AIDEVOPS_API_URL = 'http://127.0.0.1:8000'
$env:AIDEVOPS_DASHBOARD_URL = 'http://127.0.0.1:8501'

if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'aidevops.api.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $project
}

$apiReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { $apiReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $apiReady) { throw 'The backend did not start. Check the FastAPI window and make sure port 8000 is free.' }

if (-not (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $python -ArgumentList @('-m', 'streamlit', 'run', 'aidevops/ui/streamlit_app.py', '--server.address', '127.0.0.1', '--server.port', '8501') -WorkingDirectory $project
}

$uiReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 2
        if ($page.StatusCode -eq 200) { $uiReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $uiReady) { throw 'The dashboard did not start. Check the Streamlit window and make sure port 8501 is free.' }

Start-Process 'http://127.0.0.1:8000/'
Write-Host 'Aidevops is ready. Sign in at http://127.0.0.1:8000/'
```

On a fresh data directory, sign in with **admin** / **admin123**. Change the demo password before exposing the app to any network. The dashboard starts without an AI key, AWS credentials, or LocalStack. Those integrations show as unavailable until configured. Docker Desktop is only needed for building images, previews, and container tests; you can start and explore the dashboard without it.

### Optional configuration

You do not need a `.env` file to start Aidevops. To customize settings, create one without overwriting an existing file:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Keep `.env` private and do not commit it. Restart the backend after changing its configuration. Existing shell environment variables take precedence over `.env`.

The backend also serves the login and signup page at **[http://127.0.0.1:8000/login](http://127.0.0.1:8000/login)**. Sign-up creates additional accounts in the SQLite database; each username must be unique and passwords must be at least eight characters. After registration, the form returns to login and asks the new user to sign in; it does not automatically create a session. Set `AIDEVOPS_ADMIN_USERNAME` and `AIDEVOPS_ADMIN_PASSWORD` before the first backend startup to use different administrator credentials; a restart updates the configured admin password. Passwords are stored as salted hashes, and successful logins create expiring server-side sessions in HttpOnly cookies, then redirect to the Streamlit workspace. Keep the frontend running on port 8501 or set `AIDEVOPS_DASHBOARD_URL` to its URL. Docker and AWS management are restricted to the configured administrator; existing project APIs and public sign-up retain their existing access model. Use the same host name (for example, `127.0.0.1`) for the login page and Streamlit dashboard so the browser session cookie reaches the dashboard.

Open **AI assistant** from the dashboard sidebar for a full-page chat. General questions use the configured AI provider and stay in the current Streamlit session. Questions about live Docker containers and EC2 readings are answered from the local Docker Engine or AWS/LocalStack services and require the configured administrator; these readings are not sent to the AI provider. For example, ask “Show EC2 CPU and RAM” or “List running containers.” Exact AWS management commands are handled deterministically by FastAPI using validated, allowlisted operations; they are not sent to the AI provider and cannot run arbitrary shell commands. Configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GROQ_API_KEY` in `.env`, select the provider with `AIDEVOPS_LLM_PROVIDER` when needed, and restart the backend. Without a configured provider, general chat reports that it is unavailable rather than returning a canned answer. EC2 memory readings require the CloudWatch Agent to publish `CWAgent/mem_used_percent`.

| Address | What it opens |
| --- | --- |
| [127.0.0.1:8000/](http://127.0.0.1:8000/) | Login page (redirects to login) |
| [127.0.0.1:8501](http://127.0.0.1:8501) | Aidevops workspace after login |
| [127.0.0.1:8000/health](http://127.0.0.1:8000/health) | Backend connection/configuration status |
| [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Interactive API reference |

Run **one backend process per data directory**. Do not add multiple Uvicorn workers: the preview service uses a single-process worker lock.

### Stop or restart

1. In the UI, stop any active preview you no longer need. Use **Remove preview resources** if you also want its image and snapshot removed.
2. Press **Ctrl+C** in each service window to stop the frontend and backend.
3. To restart, paste the Quick start block again from the project folder; already-running services are reused.

Stopping the frontend does not stop a preview container. Automatic preview expiry requires the backend to remain running; it reconciles expired sessions after restart. If the backend is offline, expiry is not enforced at that time.

After updating the project, restart both processes to load configuration and imported-module changes, then refresh the browser. Create a **new project review** to regenerate setup files; an old review keeps its previously generated files.

## Use the workspace

### 1. Add a project

Choose **ï¼‹ New project**, then one of:

- **Upload a project:** upload the source as ZIP, TAR, GZ, or TGZ. The backend upload limit defaults to 50,000,000 bytes, even if the browser uploader displays a higher limit.
- **Use a folder:** paste an absolute folder path, such as `E:\MyProjects\todo-app`. It must be accessible on the computer running the backend.
- **Try an example project:** explore the bundled sample without uploading files.

Use the app's source folder containing its manifest or entry point. Leave out `.env`, credentials, dependency directories, build caches, and unrelated files. A screenshot or finished installer is not app source. Upload and folder choices are shown together on the project home screen.

Aidevops reads project clues, prepares a plan, generates setup files in an isolated workspace, and performs static validation. Original source files are not overwritten. The review then waits for your decisions.

### 2. Review the suggested setup

The project page keeps **Build & preview** in the main workflow. Project findings, setup files, and check results are available in expandable supporting sections; the approval action for checks stays visible when required.

| Section | Purpose |
| --- | --- |
| **Build & preview** | Prepare a snapshot, build an image, and launch the app. |
| **Project overview** | Expand to see the detected language/framework, evidence, plan, and assumptions. |
| **Setup files** | Expand to inspect generated Docker/Compose/CI files and download them individually or as a ZIP. |
| **Check results** | Approve checks when prompted, then expand results to review their output. |

The sidebar lets you reopen previous project reviews. **Refresh** reloads a project's status.

A plan is labelled **AI-generated suggestion** or **Example plan Â· not AI-generated**. A static validation pass means the generated instructions passed those checks; it does not prove an image builds or the app works.

### 3. Build the Docker image

In **Build & preview**:

1. Select **Prepare build snapshot**. This creates a filtered copy of the source plus setup files.
2. Review the setup, then check **I reviewed this setup and approve building this snapshot**.
3. Select **Build my app**.
4. Wait for **Image built and verified**. Open **Build log & technical details** for progress or errors.

The snapshot has a fingerprint so approval applies to that fixed copy. To include source changes, prepare and approve a new snapshot. Builds download dependencies and execute project build instructions with network access; use projects you trust.

### 4. Start and open your app

1. Check **I approve starting this app locally with internet access**.
2. Usually, keep the prefilled settings. Open **Advanced preview settings** if you need to change:
   - **App port:** the port inside the container, not the public browser port.
   - **Health-check path:** a working HTTP endpoint, usually `/`.
   - **Stop automatically after:** 15, 30, 60, or 120 minutes; default 30.
   - **Environment variable:** one optional runtime name/value in the UI.
3. Select **Start local preview**.
4. After the startup HTTP check passes, select **Open my app**. For a FastAPI app without a homepage route, Aidevops links to the API docs at `/docs` and also provides a link to the service root.

The app must listen on `0.0.0.0` inside its container. Aidevops assigns a host port bound to `127.0.0.1`, so the preview is local to this computer. A passing HTTP check establishes basic availability, not complete functionality or security.

The panel refreshes every two seconds during build/start/stop and every ten seconds while a preview is ready. **Stop preview / cancel operation** stops the operation or running container. Expand **Remove preview resources**, confirm removal, then click its button to remove that preview's container, image, and snapshot.

### 5. Run optional project checks

When checks are ready, review the explanation on the project page, check the approval box, then select **Approve & run checks**. Container tests require Docker and may download dependencies and execute app code.

**Checks passed**, **image built**, and **preview ready** are separate results. Running checks does not build a preview image or deploy an app. If no tests were detected, static checks alone cannot establish app correctness.

## Docker monitoring and management

Select **Docker monitoring** in the Streamlit sidebar to see all containers on the Docker Engine available to the backend. The compact overview prioritizes running/stopped/unhealthy totals, container status, CPU, memory, and health. Select a container to see live resource trends; auto-refresh defaults to every five seconds and can be slowed to 15/30 seconds or turned off. Refreshing polls the container list and only the selected running container's stats—logs load on request, and there is no per-container stats fan-out. Charts keep the latest 30 samples; network and block-I/O counters are cumulative.

**Start** and **Stop** are available when appropriate. **Restart** and **Remove** are tucked under **More actions** and require explicit confirmation; removal is limited to stopped containers. Container ports, IDs, and creation details are under **Container information**, and logs stay collapsed until requested. Logs are bounded and recognizable secrets are redacted heuristically, which is not a guarantee that every sensitive value is detected. Container inspection responses do not include environment variables, labels, or other arbitrary Docker metadata.

All management requests go from Streamlit to the authenticated FastAPI `/api/docker` endpoints, then through the backend Docker SDK to the host Engine. The Streamlit frontend does not receive or mount the Docker socket. Access is limited to the configured administrator account (not other registered accounts), and start/stop/restart/remove outcomes are recorded in the SQLite `docker_management_audit` table. Example endpoints include:

- `GET /api/docker/containers` and `GET /api/docker/containers/{container_id}`
- `GET /api/docker/containers/{container_id}/stats` and `/logs`
- `POST /api/docker/containers/{container_id}/start`, `/stop`, or `/restart`
- `DELETE /api/docker/containers/{container_id}`

**Security note:** Docker management gives the configured administrator control over containers on the backend host. Keep both backend and dashboard bound to localhost unless you have separately secured the network, account credentials, and host. Never expose the Docker socket to Streamlit or an untrusted frontend. This feature manages local containers independently from Aidevops project previews; existing preview build/start/cleanup behavior is unchanged.

## AWS deployment and monitoring

The **AWS monitoring** sidebar section reports the configured account identity, EC2 instance state and recent CloudWatch CPU metrics, S3 buckets, and Aidevops deployment records. Refresh defaults to every 30 seconds; choose 60 seconds or turn it off to reduce API requests. Metrics can be delayed or unavailable. For bounded request volume, CPU data is requested only for the first ten running instances. Ask the administrator-only **AI assistant** for EC2 memory utilization; it queries `CWAgent/mem_used_percent` on demand, which requires the CloudWatch Agent to publish that metric.

Use **AWS setup** in the sidebar for a guided real-AWS setup. It recommends an AWS CLI SSO profile on the backend host, shows the non-secret `.env` settings, lists the deployment permission categories, and can test the backend's AWS identity through STS. The page never accepts or stores access keys; the connection test checks identity only, not every deployment permission. If an SSO session expires, run `aws sso login --profile aidevops` on the backend computer and check again; an SSO refresh does not require restarting FastAPI.

After an approved Docker build has produced a verified image, expand **AWS deployment** in that preview. Aidevops recommends **S3** for static sites and **EC2** for server applications such as FastAPI, Flask, Node servers, or Next.js. The recommendation is based on the analyzed project type and the selected path is checked against the built image before publishing. Each deployment requires one confirmation for creating resources and a separate confirmation that the website/service will be publicly reachable.

- **S3:** Copies at most 100 MiB of static files from the verified image into a newly created bucket, uploading up to eight files concurrently, configures website hosting, and allows public `GetObject` access. S3 website endpoints are HTTP. Use only content intended to be public.
- **EC2:** Creates an ECR repository, pushes the verified image, creates a security group allowing public HTTP on port 80, and launches one `t3.micro` instance in the default VPC. Configure a region-compatible AMI and an instance profile with ECR pull access. Before creating resources, Aidevops verifies that the AMI is available and x86_64-compatible and that the instance role can pull from ECR. LocalStack must also include ECR in its active license; otherwise EC2 deployments will be rejected before resources are created. The app may take a few minutes to start after the instance launches.
- **Choosing a target:** S3 hosts extracted static website files; it cannot run a Docker container or server process. Use EC2 for containerized backend/server applications.
- **Cost and cleanup:** AWS resources can incur charges. Aidevops does not currently stop or delete successful cloud deployments; manage them in the AWS console. Failed operations attempt to remove resources they created, but permission or service failures can prevent cleanup. Check resources tagged by Aidevops before retrying.

The backend defaults to **LocalStack only**, at `http://localhost:4566`, using dummy credentials. It never falls back to real AWS. This is an AWS API endpoint, not a browser console; opening its root may show `Not Found`. Check LocalStack health at `http://localhost:4566/_localstack/health`. Start LocalStack and set `AIDEVOPS_AWS_ENDPOINT_URL` if its endpoint differs. The LocalStack account ID (usually `000000000000`) is an emulator identity, not a real AWS account. When signing in, use the same hostname for the dashboard and login page (for example, `localhost` for both, not `localhost` for one and `127.0.0.1` for the other).

The current LocalStack `us-east-1` configuration uses the emulator's AL2023 x86_64 AMI (`ami-07518cc94bb750af3`) and a local ECR-pull instance profile (`arn:aws:iam::000000000000:instance-profile/aidevops-localstack-ecr-pull`). These are configured in the ignored local `.env`, with the matching role/profile in LocalStack. They are not real AWS resources and must not be used after switching to real AWS mode. EC2 deployment remains approval-gated.

Real AWS is opt-in. Set `AIDEVOPS_AWS_MODE=aws` on the backend, set `AWS_PROFILE` to a configured non-secret profile name if needed, set the region, and configure credentials through the normal AWS SDK credential chain on that host (for example, an IAM role or AWS CLI SSO profile). Do not put access keys in the UI, source code, or `.env`. EC2 additionally needs a region-compatible Amazon Linux 2023 AMI and:

```dotenv
AIDEVOPS_AWS_EC2_AMI_ID=ami-0123456789abcdef0
AIDEVOPS_AWS_EC2_INSTANCE_PROFILE_ARN=arn:aws:iam::123456789012:instance-profile/aidevops-ecr-pull
```

Attach the AWS-managed `AmazonEC2ContainerRegistryReadOnly` policy to the IAM role in that instance profile so EC2 can pull the image. This is separate from the backend AWS profile. The backend profile must also be allowed to call `ec2:DescribeImages`, `iam:GetInstanceProfile`, and `iam:SimulatePrincipalPolicy` for the deployment preflight, plus `ecr:DescribeImages` to verify the image push, in addition to the deployment permissions listed in the AWS setup page. A failed preflight explains the missing configuration and stops before creating AWS resources.

Only the configured administrator can access `/api/aws` and `/api/aws/infra`. The dashboard never receives AWS credentials. The backend uses typed AWS SDK calls rather than arbitrary shell commands. Deployment endpoints include `GET /api/aws/status`, `GET /api/aws/overview`, `GET /api/aws/deployments`, `GET /api/aws/previews/{preview_id}/recommendation`, and the separately approved `POST /api/aws/previews/{preview_id}/deploy`. Infrastructure endpoints provide EC2 listing/details/actions, metrics, cost reports, audited SSM Docker actions, and audit history.

## AWS management dashboard

Select **AWS management** in the sidebar for EC2 instance details and lifecycle controls, on-demand CloudWatch CPU/memory/network/block-I/O metrics, Cost Explorer `UnblendedCost` data, and an administrator-only audit log. Cost Explorer data is delayed and can differ from the final bill, including credits and taxes. The page uses manual refresh; metrics, costs, and audit records load only when requested. Instance creation and termination require explicit confirmation. Configure the backend profile with scoped EC2 read/write permissions, `cloudwatch:GetMetricStatistics`, and `ce:GetCostAndUsage`.

The dashboard can send a fixed set of remote Docker actions through Systems Manager: list containers, retrieve bounded logs, start, stop, restart, remove, and deploy a container from an ECR image. This requires an online SSM Agent and an EC2 instance profile with `AmazonSSMManagedInstanceCore`; ECR pulls additionally require `AmazonEC2ContainerRegistryReadOnly`. Container removal and deployment require explicit confirmation, and deployment also requires confirming the possible exposure through the instance security group. No arbitrary command, environment-variable inspection, or Docker socket is exposed. SSM output is redacted heuristically and should still be treated as potentially sensitive.

The assistant supports these exact, administrator-only command forms for these operations:

```text
aws start i-0123456789abcdef0
aws stop i-0123456789abcdef0
aws reboot i-0123456789abcdef0
aws terminate i-0123456789abcdef0
aws docker list i-0123456789abcdef0
aws docker logs i-0123456789abcdef0 aaaaaaaaaaaa
aws docker restart i-0123456789abcdef0 aaaaaaaaaaaa
aws docker deploy i-0123456789abcdef0 123456789012.dkr.ecr.us-east-1.amazonaws.com/web:latest web 8080 80
aws metrics i-0123456789abcdef0
aws costs 2026-11-10 2026-11-17 daily
```

For permanent or externally reachable actions, the assistant first returns the exact confirmation command to send next, such as `aws confirm terminate i-0123456789abcdef0`, `aws docker confirm remove i-0123456789abcdef0 aaaaaaaaaaaa`, or the same deploy command prefixed with `aws docker confirm`. SSM Docker deploy details and command output are managed in **AWS management**.

## Supported projects

Detection and generation use project files and conventions; arbitrary projects are not guaranteed to run automatically.

| Project | Current strategy |
| --- | --- |
| Create React App / Vite | Build browser assets, then serve with Nginx on container port 8080. |
| Next.js | Production build and Node server, normally port 3000. |
| Node.js server | Uses declared start/main and supported build scripts. |
| FastAPI / Flask | Detects app objects and generates a web-server launch command. |
| Django / Streamlit | Convention-based launch strategies. |
| Static HTML | Serves an `index.html` project without a package manifest. |
| Existing Dockerfile | Preserves it for review and build use. |

CRA, Vite, static HTML, Flask, FastAPI, and Node paths have recorded live Docker checks. Other strategies have narrower verification; see [implementation status](docs/IMPLEMENTATION_STATUS.md).

A single nested app can be selected automatically. For repositories containing multiple apps, select the intended app folder. Databases, private packages, custom build layouts, missing credentials, unsupported runtimes, and invalid app code can require configuration or your own Dockerfile. Database provisioning and multi-service deployment are not automatic.

## Configuration and AI privacy

See [.env.example](.env.example) for the full list. Common settings:

| Variable | Default / meaning |
| --- | --- |
| `AIDEVOPS_DATA_DIR` | `data`; persistent application data. |
| `AIDEVOPS_ALLOW_LOCAL_PATHS` | `true`; permits folder-based reviews. |
| `AIDEVOPS_EXEC_BACKEND` | `auto`; container checks run if Docker is available. `disabled` blocks container check tools and new preview snapshots; stop existing previews separately. |
| `AIDEVOPS_EXEC_TIMEOUT_SECONDS` | `120`; normal tool timeout. |
| `AIDEVOPS_BUILD_TIMEOUT_SECONDS` | `600`; separate image-build timeout, capped at 1800 seconds. |
| `AIDEVOPS_AWS_MODE` | `localstack`; set to `aws` explicitly to allow the AWS SDK credential chain. |
| `AWS_PROFILE` | Optional non-secret AWS CLI profile name; configure the profile on the backend host, not in the dashboard. |
| `AIDEVOPS_AWS_ENDPOINT_URL` | `http://localhost:4566`; LocalStack endpoint; ignored in explicit AWS mode. |
| `AIDEVOPS_AWS_REGION` | `us-east-1`; AWS/LocalStack region. |
| `AIDEVOPS_AWS_EC2_AMI_ID` | Required for EC2 deployment; use an Amazon Linux 2023 AMI available in the configured region. |
| `AIDEVOPS_AWS_EC2_INSTANCE_PROFILE_ARN` | EC2 deployment/management profile; its role needs ECR read for image pulls and SSM Core for remote management. |
| `AIDEVOPS_LOCAL_ONLY` | `false`; set `true` to disable external AI requests. |
| `AIDEVOPS_AI_ALLOWED_HOSTS` | Permitted HTTPS AI destinations; defaults include OpenAI, OpenRouter, Anthropic, and Groq. |
| `OPENAI_API_KEY` | Empty by default; enables external AI planning and the dashboard assistant. |
| `ANTHROPIC_API_KEY` | Optional Anthropic key; choose `AIDEVOPS_LLM_PROVIDER=anthropic` to use Claude. |
| `GROQ_API_KEY` | Optional Groq key; choose `AIDEVOPS_LLM_PROVIDER=groq` to use Groq. |
| `OPENAI_MODEL` | Provider model identifier; see the repository defaults in `.env.example`. |
| `OPENAI_BASE_URL` | Optional compatible provider endpoint; must pass the destination policy. |
| `GROQ_MODEL` | Groq model identifier; defaults to `openai/gpt-oss-20b`. |
| `GROQ_BASE_URL` | Groq-compatible API endpoint; defaults to `https://api.groq.com/openai/v1`. |
| `AIDEVOPS_API_URL` | Frontend backend address; the Quick start command sets it to `http://127.0.0.1:8000`. |

To enable external planning, edit the provider fields in `.env`, set `AIDEVOPS_LOCAL_ONLY=false`, and restart the backend. `AIDEVOPS_LLM_PROVIDER` accepts `openai`, `anthropic`, or `groq`; when omitted, it selects a provider based on available keys. Provider/model compatibility varies. `/health` reporting `llm_mode: "live"` means configured, not proof that a provider request succeeded. Check each plan's label; failures may fall back to an example plan.

For no external AI requests, put this in `.env` and restart the backend:

```dotenv
AIDEVOPS_LOCAL_ONLY=true
```

This disables external AI only. Docker builds, package downloads, and running apps can still access the network.

### What is protected, and what needs care

- Analysis does not execute project code; known sensitive paths and symlinks are excluded.
- AI requests pass through filtering/redaction and a permitted HTTPS destination check. Open **Privacy Â· see what is sent to AI** to inspect the filtered request after analysis. This is not a consent screen before the original request.
- Secret filtering is heuristic. Unusual filenames, unknown token formats, or sensitive source content can escape detection. Use local-only mode when external AI transmission is unsuitable.
- Model-proposed commands are advisory. Registered tools and explicit approvals control execution.
- Preview containers have resource limits and security restrictions. The Docker socket is not mounted into the app container. This is a local development tool, not a complete sandbox for hostile code.
- Runtime environment values are not sent to AI or saved in review records. Docker can retain them in container metadata until removal. Runtime app logs are withheld in the UI because apps can print secrets; filtered build logs remain available.
- AWS and Docker management are restricted to the configured administrator. Keep the service on loopback unless you separately secure the network, account credentials, and deployment environment; it is not a public multi-tenant control plane.

Read [SECURITY.md](docs/SECURITY.md) for the full boundaries and limitations.

### Where files are stored

With default settings:

| Location | Contents |
| --- | --- |
| `data/aidevops.db` | Project reviews and their state. |
| `data/aws_management.db` | AWS deployment records and infrastructure-operation audit logs. |
| `data/generated/<JOB_ID>/` | Generated setup files. |
| `data/previews.db` | Preview state and build records. |
| `data/previews/` | Preview snapshots and worker lock. |

Treat these as local project data. Do not delete the data directory as a routine troubleshooting step. Use the UI's resource-removal controls for previews.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `.venv\Scripts\python.exe` cannot be found | Paste the Quick start block from the project folder or its parent. Confirm Python 3.11 or newer is installed. |
| `ModuleNotFoundError` | Run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` from the project directory. |
| Backend is offline in the UI | Check the FastAPI window and open `http://127.0.0.1:8000/health`. Confirm the dashboard uses `http://127.0.0.1:8000` as its backend. |
| Port 8000 or 8501 is already in use | The Quick start block reuses services already listening on those ports. If they belong to another application, stop that app or close its server window before starting Aidevops. |
| Docker is unavailable | Start Docker Desktop with Linux containers, wait for `docker version` to show Server information, then restart the backend and refresh. |
| Another preview worker owns the data directory | Stop duplicate backend processes gracefully. Run one backend for that directory; deleting the lock file is not a substitute. |
| Upload rejected | Check the backend size limit, archive format, and excluded/unsafe files. Try the local source folder instead. |
| Project type is unknown / several apps detected | Select the actual app folder containing its manifest or entry point, or supply a suitable Dockerfile. |
| Image build fails | Read **Build log & technical details**. Check dependency access, build scripts, missing files, and Dockerfile assumptions. Fix the source and create a new review/snapshot. |
| Build times out | Increase `AIDEVOPS_BUILD_TIMEOUT_SECONDS` within its maximum, restart the backend, and retry the reviewed snapshot. |
| Image builds but preview fails | Check the internal port, a valid HTTP path, `0.0.0.0` binding, and required runtime settings/services. |
| AI plan is labelled as an example | Check provider configuration and local-only mode. The label is intentional; a configured key does not guarantee a successful model response. |
| Old UI or Dockerfile remains | Close and restart both service windows, then refresh. Create a new review to generate updated setup files. |
| Snapshot limit reached | Remove unused preview resources through the UI. The service currently permits 20 unremoved snapshots and two active operations. |

## API example (PowerShell)

The UI is the easiest starting point. For scripting, start the backend and run the following in another PowerShell terminal:

```powershell
cd E:\Aidevops
$apiBase = "http://127.0.0.1:8000"
$samplePath = (Resolve-Path .\examples\sample_python_app).Path
$createBody = @{ source_path = $samplePath } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs" -ContentType "application/json" -Body $createBody
$jobId = $job.id

# Analyze, plan, generate, and validate.
$review = Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs/$jobId/run"
$review | Select-Object id, state, project_name

# Inspect generated files before approving execution.
$setup = Invoke-RestMethod -Uri "$apiBase/api/jobs/$jobId/artifacts"
$setup.artifacts | Select-Object path, kind, verified
```

After reviewing the setup, this separate command approves the registered checks. It does not build a preview image:

```powershell
$approvalBody = @{ approved = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs/$jobId/execute" -ContentType "application/json" -Body $approvalBody
```

Use [the API reference](http://localhost:8000/docs) for upload, cancellation, sanitized prompt inspection, and separate preview snapshot/build/start/stop/cleanup endpoints. Build approval includes the snapshot digest; startup requires its own approval.

## Tests and developer documentation

Run automated tests from the repository root:

```powershell
cd E:\Aidevops
.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs
```

Latest full-suite verification on **27 November 2026 (India time): 192 passed, 3 skipped**. One skipped test needs Windows symlink privileges; the Docker Engine and LocalStack integration checks are opt-in. The LocalStack STS integration passed separately against the running local service; Docker integration was not run. The suite includes 29 Streamlit UI tests, 10 mocked Docker-management tests, and 20 mocked AWS-management tests; ordinary tests use isolated data and fake external services rather than proving every uploaded app builds.

Optional integration checks below start temporary services and perform real Docker work. They may download dependencies and take longer; inspect their scripts before running:

```powershell
.\.venv\Scripts\python.exe tests/smoke_local.py
.\.venv\Scripts\python.exe tests/smoke_preview.py
.\.venv\Scripts\python.exe tests/smoke_frontends.py
```

The Docker dashboard's real-Engine listing smoke is separate and read-only; it is skipped by default:

```powershell
$env:AIDEVOPS_DOCKER_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_docker_integration.py -o addopts="" -rs
Remove-Item Env:AIDEVOPS_DOCKER_INTEGRATION
```

The AWS integration check is read-only and contacts LocalStack STS only. It is skipped by default and will not use real AWS:

```powershell
$env:AIDEVOPS_AWS_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_aws_integration.py -o addopts="" -rs
Remove-Item Env:AIDEVOPS_AWS_INTEGRATION
```

| Document | Purpose |
| --- | --- |
| [Project memory](PROJECT_MEMORY.md) | Contributor handoff and verification context. |
| [Architecture](docs/ARCHITECTURE.md) | Components and data flow. |
| [Implementation status](docs/IMPLEMENTATION_STATUS.md) | Feature coverage and verification limits. |
| [Testing](docs/TESTING.md) | Tests and recorded evidence. |
| [Security](docs/SECURITY.md) | Privacy, execution boundaries, and known risks. |
| [Tool registry](docs/TOOL_REGISTRY.md) | Allowlisted execution tools. |
| [Decisions](docs/DECISIONS.md) | Design decisions. |
| [Changelog](docs/CHANGELOG.md) | Change history. |
| [Roadmap](docs/ROADMAP.md) | Planned work. |

Kubernetes management, automatic database provisioning, multi-user authorization, cloud-resource stop/delete controls, and autonomous recovery/rollback are not implemented.

### Legacy prototype

`app.py`, `rag.py`, `generator.py`, and `knowledge/` belong to the older notes-retrieval prototype. They are separate from the main Aidevops workspace. To explore it, use another free UI port:

```powershell
cd E:\Aidevops
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```
