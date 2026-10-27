# vercel/next.js#91655 is not fixed for the standalone server

This repository reproduces an OpenTelemetry warning that Next.js 16.2.0 and later log once per
request. [vercel/next.js#91655](https://github.com/vercel/next.js/issues/91655) was closed as fixed,
but the warning still occurs on 16.4.3 and on 16.5.0-canary.28. It happens when the app runs from
`output: 'standalone'` (or `next start`) with `@opentelemetry/instrumentation-http` active:

```
Cannot execute the operation on ended Span {traceId: …, spanId: …} Error: Operation attempted on ended Span {traceId: …, spanId: …}
    at SpanImpl._isSpanEnded (…/@opentelemetry/sdk-trace/dist/Span.cjs:234:34)
    at SpanImpl.setAttribute (…/@opentelemetry/sdk-trace/dist/Span.cjs:77:12)
    at <unknown> (node_modules/next/dist/server/base-server.js:539:44)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async invokeRender (node_modules/next/dist/server/lib/router-server.js:363:21)
    at async handleRequest (node_modules/next/dist/server/lib/router-server.js:567:24)
    at async requestHandlerImpl (node_modules/next/dist/server/lib/router-server.js:636:13)
    at async Server.requestListener (node_modules/next/dist/server/lib/start-server.js:210:13)
```

Without `__NEXT_SHOW_IGNORE_LISTED=true`, the Next.js frames appear only as `at ignore-listed frames`.

The app uses only the OpenTelemetry Node SDK (`@opentelemetry/sdk-node`) and
`@opentelemetry/instrumentation-http`. No vendor distribution of OpenTelemetry is involved.

## Cause

In `BaseServer.handleRequest`
([`packages/next/src/server/base-server.ts` at v16.4.3](https://github.com/vercel/next.js/blob/v16.4.3/packages/next/src/server/base-server.ts#L911-L1005)),
Next.js saves the active span as `parentSpan` before it starts its own `handleRequest` span (line 911).
When the request is complete, inside `this.handleRequestImpl(req, res, parsedUrl).finally(…)`
(line 951), it writes the route to that parent span (line 1005):

```ts
if (parentSpan && parentSpan !== span) {
  parentSpan.setAttribute('http.route', route)
}
```

When `@opentelemetry/instrumentation-http` is active, `parentSpan` is its HTTP server span.
`instrumentation-http` ends that span when the response closes, which is before the `.finally()`
callback runs. The OpenTelemetry SDK ignores the write and logs the warning through `diag.warn`.

## History

| Date | Change |
|---|---|
| 2026-03-03 | [#90832](https://github.com/vercel/next.js/pull/90832), "[otel] fix missing http.route attribute", adds the `parentSpan.setAttribute('http.route', route)` call. The first release tag that contains it is `v16.2.0-canary.74`. |
| 2026-03-19 | [#91655](https://github.com/vercel/next.js/issues/91655), "Opentelemetry warnings since v16.2.0", reports the warning on every request. |
| 2026-09-02 | #91655 is closed as fixed. The maintainer's comment reports 0 warnings on 16.3.2 and 16.4.0-canary.5 and names [#91665](https://github.com/vercel/next.js/pull/91665), [#94603](https://github.com/vercel/next.js/pull/94603) and [#94817](https://github.com/vercel/next.js/pull/94817) as the fixes. The issue was later locked. |

The three fixes change the build templates (`packages/next/src/build/templates/app-page.ts`,
`app-route.ts`, `pages-api.ts`, `edge-ssr*.ts`) and `pages-handler.ts`. Those files are used when a
platform calls a route's `handler` export directly, without `BaseServer`. None of the three changes
`base-server.ts`, and the `parentSpan.setAttribute('http.route', route)` call is still present in the
published builds of 16.4.3 and 16.5.0-canary.28. The standalone server and `next start` both run
`BaseServer.handleRequest`.

## Results

20 requests to each route, Node.js 24.13.0, `@opentelemetry/sdk-node` 0.300.0,
`@opentelemetry/instrumentation-http` 0.300.0, `@opentelemetry/sdk-trace-base` 2.12.0:

| Next.js | SDK started from | instrumentation-http SERVER spans | Warnings `/` | Warnings `/api/ping/` |
|---|---|---|---|---|
| 16.4.3 | `instrumentation.ts` | 41 | 20 / 20 | 20 / 20 |
| 16.4.3 | `node --require ./otel.cjs` | 41 | 20 / 20 | 20 / 20 |
| 16.5.0-canary.28 | `instrumentation.ts` | 41 | 20 / 20 | 20 / 20 |
| 16.5.0-canary.28 | `node --require ./otel.cjs` | 41 | 20 / 20 | 20 / 20 |
| 16.1.7 | `instrumentation.ts` | 41 | 0 / 20 | 0 / 20 |
| 16.1.7 | `node --require ./otel.cjs` | 41 | 0 / 20 | 0 / 20 |

16.1.7 is the last release before #90832. It has the same HTTP server spans and no warnings, because
it doesn't write to the parent span.

The [Reproduce workflow](../../actions/workflows/reproduce.yml) runs the same six cases on each push to
`main`, weekly, and on demand. Each job writes its results to the job summary.

## Running it

Requires Node.js 24, [Bun](https://bun.sh) 1.4 and Python 3.10 or later.

```sh
python3 scripts/reproduce.py                        # Next.js 16.4.3, SDK started from instrumentation.ts
python3 scripts/reproduce.py --preload              # SDK started with node --require ./otel.cjs
python3 scripts/reproduce.py --next 16.1.7          # control: the last release before #90832
python3 scripts/reproduce.py --next canary          # the current canary
```

The script installs dependencies, runs `next build`, starts `.next/standalone/server.js`, sends the
requests, and prints the table row, the span counts and the first warning. `--next` builds a copy of
the app under `.work/`, so the checkout is left unchanged.

## Files

- `app/page.tsx`, `app/api/ping/route.ts`: one dynamic page and one route handler.
- `next.config.mjs`: `output: 'standalone'`.
- `otel-setup.js`: starts `NodeSDK` with only `HttpInstrumentation`, sets the diagnostic logger to
  `WARN` so that the warning prints, and counts finished spans by instrumentation scope.
- `instrumentation.ts`: loads `otel-setup.js` from Next.js's `register()` hook.
- `otel.cjs`: loads `otel-setup.js` through `node --require`, before Next.js starts.

`otel-setup.js` calls `require('node:http')` after the SDK starts. `instrumentation-http` patches
`http` the next time a module requires it, and when the SDK starts from `instrumentation.ts`, Next.js
has already required `http`. In an application, modules loaded later (error reporters, database
clients, HTTP clients) do this. An app with two routes has no such module, so without this line no
HTTP server span exists, `parentSpan` is the Next.js span itself, and nothing is logged.

## Possible fixes

- Write `http.route` to the parent span only while it is still recording:
  `if (parentSpan && parentSpan !== span && parentSpan.isRecording())`. `Span.isRecording()` returns
  `false` after a span ends. This removes the warning, but the parent span still doesn't receive
  `http.route`.
- Write `http.route` to the parent span when the route is resolved, before the response is sent, so
  that the parent span receives it while it is open.
