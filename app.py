import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from google.cloud import storage
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import io
import csv
from enum import Enum
from datetime import datetime
import re
import unicodedata
from typing import List, Literal, Optional
from google.cloud import firestore
import time
from google.api_core.exceptions import InternalServerError, ServiceUnavailable

# --- 🚀 初期設定 ---
app = Flask(__name__)

# Flask セキュリティ設定（必要に応じて）
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super-secret-key-59310')
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'suziegogo')

# Firestoreクライアントの初期化
db = firestore.Client()

# 🌟 Vertex AI経由のGenaiクライアント初期化（asia-northeast1）
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT', 'commanding-fact-481507-n7')
client = genai.Client(
    vertexai=True, 
    project=PROJECT_ID,
    location='asia-northeast1' 
)



# --- 🔒 認証 & PWAルート制御 (Before Request) ---
@app.before_request
def check_authentication():
    # パスワード不要でアクセスできる公開パス（PWA必須ファイルを含む）
    public_paths = ['/login', '/manifest.json', '/sw.js']
    
    # 公開パス、または /static/ 配下のファイルは認証をスキップ
    if request.path in public_paths or request.path.startswith('/static/'):
        return
    
    # ログインセッションがない場合は /login へリダイレクト
    if not session.get('logged_in'):
        return redirect(url_for('login'))


# --- 🔑 ログイン関連ルート ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        if password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'パスワードが間違っています。'
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# ==========================================
# 1. Pydantic スキーマ定義 (Gemini構造化出力用)
# ==========================================

class ExpenseCategory(str, Enum):
    SHOKUHI = "食費"
    NICHIYOU = "日用品"
    GAISHOKU = "外食"
    KOUTSUU = "交通費"
    GORAKU = "娯楽"
    KOTEI = "固定費"
    CLOTHING = "衣服・美容"
    IRYOU = "医療費"
    OTHER = "その他"

from pydantic import BaseModel, Field

# --- 📋 カテゴリの選択肢を明確にした Pydantic スキーマ ---
class ReceiptItem(BaseModel):
    name: str = Field(default="", description="購入した品目名")
    category: Literal["食費", "日用品", "外食", "交通費", "娯楽", "固定費", "衣服・美容", "医療費", "その他"] = Field(
        default="食費", description="カテゴリ"
    )
    amount: int = Field(default=0, description="金額（円）")

class ReceiptAnalysis(BaseModel):
    store_name: str = Field(default="", description="店舗の屋号・名前（住所や電話番号は含めない）")
    date: str = Field(default="", description="購入日 (YYYY-MM-DD形式)")
    tax: int = Field(default=0, description="消費税額（整数）")
    total_amount: int = Field(default=0, description="総合計金額")
    items: List[ReceiptItem] = Field(default=[], description="品目明細のリスト")


# --- 📅 日付標準化関数 ---
def standardize_date(date_str):
    if not date_str or str(date_str).strip() in ["", "0", "null", "None", "0000-00-00"]:
        return datetime.now().strftime('%Y-%m-%d')
    
    str_val = str(date_str).strip()
    normalized = unicodedata.normalize('NFKC', str_val)
    match = re.search(r'(\d{4})[^\d]?(\d{1,2})[^\d]?(\d{1,2})?', normalized)
    if match:
        year = match.group(1)
        month = match.group(2).zfill(2)
        day = match.group(3).zfill(2) if match.lastindex >= 3 and match.group(3) else '01'
        return f"{year}-{month}-{day}"
        
    return datetime.now().strftime('%Y-%m-%d')


# --- 🏠 メイン画面（サマリー表示） ---
@app.route('/')
def index():
    try:
        # Firestoreからレシートデータを新しい順に取得
        docs = db.collection('expenses').order_by('date', direction=firestore.Query.DESCENDING).stream()
        
        expenses_list = []
        total_amount = 0
        total_tax = 0
        
        for doc in docs:
            data = doc.to_dict()
            doc_id = doc.id
            
            raw_date = data.get('date', '')
            clean_date = standardize_date(raw_date)
            
            items = data.get('items', [])
            first_category = items[0].get('category', '食費') if items else 'その他'
            
            # 各項目の数値を取得（安全にパース）
            amt = int(data.get('total_amount', 0) or 0)
            tax = int(data.get('tax', 0) or 0)
            
            # 全体の合計に加算
            total_amount += amt
            total_tax += tax
            
            formatted_item = {
                '_serverId': doc_id,
                'id': doc_id,
                '日付': clean_date,
                '店舗名': data.get('store_name', '店舗名未設定'),
                '金額 (¥)': amt,
                '内消費税 (¥)': tax,
                'カテゴリ': first_category,
                'items': items
            }
            
            expenses_list.append(formatted_item)
            
        # 🌟 total_amount と total_tax もテンプレートに渡す
        return render_template(
            'index.html', 
            expenses=expenses_list,
            total_amount=total_amount,
            total_tax=total_tax
        )
    except Exception as e:
        print(f"🔥 Index Error: {e}")
        return render_template('index.html', expenses=[], total_amount=0, total_tax=0, error=str(e))

def analyze_receipt_with_retry(image_bytes, mime_type, retries=3, delay=2):
    prompt_text = """
    You are an expert Japanese receipt parsing assistant. Extract the structured data from this receipt image into strict JSON format with the following keys:

    1. "store_name": (string) The name of the merchant/store.
    2. "date": (string) The transaction date in YYYY-MM-DD format.
    3. "total_amount": (integer) The final grand total amount paid (including consumption tax). 
    - Look specifically for keywords preceding or near this amount such as: 合計, 領収金額, 総計, 請求金額, or 御代.
    - Always extract the final payable amount verbatim without doing any calculations or falling back to tax-excluded subtotals.
    4. "tax": (integer) The consumption tax amount printed on the receipt (labeled as 内税, 内消費税, or 消費税). Extract verbatim.
    5. "items": (array of objects) Each containing:
    - "name": (string) Item name
    - "category": (string) Appropriate category (e.g., 食費, 日用品, 医療費, etc.)
    - "amount": (integer) Line item price
    """

    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type or 'image/jpeg'),
        prompt_text
    ]

    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ReceiptAnalysis,
                    temperature=0.1
                )
            )
        except (ServiceUnavailable, InternalServerError) as e:
            if attempt == retries - 1:
                raise e
            time.sleep(delay * (attempt + 1))

@app.route('/api/analyze-receipt', methods=['POST'])
def analyze_receipt():
    if 'receipt_image' not in request.files:
        return jsonify({"success": False, "error": "No image file uploaded"}), 400
    
    file = request.files['receipt_image']
    image_bytes = file.read()
    mime_type = file.content_type

    try:
        response = analyze_receipt_with_retry(image_bytes, mime_type)
        parsed_data = response.parsed

        return jsonify({
            "success": True, 
            "data": parsed_data.dict() if hasattr(parsed_data, 'dict') else parsed_data
        })

    except Exception as e:
        print(f"Receipt analysis error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def calculate_category_summary(expenses):
    """
    Aggregates category totals from item-level breakdowns within each receipt:
    - Iterates through the 'items' array of each receipt document.
    - Sums item-level amounts by category.
    - Tracks item counts for clean UI badge displays.
    """
    summary = {}
    
    for exp in expenses:
        items = exp.get('items', [])
        for item in items:
            cat = item.get('category') or item.get('カテゴリ') or 'その他'
            amount = float(item.get('amount', 0) or 0)
            
            if cat not in summary:
                summary[cat] = {
                    'amount': 0,
                    'count': 0
                }
                
            summary[cat]['amount'] += amount
            summary[cat]['count'] += 1
            
    return summary   
    
@app.route('/add_receipt', methods=['POST'])
@app.route('/api/save', methods=['POST'])  # フロントエンドがどちらを叩いても対応できるように両方設置
def add_receipt():
    try:
        # JSON または Form Data のどちらでも受け取れるようにする
        if request.is_json:
            req_data = request.json
            store_name = req_data.get('store_name', '店舗名未設定')
            raw_date = req_data.get('date', '')
            tax = int(req_data.get('tax', 0) or 0)
            items = req_data.get('items', [])
        else:
            store_name = request.form.get('store_name', '店舗名未設定').strip()
            raw_date = request.form.get('date', '')
            tax = int(request.form.get('tax', 0) or 0)
            
            names = request.form.getlist('item_name[]')
            amounts = request.form.getlist('item_amount[]') or request.form.getlist('item_price[]')
            categories = request.form.getlist('item_category[]')
            
            items = []
            for name, amount_str, category in zip(names, amounts, categories):
                if name and name.strip():
                    items.append({
                        'name': name.strip(),
                        'amount': int(amount_str) if amount_str else 0,
                        'category': category.strip() if category else '食費'
                    })

        date_str = standardize_date(raw_date)
        
        # 品目の合計計算
        items_total = sum(int(item.get('amount', 0) or 0) for item in items)
        total_amount = items_total

        # 🔍 重複チェック (Duplicate Check)
        existing_query = (
            db.collection('expenses')
            .where('date', '==', date_str)
            .where('store_name', '==', store_name)
            .where('total_amount', '==', int(total_amount))
            .limit(1)
            .stream()
        )
        
        if any(existing_query):
            return jsonify({
                'success': False,
                'duplicate': True,
                'error': f'【重複検知】{date_str} の「{store_name}」（¥{total_amount:,}）はすでに登録されています。'
            }), 409  # Conflict status

        # Firestore (expenses コレクション) に保存
        db.collection('expenses').add({
            'store_name': store_name,
            'date': date_str,
            'tax': tax,
            'total_amount': total_amount,
            'items': items,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        # 1. Fetch all expenses from Firestore
        docs = db.collection('expenses').order_by('date', direction=firestore.Query.DESCENDING).stream()
        updated_expenses = []
        for doc in docs:
            item = doc.to_dict()
            item['id'] = doc.id
            updated_expenses.append(item)
            
        # 2. Calculate category breakdown summary
        category_summary = calculate_category_summary(updated_expenses)
        
        # 3. Return JSON response
        return jsonify({
            'success': True,
            'expenses': updated_expenses,
            'category_summary': category_summary
        })
        
    except Exception as e:
        print(f"🔥 Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# --- 💾 登録・保存 API (Firestore保存) ---
@app.route('/api/save', methods=['POST'])
def api_save():
    new_receipt = request.json
    if not new_receipt:
        return jsonify({'success': False, 'error': 'データがありません'}), 400
        
    raw_date = new_receipt.get('date', '')
    clean_date = standardize_date(raw_date)
    date_str = clean_date if clean_date else datetime.now().strftime('%Y-%m-%d')

    store_name = str(new_receipt.get('store_name', '')).strip()    
    items = new_receipt.get('items', [])
    
    # Calculate items total for reference/debugging
    items_total = sum(int(item.get('amount', 0) or 0) for item in items)
    
    # 🌟 Use Gemini's extracted total_amount (verbatim grand total including tax, discounts, etc.)
    # Fall back to items_total only if total_amount is missing or zero.
    extracted_total = int(new_receipt.get('total_amount', 0) or 0)
    total_amount = extracted_total if extracted_total > 0 else items_total
    
    tax = int(new_receipt.get('tax', 0) or 0)

    # 🌟 Verification logging to confirm exact saved totals in Cloud Run logs
    print(f"💾 [API SAVE] Store: {store_name} | Date: {date_str} | Grand Total: ¥{total_amount} | Items Sum: ¥{items_total} | Tax: ¥{tax}")

    try:
        # Firestore (expenses コレクション) に保存
        db.collection('expenses').add({
            'store_name': store_name,
            'date': date_str,
            'tax': tax,
            'total_amount': total_amount,
            'items': items,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        # 1. Fetch all expenses from Firestore
        docs = db.collection('expenses').order_by('date', direction=firestore.Query.DESCENDING).stream()
        updated_expenses = []
        for doc in docs:
            item = doc.to_dict()
            item['id'] = doc.id
            updated_expenses.append(item)
            
        # 2. Calculate category breakdown summary
        category_summary = calculate_category_summary(updated_expenses)
        
        # 3. Return JSON response
        return jsonify({
            'success': True,
            'expenses': updated_expenses,
            'category_summary': category_summary
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/expenses', methods=['GET'])
def api_get_expenses():
    try:
        docs = db.collection('expenses').stream()
        expenses_list = []
        for doc in docs:
            item = doc.to_dict()
            item['id'] = doc.id
            expenses_list.append(item)
        return jsonify({'success': True, 'expenses': expenses_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
# --- 🗑️ 個別削除 API (FirestoreのドキュメントIDを使用) ---
@app.route('/api/delete', methods=['POST'])
def api_delete():
    req = request.json
    doc_id = req.get('id')  # フロントエンドから Firestore のドキュメントIDを受け取る想定
    
    if not doc_id:
        return jsonify({'success': False, 'error': '削除対象のIDが指定されていません'}), 400
        
    try:
        # Firestore上のドキュメントを直接削除
        db.collection('expenses').document(doc_id).delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- 🗑️ 全削除 API ---
@app.route('/api/delete-all', methods=['POST'])
def api_delete_all():
    try:
        # 'expenses' コレクション内のすべてのドキュメントを取得して一括削除
        docs = db.collection('expenses').stream()
        batch = db.batch()
        count = 0
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
            # Firestoreのバッチ制限（500件）対策として分割処理する場合もありますが、まずはシンプルに
        batch.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- 📥 CSV エクスポート (マルチカテゴリ・Firestore対応版) ---
@app.route('/api/export-csv')
def export_csv():
    month = request.args.get('month', 'ALL')
    
    try:
        # Firestoreからデータを取得
        docs = db.collection('expenses').order_by('date', direction=firestore.Query.DESCENDING).stream()
        
        output = io.StringIO()
        writer = csv.writer(output)
        # ヘッダー行（品目単位やレシート単位など、お好みに合わせて調整可能）
        writer.writerow(['日付', '店舗名', '品目名', 'カテゴリ', '金額 (¥)', '消費税 (¥)', '合計金額 (¥)'])
        
        for doc in docs:
            item_data = doc.to_dict()
            date = item_data.get('date', '')
            
            # 月指定フィルター
            if month != 'ALL' and not date.startswith(month):
                continue
                
            store_name = item_data.get('store_name', '')
            tax = item_data.get('tax', 0)
            total_amount = item_data.get('total_amount', 0)
            items = item_data.get('items', [])
            
            # レシート内の各品目行をCSVに出力する場合
            if items:
                for itm in items:
                    writer.writerow([
                        date,
                        store_name,
                        itm.get('name', ''),
                        itm.get('category', ''),
                        itm.get('amount', 0),
                        tax,
                        total_amount
                    ])
            else:
                # 品目がない場合のフォールバック
                writer.writerow([date, store_name, '-', '-', 0, tax, total_amount])
                
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=expenses_{month}.csv"}
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- 📱 PWA用ファイルの明示的ルーティング ---
@app.route('/manifest.json')
def serve_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')


# --- 🚀 サーバー起動 (Cloud RunのPORT環境変数に対応) ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)