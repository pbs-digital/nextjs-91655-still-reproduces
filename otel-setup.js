// The OpenTelemetry Node SDK with only the HTTP instrumentation. No vendor distribution is involved.
const { diag, DiagConsoleLogger, DiagLogLevel, SpanKind } = require('@opentelemetry/api');
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { HttpInstrumentation } = require('@opentelemetry/instrumentation-http');
const { InMemorySpanExporter, SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-base');

// Without a diagnostic logger, the SDK reports operations on ended spans to no one.
diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.WARN);

const exporter = new InMemorySpanExporter();
new NodeSDK({
  spanProcessors: [new SimpleSpanProcessor(exporter)],
  instrumentations: [new HttpInstrumentation()],
}).start();

// instrumentation-http patches `http` the next time a module requires it. When this file runs from
// instrumentation.ts, Next.js has already required `http` and started its server. In a real app,
// modules loaded later (error reporters, database clients, HTTP clients) require `http` and apply the
// patch; a two-file app has no such module, so this line stands in for them.
require('node:http');

// Reports, on shutdown, how many spans each instrumentation finished.
process.on('SIGTERM', () => {
  const counts = {};
  for (const span of exporter.getFinishedSpans()) {
    const key = `${span.instrumentationScope.name} ${SpanKind[span.kind]}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  console.log(`[otel-setup] finished spans ${JSON.stringify(counts)}`);
  process.exit(0);
});
