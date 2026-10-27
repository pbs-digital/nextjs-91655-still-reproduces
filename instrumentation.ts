export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { diag, DiagConsoleLogger, DiagLogLevel } = await import("@opentelemetry/api");
    const { NodeSDK } = await import("@opentelemetry/sdk-node");
    const { HttpInstrumentation } = await import("@opentelemetry/instrumentation-http");

    // Without a diagnostic logger, the SDK doesn't print the warning.
    diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.WARN);

    new NodeSDK({
      // Discards spans. With `spanProcessors: []` in place of an exporter, no spans are recorded.
      traceExporter: { export: (_spans, done) => done({ code: 0 }), shutdown: async () => {} },
      instrumentations: [new HttpInstrumentation()],
    }).start();

    // instrumentation-http patches `http` the next time a module requires it, and Next.js has
    // already required `http` by the time register() runs. In an application, modules loaded later
    // (error reporters, database clients) apply the patch. This app has no such module, so this
    // call stands in for them.
    require("node:http");
  }
}
