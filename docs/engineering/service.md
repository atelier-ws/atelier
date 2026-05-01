# HTTP Service

Atelier includes an optional FastAPI HTTP service that exposes all runtime operations over HTTP. It is disabled by default — the MCP server (stdio) and CLI are the primary interfaces.

## When to Use the HTTP Service

- Remote MCP mode: run one Atelier instance shared across multiple machines
- React dashboard access (frontend reads the service)
- External tools or scripts that can't use stdio MCP
- Staging/production multi-agent environments

## Starting the Service

```bash
# Development (no auth)
ATELIER_SERVICE_ENABLED=true ATELIER_REQUIRE_AUTH=false make service
# → http://localhost:8787
# → http://localhost:8787/docs  (Swagger UI)

# With API key
ATELIER_SERVICE_ENABLED=true ATELIER_API_KEY=my-secret-key make service
```

Environment variables:

| Variable                  | Default     | Description                           |
| ------------------------- | ----------- | ------------------------------------- |
| `ATELIER_SERVICE_ENABLED` | `false`     | Must be `true` to start service       |
| `ATELIER_SERVICE_HOST`    | `127.0.0.1` | Bind host                             |
| `ATELIER_SERVICE_PORT`    | `8787`      | Port                                  |
| `ATELIER_REQUIRE_AUTH`    | `true`      | Require `Authorization: Bearer <key>` |
| `ATELIER_API_KEY`         | `""`        | API key                               |

## Endpoints

### Ops

| Method | Path       | Description                    |
| ------ | ---------- | ------------------------------ |
| `GET`  | `/health`  | Liveness probe                 |
| `GET`  | `/ready`   | Readiness probe (checks store) |
| `GET`  | `/metrics` | Basic metrics                  |

### Reasoning

| Method | Path                       | Description           |
| ------ | -------------------------- | --------------------- |
| `POST` | `/v1/reasoning/context`    | Get reasoning context |
| `POST` | `/v1/reasoning/check-plan` | Validate a plan       |
| `POST` | `/v1/reasoning/rescue`     | Get rescue procedure  |

### Rubrics

| Method | Path              | Description          |
| ------ | ----------------- | -------------------- |
| `GET`  | `/v1/rubrics`     | List rubrics         |
| `POST` | `/v1/rubrics`     | Create/update rubric |
| `POST` | `/v1/rubrics/run` | Run a rubric gate    |

### Traces

| Method | Path                     | Description        |
| ------ | ------------------------ | ------------------ |
| `POST` | `/v1/traces`             | Record a trace     |
| `POST` | `/v1/traces/{id}/events` | Add event to trace |
| `POST` | `/v1/traces/{id}/finish` | Finalize a trace   |

### ReasonBlocks

| Method  | Path                    | Description         |
| ------- | ----------------------- | ------------------- |
| `GET`   | `/v1/reasonblocks`      | List/search blocks  |
| `POST`  | `/v1/reasonblocks`      | Create/update block |
| `PATCH` | `/v1/reasonblocks/{id}` | Update block status |

### Environments

| Method | Path               | Description                 |
| ------ | ------------------ | --------------------------- |
| `GET`  | `/v1/environments` | List reasoning environments |
| `POST` | `/v1/environments` | Create environment          |

### Evals

| Method | Path            | Description        |
| ------ | --------------- | ------------------ |
| `GET`  | `/v1/evals`     | List eval cases    |
| `POST` | `/v1/evals/run` | Run evals (queued) |

### Extract & Failures

| Method | Path                      | Description              |
| ------ | ------------------------- | ------------------------ |
| `POST` | `/v1/extract/reasonblock` | Extract block from trace |
| `POST` | `/v1/failures/analyze`    | Cluster failure traces   |

### Metrics

| Method | Path                  | Description                |
| ------ | --------------------- | -------------------------- |
| `GET`  | `/v1/metrics/savings` | Token/call savings summary |

## Authentication

When `ATELIER_REQUIRE_AUTH=true` (default), all `/v1/*` requests must include:

```
Authorization: Bearer <ATELIER_API_KEY>
```

Health/ready/metrics endpoints are unauthenticated.

For development, set `ATELIER_REQUIRE_AUTH=false` to skip auth entirely.

## Remote MCP Mode

To run agents in remote mode (MCP server forwards to HTTP service):

```bash
# 1. Start the service
ATELIER_SERVICE_ENABLED=true ATELIER_API_KEY=dev-key make service

# 2. Run agents with remote MCP
ATELIER_MCP_MODE=remote \
ATELIER_SERVICE_URL=http://localhost:8787 \
ATELIER_API_KEY=dev-key \
uv run atelier-mcp
```

## Swagger UI

When running the service, full API docs are available at:

```
http://localhost:8787/docs
```
