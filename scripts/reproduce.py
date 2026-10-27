"""Build the app, run its standalone server, and count OpenTelemetry "ended Span" warnings.

Usage:
    python3 scripts/reproduce.py [--next VERSION] [--preload] [--requests N] [--port PORT]

With --next, the app is copied to .work/next-VERSION and built against that Next.js version, so the
checkout is left unchanged. With --preload, the SDK starts from `node --require ./otel.cjs` instead
of instrumentation.ts. When GITHUB_STEP_SUMMARY is set, the results are appended to it as Markdown.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ("/", "/api/ping/")
WARNING = "Cannot execute the operation on ended Span"
APP_FILES = ("app", "instrumentation.ts", "next.config.mjs", "otel-setup.js", "otel.cjs",
             "package.json", "bun.lock", "tsconfig.json")


def prepare(version: str | None) -> Path:
    if version is None:
        subprocess.run(["bun", "install", "--frozen-lockfile"], cwd=ROOT, check=True)
        return ROOT
    app = ROOT / ".work" / f"next-{version}"
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    for name in APP_FILES:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, app / name)
        elif source.exists():
            shutil.copy2(source, app / name)
    subprocess.run(["bun", "install"], cwd=app, check=True)
    subprocess.run(["bun", "add", "--exact", f"next@{version}"], cwd=app, check=True)
    return app


def build(app: Path) -> Path:
    subprocess.run(["bun", "run", "build"], cwd=app, check=True)
    standalone = app / ".next" / "standalone"
    shutil.copytree(app / ".next" / "static", standalone / ".next" / "static", dirs_exist_ok=True)
    return standalone


def get(port: int, path: str) -> int:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--next", dest="version", help="Next.js version or dist-tag to build against")
    parser.add_argument("--preload", action="store_true", help="start the SDK with node --require")
    parser.add_argument("--requests", type=int, default=20, help="requests per route")
    parser.add_argument("--port", type=int, default=3999)
    args = parser.parse_args()

    app = prepare(args.version)
    standalone = build(app)
    version = json.loads((app / "node_modules" / "next" / "package.json").read_text())["version"]
    loading = "node --require ./otel.cjs" if args.preload else "instrumentation.ts"

    env = {**os.environ, "PORT": str(args.port), "HOSTNAME": "127.0.0.1",
           # Shows the Next.js frames that its stack traces otherwise hide as "ignore-listed frames".
           "__NEXT_SHOW_IGNORE_LISTED": "true"}
    if args.preload:
        env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} --require {app / 'otel.cjs'}".strip()

    log_path = app / "server.log"
    with open(log_path, "w") as log:
        server = subprocess.Popen(["node", "server.js"], cwd=standalone, env=env,
                                  stdout=log, stderr=subprocess.STDOUT)
        for _ in range(120):
            try:
                get(args.port, ROUTES[-1])
                break
            except OSError:
                if server.poll() is not None:
                    raise SystemExit(f"The server exited; see {log_path}")
                time.sleep(0.5)
        else:
            server.terminate()
            raise SystemExit(f"The server didn't respond; see {log_path}")

        # Requests made while waiting for the server aren't counted.
        time.sleep(1)
        warnings = {}
        for route in ROUTES:
            before = log_path.read_text().count(WARNING)
            for _ in range(args.requests):
                get(args.port, route)
            time.sleep(1)
            warnings[route] = log_path.read_text().count(WARNING) - before

        server.send_signal(signal.SIGTERM)
        server.wait(timeout=30)

    output = log_path.read_text()
    spans_match = re.search(r"\[otel-setup\] finished spans (\{.*\})", output)
    spans = json.loads(spans_match.group(1)) if spans_match else {}
    http_spans = spans.get("@opentelemetry/instrumentation-http SERVER", 0)
    sample = re.search(rf"{WARNING}.*?(?=\n\S|\Z)", output, re.S)

    row = (f"| {version} | `{loading}` | {http_spans} | "
           + " | ".join(f"{warnings[route]} / {args.requests}" for route in ROUTES) + " |")
    report = [
        "| Next.js | SDK started from | instrumentation-http SERVER spans | Warnings `/` | Warnings `/api/ping/` |",
        "|---|---|---|---|---|",
        row,
        "",
        f"Spans finished, by instrumentation scope and kind: `{json.dumps(spans)}`",
    ]
    if sample:
        report += ["", "First warning:", "", "```", sample.group(0).strip(), "```"]
    text = "\n".join(report) + "\n"
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
