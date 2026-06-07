from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import csv
import os
import uuid

app = FastAPI(title="편의점 POS 시스템 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 메모리 DB ---
inventory = {}
cart = {}
total_revenue = 0
pending_orders = []
sales_log = {}          # 상품별 누적: {pid: {"name","qty","amount"}}
order_history = []      # 주문 단위: [{"order_id","timestamp","items":[...], "total_amount","refunded"}]


# --- 서버 시작 시 데이터 로드 ---
@app.on_event("startup")
def load_data():
    global inventory
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'products.csv')
    print(f"[startup] CSV 로드 시도: {csv_path}")
    f = None
    for enc in ('utf-8-sig', 'cp949', 'euc-kr'):
        try:
            f = open(csv_path, mode='r', encoding=enc)
            f.read(1); f.seek(0)
            print(f"[startup] 인코딩 감지: {enc}")
            break
        except (UnicodeDecodeError, FileNotFoundError) as e:
            if f: f.close(); f = None
            if isinstance(e, FileNotFoundError):
                print(f"[startup] 파일 없음: {csv_path}")
                return
    if not f:
        print("[startup] 지원하는 인코딩으로 열 수 없음")
        return
    try:
        reader = csv.DictReader(f)
        for row in reader:
            inventory[row['product_id']] = {
                "category": row['category'],
                "name": row['name'],
                "price": int(row['price']),
                "stock": int(row['stock']),
                "expiration_date": row['expiration_date'],
            }
        print(f"[startup] 로드 완료: {len(inventory)}개 상품")
    except Exception as e:
        print(f"[startup] 데이터 로드 에러: {e}")
    finally:
        f.close()


# --- 카테고리 / 상품 ---
@app.get("/api/categories")
def get_categories():
    categories = sorted(list(set(item['category'] for item in inventory.values())))
    return {"categories": categories}


@app.get("/api/products")
def get_products(category: str):
    return {"products": [
        {"id": pid, **info} for pid, info in inventory.items() if info['category'] == category
    ]}


# --- 장바구니 ---
class CartItem(BaseModel):
    product_id: str
    qty: int


@app.post("/api/cart")
def add_to_cart(item: CartItem):
    p_id = item.product_id
    if p_id not in inventory:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    current_stock = inventory[p_id]['stock']
    already_in_cart = cart.get(p_id, {}).get('qty', 0)
    if current_stock < already_in_cart + item.qty:
        raise HTTPException(status_code=400, detail="재고가 부족합니다.")
    if p_id in cart:
        cart[p_id]['qty'] += item.qty
        cart[p_id]['subtotal'] += item.qty * inventory[p_id]['price']
    else:
        cart[p_id] = {
            "name": inventory[p_id]['name'],
            "price": inventory[p_id]['price'],
            "qty": item.qty,
            "subtotal": item.qty * inventory[p_id]['price']
        }
    return {"message": "장바구니에 담겼습니다.", "cart": cart}


@app.get("/api/cart")
def view_cart():
    return {"cart": cart, "total_amount": sum(item['subtotal'] for item in cart.values())}


# --- 결제 ---
@app.post("/api/checkout")
def checkout():
    global total_revenue, cart
    if not cart:
        raise HTTPException(status_code=400, detail="장바구니가 비어있습니다.")

    total_amount = sum(item['subtotal'] for item in cart.values())
    total_revenue += total_amount
    new_orders = []
    today = datetime.now()
    order_id = f"ORD-{today.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    timestamp = today.isoformat(timespec="seconds")

    order_items = []
    for p_id, info in cart.items():
        inventory[p_id]['stock'] -= info['qty']

        # 상품별 누적
        s = sales_log.setdefault(p_id, {"name": info["name"], "qty": 0, "amount": 0})
        s["qty"] += info['qty']
        s["amount"] += info['subtotal']

        order_items.append({
            "product_id": p_id,
            "name": info['name'],
            "qty": info['qty'],
            "price": info['price'],
        })

        # 자동 발주
        if inventory[p_id]['stock'] <= 10:
            order_qty = 20
            restock_date = today + timedelta(days=1)
            expiration_date = today + timedelta(days=7)
            order_data = {
                "product_id": p_id,
                "name": info['name'],
                "order_qty": order_qty,
                "restock_date": restock_date.strftime("%Y-%m-%d"),
                "new_expiration": expiration_date.strftime("%Y-%m-%d")
            }
            pending_orders.append(order_data)
            new_orders.append(order_data)

    # 주문 단위 기록 (환불 추적용)
    order_history.append({
        "order_id": order_id,
        "timestamp": timestamp,
        "items": order_items,
        "total_amount": total_amount,
        "refunded": False,
    })

    # CSV에도 append (분석/백업용)
    try:
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sales_history.csv')
        write_header = not os.path.exists(csv_file)
        with open(csv_file, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["order_id","timestamp","product_id","name","price","qty","amount","refunded"])
            for it in order_items:
                w.writerow([order_id, timestamp, it["product_id"], it["name"],
                            it["price"], it["qty"], it["price"]*it["qty"], "false"])
    except Exception as e:
        print(f"[checkout] CSV 기록 실패: {e}")

    receipt = cart.copy()
    cart.clear()

    return {
        "message": "결제가 완료되었습니다.",
        "order_id": order_id,
        "timestamp": timestamp,
        "receipt": receipt,
        "total_amount": total_amount,
        "auto_orders_triggered": new_orders
    }


# --- 매출 / 발주 ---
@app.get("/api/revenue")
def get_revenue():
    return {"total_revenue": total_revenue}


@app.get("/api/pending-orders")
def get_pending_orders():
    return {"pending_orders": pending_orders}


@app.get("/api/sales")
def get_sales():
    items = [{"product_id": pid, **info} for pid, info in sales_log.items()]
    items.sort(key=lambda x: x["amount"], reverse=True)
    return {
        "items": items,
        "total_amount": sum(i["amount"] for i in items),
        "total_qty": sum(i["qty"] for i in items),
    }


# --- 시간대별 매출 ---
@app.get("/api/sales/by-time")
def sales_by_time(bucket: str = "hour"):
    agg = {}
    for o in order_history:
        if o["refunded"]:
            continue
        try:
            dt = datetime.fromisoformat(o["timestamp"])
        except Exception:
            continue
        key = dt.strftime("%Y-%m-%d %H:00") if bucket == "hour" else dt.strftime("%Y-%m-%d")
        a = agg.setdefault(key, {"amount": 0, "qty": 0})
        a["amount"] += o["total_amount"]
        a["qty"]    += sum(it["qty"] for it in o["items"])
    buckets = [{"label": k, **v} for k, v in sorted(agg.items())]
    return {"buckets": buckets}


# --- TOP N ---
@app.get("/api/sales/top")
def sales_top(limit: int = 5):
    items = [{"product_id": pid, **info} for pid, info in sales_log.items()]
    items.sort(key=lambda x: x["amount"], reverse=True)
    return {"items": items[:limit]}


# --- 최근 24h 주문 ---
@app.get("/api/orders/recent")
def orders_recent(hours: int = 24):
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    result = []
    for o in sorted(order_history, key=lambda x: x["timestamp"], reverse=True):
        try:
            dt = datetime.fromisoformat(o["timestamp"])
        except Exception:
            continue
        if dt < cutoff:
            continue
        refundable = (not o["refunded"]) and (now - dt <= timedelta(hours=24))
        result.append({
            "order_id": o["order_id"],
            "timestamp": o["timestamp"],
            "total_amount": o["total_amount"],
            "items": o["items"],
            "refundable": refundable,
            "refunded": o["refunded"],
        })
    return {"orders": result}


# --- 환불 ---
class RefundReq(BaseModel):
    order_id: str


@app.post("/api/refund")
def refund(req: RefundReq):
    global total_revenue
    target = next((o for o in order_history if o["order_id"] == req.order_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if target["refunded"]:
        raise HTTPException(status_code=400, detail="이미 환불된 주문입니다.")
    try:
        dt = datetime.fromisoformat(target["timestamp"])
    except Exception:
        raise HTTPException(status_code=400, detail="주문 시간을 확인할 수 없습니다.")
    if datetime.now() - dt > timedelta(hours=24):
        raise HTTPException(status_code=400, detail="24시간이 지나 환불할 수 없습니다.")

    # 재고 복구 + 매출/누적 차감
    for it in target["items"]:
        pid = it["product_id"]
        qty = it["qty"]
        amt = it["price"] * qty
        if pid in inventory:
            inventory[pid]["stock"] += qty
        if pid in sales_log:
            sales_log[pid]["qty"]    = max(0, sales_log[pid]["qty"] - qty)
            sales_log[pid]["amount"] = max(0, sales_log[pid]["amount"] - amt)
    total_revenue = max(0, total_revenue - target["total_amount"])
    target["refunded"] = True

    # CSV 갱신 (해당 order_id 줄 refunded=true 로 마킹)
    try:
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sales_history.csv')
        if os.path.exists(csv_file):
            with open(csv_file, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for r in rows:
                if r.get("order_id") == req.order_id:
                    r["refunded"] = "true"
            if rows:
                with open(csv_file, "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
    except Exception as e:
        print(f"[refund] CSV 갱신 실패: {e}")

    return {"message": "환불 완료", "order_id": req.order_id}


# --- 전체 재고 ---
@app.get("/api/inventory")
def get_inventory():
    return {"products": [
        {
            "id": pid,
            "name": p["name"],
            "category": p["category"],
            "stock": p["stock"],
            "price": p["price"],
            "expiration_date": p["expiration_date"],
        }
        for pid, p in inventory.items()
    ]}


# --- 유통기한 임박 ---
@app.get("/api/inventory/expiring")
def get_expiring(days: int = 3):
    today = datetime.now().date()
    limit = today + timedelta(days=days)
    items = []
    for pid, p in inventory.items():
        try:
            d = datetime.strptime(p["expiration_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if d <= limit:
            items.append({
                "id": pid,
                "name": p["name"],
                "category": p["category"],
                "stock": p["stock"],
                "price": p["price"],
                "expiration_date": p["expiration_date"],
            })
    items.sort(key=lambda x: x["expiration_date"])
    return {"products": items}
