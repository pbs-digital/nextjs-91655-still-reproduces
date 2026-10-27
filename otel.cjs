// Entry point for `node --require ./otel.cjs`, which starts the SDK before Next.js loads.
process.env.OTEL_PRELOADED = '1';
require('./otel-setup.js');
