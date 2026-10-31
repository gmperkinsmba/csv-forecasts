from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import secrets
import socketserver
import threading
from forecast import parse_csv, repair_missing, evaluate
from report import make_report
from timesfm_adapter import load as load_timesfm, backtest as backtest_timesfm

ROOT = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8321
TOKEN = secrets.token_urlsafe(24)
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)


class ForecastHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Bypass HTTPServer.server_bind's reverse-DNS lookup for localhost.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.socket.getsockname()[1]


class Handler(BaseHTTPRequestHandler):
    server_version = "ForecastStudio/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        # Requests can contain imported data or model paths; keep logs silent.
        return

    def safe(self):
        port = self.server.server_port
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origins = {f"http://{item}" for item in hosts}
        return host in hosts and (not origin or origin in origins)

    def do_GET(self):
        if not self.safe():
            return self.send_error(403)
        if self.path not in ("/", "/?desktop=1"):
            return self.send_error(404)
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.safe() or self.headers.get("X-Forecast-Token") != TOKEN:
            return self.send_error(403)
        if self.path not in ("/api/inspect", "/api/run", "/api/report"):
            return self.send_error(404)
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self.send_error(415)
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            return self.send_error(400)
        if size < 1 or size > 2_100_000:
            return self.send_error(413)
        try:
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("Request body is incomplete")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            raw = data.get("csv", "")
            if not isinstance(raw, str):
                raise ValueError("CSV data must be text")
            headers, groups = parse_csv(raw, data.get("timestamp", ""), data.get("value", ""), data.get("series", ""), data.get("covariates", []))
            if len(groups) > 20:
                raise ValueError("CSV has more than 20 series. Select or split the series before running.")
            if self.path == "/api/inspect":
                result = {"headers": headers, "series": [{k: v for k, v in g.items() if k != "rows_data"} for g in groups], "preview": [{"timestamp": r["t"].isoformat(), "value": r["y"], "series": g["name"], **r["covariates"]} for g in groups for r in g["rows_data"][:6]][:6]}
            else:
                horizon = int(data.get("horizon", 4))
                season = int(data.get("season", 1))
                folds = int(data.get("folds", 5))
                unit = data.get("unit", "unspecified")[:80]
                results = []
                mode = data.get("mode", "baseline")
                if mode not in ("baseline", "timesfm"):
                    raise ValueError("Choose baseline or TimesFM 2.5 mode")
                timesfm_model = None
                model_meta = None
                if mode == "timesfm":
                    timesfm_model, model_meta = load_timesfm(data.get("weights_path", ""), max(g["rows"] for g in groups), horizon)
                for group in groups:
                    values = [row["y"] for row in group["rows_data"]]
                    if any(value is None for value in values) and data.get("repair") not in ("linear", "mean", "zero"):
                        raise ValueError(f"Series {group['name']}: choose a missing-value repair")
                    metrics = evaluate(values, horizon, season, folds, data.get("repair") or "linear")
                    item = {"name": group["name"], "rows": group["rows"], "start": group["start"], "end": group["end"], "history_start": group["rows_data"][-min(40, len(group["rows_data"]))]["t"].isoformat(), "cadence_seconds": group["cadence_seconds"], "cadence_label": _cad(group["cadence_seconds"]), "unit": unit, "quality": {"duplicates": group["duplicates"], "gaps": group["gaps"], "missing": group["missing"]}, "repair": data.get("repair", "none"), "history": values[-40:], **metrics}
                    if mode == "timesfm":
                        repair_method = data.get("repair") or "linear"
                        item["timesfm"] = backtest_timesfm(timesfm_model, values, horizon, season, folds, lambda raw, method=repair_method: repair_missing([{"y": value} for value in raw], method) if any(value is None for value in raw) else raw)
                        item["timesfm"].update({"checkpoint_id": model_meta["checkpoint_id"], "checkpoint_sha256": model_meta["checkpoint_sha256"], "package_version": model_meta["package_version"], "load_runtime_ms": model_meta["load_runtime_ms"]})
                    results.append(item)
                result = {"horizon": horizon, "series": results, "mode": mode, "input_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "engine_version": "forecast-studio-baseline-v1"}
                if self.path == "/api/report":
                    pdf = make_report(result)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", "attachment; filename=csv-forecasts-report.pdf")
                    self.send_header("Content-Length", str(len(pdf)))
                    self.end_headers()
                    self.wfile.write(pdf)
                    return
            response = json.dumps(result, allow_nan=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(response)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json_error(400, str(exc)[:300])
        except Exception:
            self._json_error(500, "The request could not be completed. Check the selected columns and local model setup.")

    def _json_error(self, status, message):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def make_server(host=HOST, port=PORT):
    if host != "127.0.0.1":
        raise ValueError("Forecast Studio binds to 127.0.0.1 only")
    return ForecastHTTPServer((host, int(port)), Handler)


def _cad(x):
    if not x:return "unknown"
    if x>=86400:return f"{x/86400:.1f} days"
    if x>=3600:return f"{x/3600:.1f} hours"
    return f"{x/60:.1f} minutes"
if __name__ == "__main__":
    server = make_server()
    print(f"CSV Forecasts at http://127.0.0.1:{server.server_port}")
    server.serve_forever()
