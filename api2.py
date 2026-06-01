from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # 1. CORS 미들웨어 불러오기
from pydantic import BaseModel
from datetime import datetime, timedelta
import csv
import os

app = FastAPI(title="편의점 POS 시스템 API")

# 2. CORS 허용 설정 추가 (app = FastAPI() 바로 아래에 작성)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 러버블 프리뷰를 포함한 모든 도메인에서의 접근을 허용합니다.
    allow_credentials=False,
    allow_methods=["*"],  # GET, POST, OPTIONS 등 모든 HTTP 메서드를 허용합니다.
    allow_headers=["*"],  # 모든 헤더를 허용합니다.
)

# 메모리 데이터베이스 (실제 환경에서는 DB 사용 권장)
inventory = {}
cart = {}
total_revenue = 0
pending_orders = []

# --- [추가된 부분: 상품별 누적 판매 기록을 위한 전역 변수] ---
sales_log = {}  # { product_id: {"name": ..., "qty": ..., "amount": ...} }


# --- [서버 시작 시 데이터 로드] ---

@app.on_event("startup")
def load_data():
    global inventory
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'products.csv')
    print(f"[startup] CSV 로드 시도: {csv_path}")

    f = None
    for enc in ('utf-8-sig', 'cp949', 'euc-kr'):
        try:
            f = open(csv_path, mode='r', encoding=enc)
            f.read(1); f.seek(0)   # 인코딩 검증
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


# --- [API 엔드포인트: 러버블에서 호출할 주소들] ---

# 1. 대분류 카테고리 목록 가져오기 (UI 카테고리 버튼 생성용)
@app.get("/api/categories")
def get_categories():
    categories = sorted(list(set(item['category'] for item in inventory.values())))
    return {"categories": categories}


# 2. 특정 카테고리의 상품 목록 가져오기 (UI 상품 리스트 생성용)
@app.get("/api/products")
def get_products(category: str):
    category_products = [
        {"id": p_id, **info}
        for p_id, info in inventory.items()
        if info['category'] == category
    ]
    return {"products": category_products}


# 장바구니 추가를 위한 데이터 모델
class CartItem(BaseModel):
    product_id: str
    qty: int


# 3. 장바구니에 상품 담기 (UI에서 '담기' 버튼 클릭 시)
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


# 4. 장바구니 내역 확인
@app.get("/api/cart")
def view_cart():
    return {"cart": cart, "total_amount": sum(item['subtotal'] for item in cart.values())}


# 5. 결제 및 재고 차감, 자동 발주 처리 (UI에서 '결제하기' 버튼 클릭 시)
@app.post("/api/checkout")
def checkout():
    global total_revenue, cart
    
    if not cart:
        raise HTTPException(status_code=400, detail="장바구니가 비어있습니다.")
        
    total_amount = sum(item['subtotal'] for item in cart.values())
    total_revenue += total_amount
    new_orders = []
    today = datetime.now()
    
    for p_id, info in cart.items():
        # 재고 차감
        inventory[p_id]['stock'] -= info['qty']
        
        # --- [추가된 부분: 결제 확정 시, 판매 항목 누적 기록] ---
        s = sales_log.setdefault(p_id, {"name": info["name"], "qty": 0, "amount": 0})
        s["qty"] += info['qty']
        s["amount"] += info['subtotal']
        # --------------------------------------------------------
        
        # 10개 이하 시 발주 로직
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
            
    # 결제 완료 후 장바구니 초기화
    receipt = cart.copy()
    cart.clear()
    
    return {
        "message": "결제가 완료되었습니다.",
        "receipt": receipt,
        "total_amount": total_amount,
        "auto_orders_triggered": new_orders
    }


# 6. 매출 현황
@app.get("/api/revenue")
def get_revenue():
    return {"total_revenue": total_revenue}


# 7. 자동 발주 내역 (대기 중인 발주 전체)
@app.get("/api/pending-orders")
def get_pending_orders():
    return {"pending_orders": pending_orders}


# --- [추가된 부분: 상품별 판매 통계 반환 API] ---
@app.get("/api/sales")
def get_sales():
    items = [
        {"product_id": pid, **info}
        for pid, info in sales_log.items()
    ]
    # 판매 금액(amount) 기준으로 내림차순 정렬
    items.sort(key=lambda x: x["amount"], reverse=True)
    total = sum(i["amount"] for i in items)
    return {
        "items": items, 
        "total_amount": total, 
        "total_qty": sum(i["qty"] for i in items)
    }