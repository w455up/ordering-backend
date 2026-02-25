"""
自家點餐系統 - Vercel Serverless 後端
部署方式：將整個 vercel-backend 資料夾用 Vercel CLI 或 GitHub 連接部署
"""

import os
import uuid
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler


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
        "Content-Type": "application/json",
    }


def verify_staff(authorization: str) -> bool:
    expected = f"Bearer {os.environ.get('STAFF_TOKEN', '')}"
    return authorization == expected


def json_response(data, status=200):
    return {
        "statusCode": status,
        "headers": cors_headers(),
        "body": json.dumps(data, ensure_ascii=False),
    }


def handler(request):
    """
    Vercel Python Serverless Handler
    """
    method = request.method
    path = request.path

    # ── CORS preflight ──
    if method == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": cors_headers(),
            "body": "",
        }

    # ── GET /api/menu ──
    if method == "GET" and path == "/api/menu":
        try:
            sb = get_supabase()
            items = sb.table("menu_items") \
                .select("*") \
                .eq("available", True) \
                .order("sort_order") \
                .execute()

            cfg = sb.table("settings").select("*").execute()
            restaurant_name = "叙叙 chat chat"
            for row in (cfg.data or []):
                if row["key"] == "restaurant_name":
                    restaurant_name = row["value"]

            return json_response({
                "restaurant_name": restaurant_name,
                "items": items.data
            })
        except Exception as e:
            return json_response({"error": str(e)}, 500)

    # ── POST /api/order ──
    if method == "POST" and path == "/api/order":
        try:
            body = json.loads(request.body)
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

            return json_response({
                "order_id": order_id,
                "status": "new",
                "total": total
            })
        except Exception as e:
            return json_response({"error": str(e)}, 500)

    # ── GET /api/orders ──
    if method == "GET" and path == "/api/orders":
        auth = request.headers.get("authorization", "")
        if not verify_staff(auth):
            return json_response({"error": "未授權"}, 401)
        try:
            sb = get_supabase()
            orders_res = sb.table("orders") \
                .select("*") \
                .neq("status", "archived") \
                .order("created_at", desc=True) \
                .limit(50) \
                .execute()

            orders = orders_res.data or []
            if orders:
                order_ids = [o["id"] for o in orders]
                items_res = sb.table("order_items") \
                    .select("*") \
                    .in_("order_id", order_ids) \
                    .execute()

                items_map = {}
                for item in (items_res.data or []):
                    items_map.setdefault(item["order_id"], []).append(item)

                for o in orders:
                    o["items"] = items_map.get(o["id"], [])

            return json_response(orders)
        except Exception as e:
            return json_response({"error": str(e)}, 500)

    # ── PATCH /api/order/<id>/status ──
    if method == "PATCH" and path.startswith("/api/order/") and path.endswith("/status"):
        auth = request.headers.get("authorization", "")
        if not verify_staff(auth):
            return json_response({"error": "未授權"}, 401)
        try:
            parts = path.split("/")
            order_id = parts[3]
            body = json.loads(request.body)
            status = body.get("status")
            allowed = {"new", "preparing", "done", "archived"}
            if status not in allowed:
                return json_response({"error": "無效狀態"}, 400)

            sb = get_supabase()
            sb.table("orders") \
                .update({"status": status}) \
                .eq("id", order_id) \
                .execute()

            return json_response({"ok": True})
        except Exception as e:
            return json_response({"error": str(e)}, 500)

    return json_response({"error": "Not found"}, 404)
