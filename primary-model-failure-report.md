# Primary Model Failure Report

Generated: 2026-05-27

## Summary

Hermes is currently configured to use `openai-codex` as the primary provider with model `gpt-5.5` and base URL `https://chatgpt.com/backend-api/codex`.

The recent logs show a real reliability problem on that primary path. Across the retained error logs, there were 104 primary `openai-codex` / `gpt-5.5` API call failures between `2026-05-26 16:13:17` and `2026-05-27 14:26:25`.

The failures are not one single symptom. They break down into backend hangs, upstream 503s, adapter/client `TypeError`s, and invalid request payload errors.

## Current Configuration

Primary model config from `/home/shvdxw/.hermes/config.yaml`:

```yaml
model:
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.5
  provider: openai-codex
  openai_runtime: codex_app_server
fallback_providers: []
```

Auxiliary goal judging is configured for OpenRouter Owl Alpha:

```yaml
goal_judge:
  provider: openrouter
  model: openrouter/owl-alpha

goal_slice_judge:
  provider: openrouter
  model: openrouter/owl-alpha
```

Important mismatch: OpenRouter Owl Alpha is only configured for specific auxiliary judging tasks. It is not the primary chat model. Also, `fallback_providers` is empty, so primary `openai-codex` failures do not automatically fail over to OpenRouter.

## Failure Counts

Observed primary `openai-codex` / `gpt-5.5` API call failures:

| Failure type | Count | Notes |
|---|---:|---|
| `APIConnectionError` | 63 | Mostly stale/hung calls killed by Hermes after timeout. |
| `TypeError` | 34 | Logged as `'NoneType' object is not iterable`; treated as non-retryable client errors. |
| `BadRequestError` | 5 | Invalid `input[N].name` values rejected by Codex backend. |
| `InternalServerError` | 2 | HTTP 503 upstream connect/reset errors. |
| Total | 104 | 2 on 2026-05-26, 102 on 2026-05-27. |

Related transport symptoms:

| Symptom | Count |
|---|---:|
| Non-streaming call stale for 300s, connection killed | 61 |
| Stream accepted but produced no bytes for 45s | 2 |
| HTTP 503 upstream connect/reset | 2 |
| Invalid input name request rejection | 5 |

## Dandelion Telegram Session

Session `20260527_130334_64d62013` had repeated transient agent failures while responding to Dandelion's provider-check messages:

| Time | Event |
|---|---|
| 2026-05-27 13:42:16 | `TypeError: 'NoneType' object is not iterable`; gateway marked transient failure. |
| 2026-05-27 13:55:57 | Same `TypeError`; gateway marked transient failure. |
| 2026-05-27 14:00:30 | Same `TypeError`; gateway marked transient failure. |
| 2026-05-27 14:06:50 | Same `TypeError`; gateway marked transient failure. |
| 2026-05-27 14:13:59 | Same `TypeError`; gateway marked transient failure. |

The gateway did still send short responses for those turns, but it also logged: "Transient agent failure ... persisting user message so conversation context is preserved on retry." That means the user-facing response path was degraded even when a response made it out.

## Notable Log Evidence

Representative primary model failures:

```text
2026-05-26 16:13:17 WARNING provider=openai-codex model=gpt-5.5 error_type=InternalServerError summary=HTTP 503: upstream connect error or disconnect/reset before headers
2026-05-27 00:05:10 WARNING Non-streaming API call stale for 300s. model=gpt-5.5. Killing connection.
2026-05-27 13:42:16 WARNING provider=openai-codex model=gpt-5.5 error_type=TypeError summary='NoneType' object is not iterable
2026-05-27 14:23:54 WARNING Codex stream produced no bytes within TTFB cutoff (45s > 45s, model=gpt-5.5)
2026-05-27 14:24:00 ERROR Non-retryable client error: 'NoneType' object is not iterable
```

Representative invalid request failures:

```text
2026-05-27 12:53:16 WARNING provider=openai-codex model=gpt-5.5 error_type=BadRequestError summary=HTTP 400: Invalid 'input[274].name'
2026-05-27 13:09:10 WARNING provider=openai-codex model=gpt-5.5 error_type=BadRequestError summary=HTTP 400: Invalid 'input[11].name'
```

OpenRouter was not completely clean either, but it was much less prominent in the retained logs:

```text
2026-05-27 12:53:33 WARNING provider=openrouter model=openrouter/owl-alpha error_type=APIError summary=Provider returned error
```

## Interpretation

The primary issue is the active primary provider path: `openai-codex` / `gpt-5.5`.

The largest class of failures is backend non-responsiveness: requests accepted or started, then no useful response arrived before Hermes killed the connection. The second major class is a local/provider adapter failure where a `None` value is being iterated. Since Hermes logs that as a non-retryable client error, those turns do not get the same retry handling as connection failures.

The invalid `input[N].name` failures point to malformed tool/function-call payload names being sent to the Codex backend. That is likely an adapter/request-shaping bug or an upstream incompatibility with a generated message/tool item, not a network issue.

## Impact

- Primary model reliability was poor on 2026-05-27.
- Several Telegram turns for Dandelion were marked transiently failed even though short responses were sent.
- Long-running/background activity likely amplified the issue: many failures were stale 300s calls, and the logs show background review/compression activity using the same primary provider.
- Because `fallback_providers` is empty, failures on `openai-codex` remain on that path instead of being routed to OpenRouter.

## Recommendations

1. If the desired policy is "only OpenRouter Owl Alpha", change the primary `model` block to OpenRouter rather than only configuring auxiliary judges.
2. Add a fallback provider if primary Codex should remain enabled but degraded gracefully.
3. Investigate the `NoneType` path in the Codex transport/response adapter because it is classified as non-retryable and is hitting live Telegram turns.
4. Investigate/sanitize generated `input[N].name` values before sending to Codex; the backend requires `^[a-zA-Z0-9_-]+$`.
5. Consider moving background review/compression off the primary provider during incidents, because stale 300s calls consume the same backend path.

## Source Logs Reviewed

- `/home/shvdxw/.hermes/logs/errors.log`
- `/home/shvdxw/.hermes/logs/errors.log.1`
- `/home/shvdxw/.hermes/logs/errors.log.2`
- `/home/shvdxw/.hermes/logs/gateway.log`
- `/home/shvdxw/.hermes/config.yaml`
