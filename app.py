import os
import sqlite3
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get('OPSFLOW_DB', BASE / 'opsflow.db'))
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-for-production')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL,
 area TEXT NOT NULL CHECK (area IN ('Operacional','Financeiro','TI')),
 priority TEXT NOT NULL CHECK (priority IN ('Baixa','Média','Alta','Crítica')),
 status TEXT NOT NULL DEFAULT 'Aberto' CHECK(status IN ('Aberto','Em andamento','Resolvido')),
 details TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ticket_id INTEGER NOT NULL REFERENCES tickets(id),
 old_status TEXT, new_status TEXT NOT NULL, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
 status TEXT NOT NULL DEFAULT 'Pendente' CHECK(status IN ('Pendente','Pago')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 site TEXT NOT NULL,
 staff TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('Planejado','Chegada registrada')),
 latitude REAL,
 longitude REAL,
 accuracy_m REAL,
 created_at TEXT NOT NULL,
 arrived_at TEXT,
 CHECK ((status='Planejado' AND latitude IS NULL AND longitude IS NULL AND accuracy_m IS NULL AND arrived_at IS NULL)
    OR (status='Chegada registrada' AND latitude IS NOT NULL AND longitude IS NOT NULL AND accuracy_m IS NOT NULL AND arrived_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS audit_checks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item TEXT NOT NULL,
 result TEXT NOT NULL CHECK(result IN ('OK','Atenção')),
 notes TEXT NOT NULL DEFAULT '',
 checked_at TEXT NOT NULL
);
'''

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init_db():
    with connect() as con:
        con.executescript(SCHEMA)

def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

def parse_amount(raw):
    clean = raw.strip().replace('R$', '').replace(' ', '')
    if ',' in clean:
        clean = clean.replace('.', '').replace(',', '.')
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        value = Decimal(clean)
    except InvalidOperation:
        raise ValueError('Valor monetário inválido')
    if not value.is_finite() or value <= 0:
        raise ValueError('Valor deve ser positivo')
    cents = int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if cents <= 0 or cents > 1000000000:
        raise ValueError('Valor fora do limite permitido')
    return cents

@app.template_filter('brl')
def brl(cents):
    return f'R$ {cents / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

def notify_n8n(ticket):
    endpoint = os.environ.get('N8N_WEBHOOK_URL', '').strip()
    if ticket['priority'] not in ('Alta', 'Crítica'):
        return 'Prioridade sem alerta automático', 'success'
    if not endpoint:
        return 'Alerta não enviado: configure N8N_WEBHOOK_URL.', 'warning'
    data = json.dumps(ticket, ensure_ascii=False).encode('utf-8')
    try:
        req = urllib.request.Request(endpoint, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=3) as response:
            return f'n8n recebeu o chamado: HTTP {response.status}. Consulte a execução para confirmar o e-mail.', 'success'
    except Exception as exc:
        app.logger.warning('Falha no webhook do chamado #%s: %s', ticket['id'], type(exc).__name__)
        return 'Falha no envio ao n8n; chamado salvo localmente. Não há reenvio automático.', 'warning'

@app.route('/')
def home():
    with connect() as con:
        tickets = con.execute('SELECT * FROM tickets ORDER BY id DESC LIMIT 12').fetchall()
        counts = {r['status']: r['n'] for r in con.execute('SELECT status,COUNT(*) n FROM tickets GROUP BY status')}
        pending = con.execute("SELECT COALESCE(SUM(amount_cents),0) total FROM charges WHERE status='Pendente'").fetchone()['total']
        audits = con.execute('SELECT * FROM audit_checks ORDER BY id DESC LIMIT 4').fetchall()
    return render_template('index.html', tickets=tickets, counts=counts, pending=pending, audits=audits)

@app.post('/tickets')
def create_ticket():
    title = request.form.get('title', '').strip()
    area = request.form.get('area', '')
    priority = request.form.get('priority', '')
    details = request.form.get('details', '').strip()
    if not (1 <= len(title) <= 120 and area in ('Operacional','Financeiro','TI') and priority in ('Baixa','Média','Alta','Crítica') and len(details) <= 2000):
        flash('Verifique os campos do chamado.', 'error'); return redirect(url_for('home'))
    timestamp = now()
    with connect() as con:
        cur = con.execute('INSERT INTO tickets (title,area,priority,details,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                          (title,area,priority,details,timestamp,timestamp))
        ticket_id = cur.lastrowid
        con.execute('INSERT INTO ticket_history(ticket_id,old_status,new_status,changed_at) VALUES (?,NULL,?,?)',(ticket_id,'Aberto',timestamp))
    result, category = notify_n8n({'id':ticket_id,'title':title,'area':area,'priority':priority,'description':details,'status':'Aberto','created_at':timestamp})
    flash(f'Chamado #{ticket_id} criado. {result}', category); return redirect(url_for('home'))

@app.post('/tickets/<int:ticket_id>/status')
def ticket_status(ticket_id):
    status = request.form.get('status','')
    if status not in ('Aberto','Em andamento','Resolvido'):
        return 'Status inválido', 400
    with connect() as con:
        old = con.execute('SELECT status FROM tickets WHERE id=?',(ticket_id,)).fetchone()
        if old is None: return 'Chamado não encontrado',404
        con.execute('UPDATE tickets SET status=?,updated_at=? WHERE id=?',(status,now(),ticket_id))
        con.execute('INSERT INTO ticket_history(ticket_id,old_status,new_status,changed_at) VALUES (?,?,?,?)',(ticket_id,old['status'],status,now()))
    flash('Status atualizado e registrado no histórico.','success'); return redirect(url_for('home'))

@app.route('/financeiro', methods=['GET','POST'])
def finance():
    if request.method == 'POST':
        customer = request.form.get('customer','').strip()
        if not (1 <= len(customer) <= 100):
            flash('Informe um cliente válido.','error');return redirect(url_for('finance'))
        try: amount = parse_amount(request.form.get('amount',''))
        except ValueError as exc:
            flash(str(exc),'error');return redirect(url_for('finance'))
        with connect() as con:
            con.execute('INSERT INTO charges(customer,amount_cents,created_at) VALUES (?,?,?)',(customer,amount,now()))
        flash('Cobrança registrada.','success');return redirect(url_for('finance'))
    with connect() as con:
        charges = con.execute('SELECT * FROM charges ORDER BY id DESC').fetchall()
    return render_template('finance.html',charges=charges)

@app.post('/charges/<int:charge_id>/pay')
def pay(charge_id):
    with connect() as con:
        cur = con.execute("UPDATE charges SET status='Pago' WHERE id=? AND status='Pendente'",(charge_id,))
    if cur.rowcount == 0: return 'Cobrança inexistente ou já paga',400
    flash('Pagamento registrado.','success');return redirect(url_for('finance'))

@app.route('/auditoria', methods=['GET','POST'])
def audits():
    if request.method == 'POST':
        item = request.form.get('item','')
        result = request.form.get('result','')
        notes = request.form.get('notes','').strip()
        if item not in ('Backup','Erros','Acessos') or result not in ('OK','Atenção') or len(notes)>500:
            return 'Dados inválidos',400
        with connect() as con:
            con.execute('INSERT INTO audit_checks(item,result,notes,checked_at) VALUES (?,?,?,?)',(item,result,notes,now()))
        flash('Verificação registrada.','success');return redirect(url_for('audits'))
    with connect() as con:
        checks = con.execute('SELECT * FROM audit_checks ORDER BY id DESC LIMIT 30').fetchall()
    return render_template('audits.html',checks=checks)

@app.route('/operacoes', methods=['GET', 'POST'])
def operations():
    if request.method == 'POST':
        site = request.form.get('site','').strip()
        staff = request.form.get('staff','').strip()
        if not (1 <= len(site) <= 120 and 1 <= len(staff) <= 100):
            flash('Preencha local e responsável (dados fictícios).', 'error')
            return redirect(url_for('operations'))
        with connect() as con:
            con.execute("INSERT INTO visits(site,staff,status,created_at) VALUES (?,?,'Planejado',?)", (site, staff, now()))
        flash('Atendimento criado. O registro de chegada exige ação do usuário.', 'success')
        return redirect(url_for('operations'))
    with connect() as con:
        visits = con.execute('SELECT * FROM visits ORDER BY id DESC LIMIT 50').fetchall()
    return render_template('operations.html', visits=visits)

@app.post('/api/visits/<int:visit_id>/checkin')
def checkin(visit_id):
    from math import isfinite
    data = request.get_json(silent=True)
    if not isinstance(data,dict) or data.get('consent') is not True:
        return jsonify({'error':'Consentimento no momento do check-in é obrigatório.'}),400
    try:
        lat, lon, accuracy = (float(data[key]) for key in ('latitude','longitude','accuracy_m'))
    except (ValueError,TypeError,KeyError,OverflowError):
        return jsonify({'error':'Coordenadas inválidas.'}),400
    if not all(map(isfinite,(lat,lon,accuracy))) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= accuracy <= 100000):
        return jsonify({'error':'Coordenadas fora dos limites.'}),400
    # Acima de 100m, não aprovar a chegada automaticamente; usuário pode tentar novamente.
    if accuracy > 100:
        return jsonify({'error':'Precisão insuficiente (>100 m); tente em área aberta.'}),422
    with connect() as con:
        row = con.execute('SELECT status FROM visits WHERE id=?',(visit_id,)).fetchone()
        if row is None:
            return jsonify({'error':'Atendimento não encontrado.'}),404
        if row['status'] != 'Planejado':
            return jsonify({'error':'Chegada já registrada.'}),409
        con.execute("UPDATE visits SET status='Chegada registrada',latitude=?,longitude=?,accuracy_m=?,arrived_at=? WHERE id=? AND status='Planejado'", (lat,lon,accuracy,now(),visit_id))
    return jsonify({'ok':True,'message':'Chegada registrada com horário do servidor.'})

@app.route('/health')
def health():
    try:
        with connect() as con: con.execute('SELECT 1').fetchone()
        return jsonify({'status':'ok','database':'connected'})
    except sqlite3.Error:
        return jsonify({'status':'error','database':'unavailable'}),503

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT','5000')),debug=False)
