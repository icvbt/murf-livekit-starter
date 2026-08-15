import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PORT = 8765

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.getenv(
        "CALL_DB_PATH",
        str(BASE_DIR / "data" / "arthsakhi.sqlite3"),
    )
)

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_connection()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS call_outcomes (
            call_id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            outcome TEXT NOT NULL,
            success_reason TEXT,
            failure_reason TEXT,
            language_preference TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    connection.commit()
    connection.close()


def get_metrics():
    connection = get_connection()

    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total_calls,
            SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END)
                AS successful_calls,
            SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END)
                AS failed_calls
        FROM call_outcomes
        """
    ).fetchone()

    connection.close()

    return {
        "total_calls": row["total_calls"] or 0,
        "successful_calls": row["successful_calls"] or 0,
        "failed_calls": row["failed_calls"] or 0,
    }


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ArthSakhi Call Dashboard</title>
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: Arial, sans-serif;
            background: #f4f7fb;
            color: #172033;
        }

        header {
            padding: 28px 20px;
            color: white;
            background: linear-gradient(135deg, #172554, #0f766e);
        }

        header h1 {
            margin: 0 0 8px;
            font-size: 28px;
        }

        header p {
            margin: 0;
            opacity: 0.9;
        }

        main {
            width: min(1050px, calc(100% - 32px));
            margin: 35px auto;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }

        .card {
            padding: 26px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 8px 25px rgba(15, 23, 42, 0.08);
        }

        .card h2 {
            margin: 0 0 15px;
            font-size: 16px;
            color: #475569;
        }

        .number {
            font-size: 48px;
            font-weight: bold;
        }

        .total {
            border-top: 5px solid #172554;
        }

        .success {
            border-top: 5px solid #16a34a;
        }

        .failed {
            border-top: 5px solid #dc2626;
        }

        .info {
            margin-top: 28px;
            padding: 20px;
            background: white;
            border-radius: 16px;
            color: #475569;
        }

        button {
            margin-top: 18px;
            padding: 10px 16px;
            border: 0;
            border-radius: 8px;
            color: white;
            background: #0f766e;
            cursor: pointer;
        }

        button:hover {
            background: #115e59;
        }

        #status {
            margin-top: 12px;
            font-size: 13px;
            color: #64748b;
        }

        @media (max-width: 700px) {
            .cards {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>ArthSakhi Call Dashboard</h1>
        <p>Real-time call outcome tracking</p>
    </header>

    <main>
        <section class="cards">
            <div class="card total">
                <h2>Total Calls</h2>
                <div id="total-calls" class="number">0</div>
            </div>

            <div class="card success">
                <h2>Successful Calls</h2>
                <div id="successful-calls" class="number">0</div>
            </div>

            <div class="card failed">
                <h2>Failed Calls</h2>
                <div id="failed-calls" class="number">0</div>
            </div>
        </section>

        <section class="info">
            <div>
                Metrics are calculated from the SQLite call_outcomes table.
                No caller phone numbers, OTPs, PINs, account numbers, or transcripts
                are displayed.
            </div>

            <button onclick="loadMetrics()">Refresh Metrics</button>
            <div id="status">Loading...</div>
        </section>
    </main>

    <script>
        async function loadMetrics() {
            const status = document.getElementById("status");

            try {
                const response = await fetch("/api/metrics");
                const metrics = await response.json();

                document.getElementById("total-calls").textContent =
                    metrics.total_calls;

                document.getElementById("successful-calls").textContent =
                    metrics.successful_calls;

                document.getElementById("failed-calls").textContent =
                    metrics.failed_calls;

                status.textContent =
                    "Last updated: " + new Date().toLocaleTimeString();
            } catch (error) {
                status.textContent =
                    "Could not load metrics. Check that the dashboard server is running.";
            }
        }

        loadMetrics();
        setInterval(loadMetrics, 5000);
    </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, payload):
        data = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/metrics":
            self.send_json(get_metrics())
            return

        if path == "/":
            data = HTML.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format_string, *args):
        return


if __name__ == "__main__":
    initialize_database()

    server = ThreadingHTTPServer(("localhost", PORT), DashboardHandler)

    print(f"Database: {DB_PATH}")
    print(f"Dashboard: http://localhost:{PORT}")

    server.serve_forever()