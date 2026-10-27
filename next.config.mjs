export default {
  output: 'standalone',
  trailingSlash: true,
  // scripts/reproduce.py builds copies of this app under .work/. Without these, Next.js would treat
  // the repository's lockfile as the workspace root and nest server.js under .work/ in the output.
  outputFileTracingRoot: import.meta.dirname,
  turbopack: { root: import.meta.dirname },
};
