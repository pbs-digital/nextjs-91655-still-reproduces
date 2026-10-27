// The usual way to start OpenTelemetry in Next.js. `scripts/reproduce.py --preload` skips this and
// loads otel.cjs with `node --require` instead.
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs' && !process.env.OTEL_PRELOADED) {
    // @ts-ignore
    await import('./otel-setup.js');
  }
}
