from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from escalation_store import list_open_escalations


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return

        requests = list_open_escalations()

        rows = ""

        for item in requests:
            rows += f"""
            <tr>
                <td>{escape(item["request_id"])}</td>
                <td>{escape(item["issue_type"])}</td>
                <td>{escape(item["summary"])}</td>
                <td>{escape(item["urgency"])}</td>
                <td>{escape(item["language_preference"] or "")}</td>
                <td>{escape(item["preferred_follow_up_method"] or "")}</td>
                <td>{escape(item["created_at"])}</td>
            </tr>
            """

        html = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>ArthSakhi Escalations</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 32px;
                    background: #f4f7fb;
                    color: #17233c;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    background: white;
                }}
                th, td {{
                    border: 1px solid #d8e0ea;
                    padding: 10px;
                    text-align: left;
                    vertical-align: top;
                }}
                th {{
                    background: #172b4d;
                    color: white;
                }}
                .urgent {{
                    color: #b42318;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <h1>ArthSakhi Human-Help Requests</h1>
            <p>Open escalation requests: {len(requests)}</p>
            <table>
                <tr>
                    <th>Reference ID</th>
                    <th>Issue</th>
                    <th>Summary</th>
                    <th>Urgency</th>
                    <th>Language</th>
                    <th>Follow-up</th>
                    <th>Created</th>
                </tr>
                {rows}
            </table>
        </body>
        </html>
        """

        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("ArthSakhi escalation dashboard: http://localhost:8765")
    HTTPServer(("127.0.0.1", 8765), DashboardHandler).serve_forever()