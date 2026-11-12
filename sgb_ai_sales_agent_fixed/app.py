from flask import Flask, render_template, request, jsonify, session
from pathlib import Path
import sqlite3, csv, io, re, uuid
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'sales_agent.db'
app = Flask(__name__)
app.secret_key = 'local-demo-only-change-before-deployment'
REQUIRED = {'sku', 'name', 'category', 'description'}


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS products(
          sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
          description TEXT NOT NULL, applications TEXT DEFAULT '', limitations TEXT DEFAULT '',
          price REAL, currency TEXT DEFAULT 'INR', stock_status TEXT DEFAULT 'unknown',
          specifications_json TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT NOT NULL, role TEXT NOT NULL,
          message TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requirements(
          sid TEXT PRIMARY KEY, application TEXT DEFAULT '', budget REAL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT NOT NULL, order_ref TEXT UNIQUE NOT NULL,
          sku TEXT NOT NULL, product_name TEXT NOT NULL, price REAL, status TEXT NOT NULL,
          created_at TEXT NOT NULL);
        ''')
        if con.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 0:
            con.execute('''INSERT INTO products(sku,name,category,description,applications,limitations,price,currency,stock_status,specifications_json)
              VALUES(?,?,?,?,?,?,?,?,?,?)''', ('DEMO-001','Demo Irrigation Kit','Irrigation','Fictional sample product for testing.','Small gardens','Demo data; verify all specifications',1499,'INR','in_stock','{}'))


def norm(s):
    return re.sub(r'[^a-z0-9]+', '_', (s or '').strip().lower()).strip('_')


def price_value(s):
    if not s or not str(s).strip(): return None
    val = re.sub(r'[^0-9.]', '', str(s))
    try: return float(val) if val else None
    except ValueError: return None


def import_csv(upload):
    raw = upload.read()
    try: text = raw.decode('utf-8-sig')
    except UnicodeDecodeError: text = raw.decode('latin-1')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames: raise ValueError('CSV is empty or has no header row.')
    mapping = {norm(h): h for h in reader.fieldnames}
    missing = REQUIRED - set(mapping)
    if missing: raise ValueError('Missing required columns: ' + ', '.join(sorted(missing)))
    rows, skus = [], set()
    for line, src in enumerate(reader, 2):
        r = {k: (src.get(v) or '').strip() for k,v in mapping.items()}
        if not any(r.values()): continue
        sku, name = r.get('sku',''), r.get('name','')
        if not sku or not name: raise ValueError(f'Row {line}: SKU and name are required.')
        if sku.lower() in skus: raise ValueError(f'Row {line}: duplicate SKU {sku}.')
        skus.add(sku.lower())
        stock = r.get('stock_status','unknown').lower().replace(' ','_')
        if stock not in {'in_stock','out_of_stock','unknown','limited'}: stock = 'unknown'
        rows.append((sku,name,r.get('category') or 'General',r.get('description') or '',
          r.get('applications',''),r.get('limitations',''),price_value(r.get('price')),
          r.get('currency') or 'INR',stock,r.get('specifications_json') or '{}'))
    if not rows: raise ValueError('CSV contains no product rows.')
    with connect() as con:
        con.execute('DELETE FROM products')
        con.executemany('''INSERT INTO products(sku,name,category,description,applications,limitations,price,currency,stock_status,specifications_json)
          VALUES(?,?,?,?,?,?,?,?,?,?)''', rows)
    return len(rows)


def products():
    with connect() as con: return [dict(r) for r in con.execute('SELECT * FROM products ORDER BY name')]


def money(p):
    return 'price not listed' if p['price'] is None else f"{p.get('currency') or 'INR'} {p['price']:,.2f}"


def find_product(text, items):
    low = text.lower()
    for p in items:
        if p['sku'].lower() in low: return p
    for p in items:
        if p['name'].lower() in low: return p
    words = set(re.findall(r'[a-z0-9]+', low))
    ranked = []
    for p in items:
        score = len(words & set(re.findall(r'[a-z0-9]+', p['name'].lower())))
        if score >= 2: ranked.append((score,p))
    return sorted(ranked,key=lambda x:x[0],reverse=True)[0][1] if ranked else None


def budget_from(text):
    t = text.lower().replace(',', '')
    pats = [r'(?:under|below|less than|within|budget(?: is| of)?|₹|rs\.?\s*)\s*(?:₹|rs\.?\s*)?(\d+(?:\.\d+)?)', r'(\d+(?:\.\d+)?)\s*(?:rupees|inr)']
    for pat in pats:
        m = re.search(pat,t)
        if m: return float(m.group(1))
    return None


def reply(text, sid):
    t = text.lower(); items = products()
    with connect() as con:
        req = con.execute('SELECT application,budget FROM requirements WHERE sid=?',(sid,)).fetchone()
    application = req['application'] if req else ''
    budget = req['budget'] if req else None
    b = budget_from(text)
    if b is not None: budget = b
    categories = ['irrigation','spraying','garden','nursery','soil','crop','water','hand tools','safety']
    found = next((c for c in categories if c in t), None)
    if found: application = found
    with connect() as con:
        con.execute('''INSERT INTO requirements(sid,application,budget,updated_at) VALUES(?,?,?,?)
          ON CONFLICT(sid) DO UPDATE SET application=excluded.application,budget=excluded.budget,updated_at=excluded.updated_at''',
          (sid,application,budget,datetime.now().isoformat(timespec='seconds')))

    p = find_product(text,items)
    if any(x in t for x in ['hello','hi','hey','good morning']):
        answer = 'Hello! I can help with products, listed prices, budget-based suggestions, comparisons, and stock status. What do you need?'
    elif any(x in t for x in ['what products','list products','show products','available products','catalogue','catalog']):
        answer = 'Products in the current catalogue:\n' + '\n'.join(f"• {x['name']} (SKU: {x['sku']}) | {money(x)} | {x['stock_status'].replace('_',' ')}" for x in items[:25]) if items else 'No products are loaded. Import a catalogue CSV.'
    elif any(x in t for x in ['price','prices','cost','how much']):
        if p: answer = f"{p['name']} (SKU: {p['sku']}) is listed at {money(p)}. Stock status: {p['stock_status'].replace('_',' ')}."
        else:
            priced=[x for x in items if x['price'] is not None]
            answer = 'Catalogue prices:\n'+'\n'.join(f"• {x['name']} (SKU: {x['sku']}): {money(x)}; stock: {x['stock_status'].replace('_',' ')}" for x in priced[:25]) if priced else 'No prices are listed in the loaded catalogue.'
    elif any(x in t for x in ['compare','comparison','difference',' versus ',' vs ']):
        mentioned=[x for x in items if x['sku'].lower() in t or x['name'].lower() in t]
        if len(mentioned)>=2:
            a,c=mentioned[:2]; answer=f"Comparison:\n• {a['name']}: {money(a)}, category {a['category']}, stock {a['stock_status'].replace('_',' ')}.\n• {c['name']}: {money(c)}, category {c['category']}, stock {c['stock_status'].replace('_',' ')}.\nThe catalogue does not contain enough verified specifications for a technical performance comparison."
        else: answer='Please include two product names or SKUs, for example: Compare DEMO-001 and DEMO-002.'
    elif any(x in t for x in ['recommend','suggest','suitable','need','looking for','under ','below ']):
        candidates=items[:]
        if budget is not None: candidates=[x for x in candidates if x['price'] is not None and x['price']<=budget]
        if application:
            hits=[x for x in candidates if application in x['category'].lower() or application in x['applications'].lower() or application in x['name'].lower()]
            if hits: candidates=hits
        candidates.sort(key=lambda x: x['price'] if x['price'] is not None else 1e99)
        answer=('Possible catalogue matches:\n'+'\n'.join(f"• {x['name']} (SKU: {x['sku']}) | {money(x)} | stock: {x['stock_status'].replace('_',' ')}" for x in candidates[:5])+'\nThese are simple catalogue matches, not guaranteed agronomic advice. Verify product specifications before use.') if candidates else f"No listed product matched the current filters{(' and budget INR '+format(budget,',.2f')) if budget is not None else ''}. Try a higher budget or ask to list all products."
    elif any(x in t for x in ['out of stock','in stock','availability','stock status']):
        if 'out of stock' in t: matches=[x for x in items if x['stock_status']=='out_of_stock']
        elif 'in stock' in t: matches=[x for x in items if x['stock_status']=='in_stock']
        else: matches=items
        answer='Stock status:\n'+'\n'.join(f"• {x['name']} (SKU: {x['sku']}): {x['stock_status'].replace('_',' ')}" for x in matches[:25]) if matches else 'No products match that stock status.'
    elif any(x in t for x in ['warranty','guarantee','certification','voltage','capacity','flow rate','chemical compatibility']):
        answer='That specification is not verified in the loaded catalogue. I will not guess. Please check the official product documentation or ask a sales representative.'
    elif any(x in t for x in ['buy','purchase','place order','order']):
        if p: answer=f"Mock order draft: {p['name']} (SKU: {p['sku']}) at {money(p)}, quantity 1. This is not a real order. Collect customer details and review the catalogue first. This demo currently does not process payment or create a real purchase."
        else: answer='Which product would you like to order? Please provide its exact name or SKU from the catalogue.'
    elif p:
        answer=f"{p['name']} (SKU: {p['sku']})\nCategory: {p['category']}\nDescription: {p['description']}\nPrice: {money(p)}\nStock: {p['stock_status'].replace('_',' ')}"
        if p['applications']: answer+='\nApplications: '+p['applications']
        if p['limitations']: answer+='\nNote: '+p['limitations']
    else:
        answer='I can help with product details, prices, budget-based suggestions, comparisons, and stock status. Mention a product name/SKU, category, or budget. I only use details in the loaded catalogue.'
    with connect() as con:
        now=datetime.now().isoformat(timespec='seconds')
        con.execute('INSERT INTO messages(sid,role,message,created_at) VALUES(?,?,?,?)',(sid,'user',text,now))
        con.execute('INSERT INTO messages(sid,role,message,created_at) VALUES(?,?,?,?)',(sid,'assistant',answer,now))
    return answer


@app.route('/')
def home():
    session.setdefault('sid',str(uuid.uuid4()))
    return render_template('index.html')

@app.get('/api/state')
def state():
    sid=session.setdefault('sid',str(uuid.uuid4()))
    with connect() as con:
        r=con.execute('SELECT application,budget FROM requirements WHERE sid=?',(sid,)).fetchone()
        ms=con.execute('SELECT role,message FROM messages WHERE sid=? ORDER BY id DESC LIMIT 30',(sid,)).fetchall()
    return jsonify(products=products(),product_count=len(products()),requirements=dict(r) if r else {'application':'','budget':None},messages=[dict(x) for x in reversed(ms)])

@app.post('/api/chat')
def chat():
    data=request.get_json(silent=True) or {}; text=str(data.get('message','')).strip()
    if not text: return jsonify(error='Please type a message.'),400
    if len(text)>2000: return jsonify(error='Message is too long.'),400
    return jsonify(reply=reply(text,session.setdefault('sid',str(uuid.uuid4()))))

@app.post('/api/import')
def upload():
    f=request.files.get('file')
    if not f or not f.filename: return jsonify(error='Choose a CSV file first.'),400
    if not f.filename.lower().endswith('.csv'): return jsonify(error='Please select a .csv file.'),400
    try: n=import_csv(f); return jsonify(message=f'Successfully imported {n} products. Previous catalogue replaced.',count=n)
    except Exception as e: return jsonify(error=str(e)),400

@app.post('/api/reset-chat')
def reset():
    session['sid']=str(uuid.uuid4()); return jsonify(message='New chat started.')

@app.get('/health')
def health(): return jsonify(status='ok',products=len(products()))

init_db()
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=False)
