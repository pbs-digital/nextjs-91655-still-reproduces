# vercel/next.js#91655 still reproduces

[vercel/next.js#91655](https://github.com/vercel/next.js/issues/91655) ("Opentelemetry warnings since
v16.2.0") was closed as fixed, but the warning it reports still occurs on `next@canary`
(16.5.0-canary.28) and on 16.4.3. This app was created with
`npx create-next-app --example reproduction-template`, and it adds only:

- `@opentelemetry/api`, `@opentelemetry/sdk-node` and `@opentelemetry/instrumentation-http`;
- `app/api/ping/route.ts`, a route handler that returns JSON;
- `instrumentation.ts`, which starts the OpenTelemetry Node SDK with only the HTTP instrumentation.

No vendor distribution of OpenTelemetry is involved.

## Steps

```sh
npm ci
npm run build
npm start
```

In another terminal:

```sh
for i in $(seq 20); do curl -s -o /dev/null http://localhost:3000/api/ping; done
```

The server logs one warning per request:

```
Cannot execute the operation on ended Span {traceId: …, spanId: …} Error: Operation attempted on ended Span {traceId: …, spanId: …}
    at sW._isSpanEnded (.next/server/chunks/[root-of-the-server]__0rpcu2p8zs0eq._.js:18:16979)
    at sW.setAttribute (.next/server/chunks/[root-of-the-server]__0rpcu2p8zs0eq._.js:18:13305)
    at ignore-listed frames
```

With `__NEXT_SHOW_IGNORE_LISTED=true npm start`, the Next.js frames are shown:

```
    at <unknown> (node_modules/next/dist/server/base-server.js:542:44)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async invokeRender (node_modules/next/dist/server/lib/router-server.js:363:21)
    at async handleRequest (node_modules/next/dist/server/lib/router-server.js:566:24)
    at async requestHandlerImpl (node_modules/next/dist/server/lib/router-server.js:635:13)
    at async Server.requestListener (node_modules/next/dist/server/lib/start-server.js:210:13)
```

`package-lock.json` locks `next@canary` to 16.5.0-canary.28. To test a newer canary, run
`npm install next@canary` before building.

## Results

20 requests to each route per run, Node.js 24.13.0, `next start`:

| Next.js | `/api/ping` | `/` | Runs |
|---|---|---|---|
| 16.5.0-canary.28 | 20 / 20 | 0 / 20 | 3 |
| 16.4.3 | 20 / 20 | 0 / 20 | 2 |
| 16.1.7 | 0 / 20 | 0 / 20 | 2 |

16.1.7 is the last release before [#90832](https://github.com/vercel/next.js/pull/90832), which added
the code that causes the warning.

On page requests the warning depends on timing. The template's page (`/`) logged no warnings in
these runs. An earlier version of this reproduction, with a dynamic page, logged warnings on 2 to 8
of 20 page requests on GitHub Actions runners. The route handler logs the warning on every request.

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
callback runs. The OpenTelemetry SDK ignores the write and logs the warning.

## History

| Date | Change |
|---|---|
| 2026-03-03 | [#90832](https://github.com/vercel/next.js/pull/90832), "[otel] fix missing http.route attribute", adds the `parentSpan.setAttribute('http.route', route)` call. The first release tag that contains it is `v16.2.0-canary.74`. |
| 2026-03-19 | [#91655](https://github.com/vercel/next.js/issues/91655) reports the warning on every request. |
| 2026-09-02 | #91655 is closed as fixed. The maintainer's comment reports 0 warnings on 16.3.2 and 16.4.0-canary.5 and names [#91665](https://github.com/vercel/next.js/pull/91665), [#94603](https://github.com/vercel/next.js/pull/94603) and [#94817](https://github.com/vercel/next.js/pull/94817) as the fixes. The issue was later locked. |

The three fixes change the build templates (`packages/next/src/build/templates/app-page.ts`,
`app-route.ts`, `pages-api.ts`, `edge-ssr*.ts`) and `pages-handler.ts`, which are used when a platform
calls a route's `handler` export directly, without `BaseServer`. None of the three changes
`base-server.ts`, and the `parentSpan.setAttribute('http.route', route)` call is still present in the
published builds of 16.4.3 and 16.5.0-canary.28. `next start` runs `BaseServer.handleRequest`.

## Notes on `instrumentation.ts`

- `instrumentation-http` patches `http` the next time a module requires it. Next.js has already
  required `http` when `register()` runs, so `instrumentation.ts` calls `require("node:http")` after
  the SDK starts. In an application, modules loaded later (error reporters, database clients) do
  this. Without the call, this app has no HTTP server span, `parentSpan` is the Next.js span itself,
  and nothing is logged.
- The SDK doesn't print the warning unless a diagnostic logger is set.
- The exporter discards spans. With `spanProcessors: []` in its place, no spans are recorded.

## Possible fixes

- Write `http.route` to the parent span only while it is still recording:
  `if (parentSpan && parentSpan !== span && parentSpan.isRecording())`. `Span.isRecording()` returns
  `false` after a span ends. This removes the warning, but the parent span still doesn't receive
  `http.route`.
- Write `http.route` to the parent span when the route is resolved, before the response is sent, so
  that the parent span receives it while it is open.
