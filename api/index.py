from http.server import BaseHTTPRequestHandler
import os
import uuid
import json
from datetime import datetime, timezone

def get_supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"]
    )

def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }

def verify_staff(authorization: str) -> bool:
    expected = f"Bearer {os.environ.get('STAFF_TOKEN', '')}"
    return authorization == expected

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in cors_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def _handle(self, method):
        headers = cors_headers()
        headers["Content-Type"] = "application/json"
        
        try:
            # 1. Check Environment Variables first
            missing_vars = [v for v in ["SUPABASE_URL", "SUPABASE_KEY"] if v not in os.environ]
            if missing_vars:
                self._send_json({"error": f"Missing Vercel Environment Variables: {', '.join(missing_vars)}"}, 500, headers)
                return

            path = self.path
            clean_path = path.split('?')[0].rstrip('/')
            
            # ── GET /api/menu ──
            if method == "GET" and clean_path == "/api/menu":
                sb = get_supabase()
                items = sb.table("menu_items").select("*").eq("available", True).order("sort_order").execute()
                cfg = sb.table("settings").select("*").execute()
                restaurant_name = "叙叙 chat chat"
                for row in (cfg.data or []):
                    if row["key"] == "restaurant_name":
                        restaurant_name = row["value"]
                
                self._send_json({"restaurant_name": restaurant_name, "items": items.data}, 200, headers)
                return

            # ── POST /api/order ──
            if method == "POST" and clean_path == "/api/order":
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length))
                sb = get_supabase()
                order_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                total = sum(i["price"] * i["qty"] for i in body["items"])

                sb.table("orders").insert({
                    "id": order_id,
                    "table_id": body.get("table_id", "外帶"),
                    "guest_count": body.get("guest_count", 1),
                    "note": body.get("note", ""),
                    "status": "new",
                    "total": total,
                    "created_at": now,
                }).execute()

                items_data = [{
                    "order_id": order_id,
                    "menu_item_id": item["menu_item_id"],
                    "name": item["name"],
                    "price": item["price"],
                    "qty": item["qty"],
                } for item in body["items"]]
                sb.table("order_items").insert(items_data).execute()

                self._send_json({"order_id": order_id, "status": "new", "total": total}, 200, headers)
                return

            # ── GET /api/orders ──
            if method == "GET" and clean_path == "/api/orders":
                auth = self.headers.get("authorization", "")
                if not verify_staff(auth):
                    self._send_json({"error": "未授權"}, 401, headers)
                    return
                sb = get_supabase()
                orders_res = sb.table("orders").select("*").neq("status", "archived").order("created_at", desc=True).limit(50).execute()
                orders = orders_res.data or []
                if orders:
                    order_ids = [o["id"] for o in orders]
                    items_res = sb.table("order_items").select("*").in_("order_id", order_ids).execute()
                    items_map = {}
                    for item in (items_res.data or []):
                        items_map.setdefault(item["order_id"], []).append(item)
                    for o in orders:
                        o["items"] = items_map.get(o["id"], [])
                self._send_json(orders, 200, headers)
                return

            # ── PATCH /api/order/<id>/status ──
            if method == "PATCH" and clean_path.startswith("/api/order/") and clean_path.endswith("/status"):
                auth = self.headers.get("authorization", "")
                if not verify_staff(auth):
                    self._send_json({"error": "未授權"}, 401, headers)
                    return
                parts = clean_path.split("/")
                order_id = parts[3]
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length))
                status = body.get("status")
                if status not in {"new", "preparing", "done", "archived"}:
                    self._send_json({"error": "無效狀態"}, 400, headers)
                    return
                sb = get_supabase()
                sb.table("orders").update({"status": status}).eq("id", order_id).execute()
                self._send_json({"ok": True}, 200, headers)
                return

            self._send_json({"error": f"Path not found: {clean_path}"}, 404, headers)
        except Exception as e:
            # Catch everything and return it as JSON to avoid generic 500 error
            import traceback
            error_details = traceback.format_exc()
            self._send_json({
                "error": "Serverless Function Crash",
                "message": str(e),
                "traceback": error_details
            }, 500, headers)

    def _send_json(self, data, status, headers):
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except:
            pass
