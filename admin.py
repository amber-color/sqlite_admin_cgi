#!/usr/local/bin/python3.7
# -*- coding: utf-8 -*-

import cgi, cgitb, sqlite3, os, html, csv, re, uuid, time
cgitb.enable()

print("Content-Type: text/html; charset=utf-8\n")

form = cgi.FieldStorage()
base_dir = os.path.dirname(os.path.abspath(__file__))

# -----------------
# util
# -----------------
def safe(s):
    if not s: return None
    if any(x in s for x in ["/","\\",".."]): return None
    return s

def getv(name):
    return form.getfirst(name)

def db_path(db):
    return os.path.join(base_dir, db)

def get_dbs():
    return [f for f in os.listdir(base_dir) if f.endswith(".db")]

def get_tables(db):
    conn = sqlite3.connect(db_path(db))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    r = [x[0] for x in cur.fetchall()]
    conn.close()
    return r

def get_cols(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]

def highlight(val, kw, match_type="partial"):
    s = str(val)
    if not kw:
        return html.escape(s)
    if match_type == "exact":
        if s == kw:
            return f'<span style="color:red;font-weight:bold">{html.escape(s)}</span>'
        return html.escape(s)
    result = []
    lower_s, lower_kw = s.lower(), kw.lower()
    i = 0
    while i < len(s):
        pos = lower_s.find(lower_kw, i)
        if pos == -1:
            result.append(html.escape(s[i:]))
            break
        result.append(html.escape(s[i:pos]))
        result.append(f'<span style="color:red;font-weight:bold">{html.escape(s[pos:pos+len(kw)])}</span>')
        i = pos + len(kw)
    return ''.join(result)

# -----------------
# params
# -----------------
db = safe(getv("db"))
table = safe(getv("table"))
mode = getv("mode")
tab = getv("tab") or "create"
page = max(1, int(getv("page") or 1))
search_kw   = getv("search_kw") or ""
search_type = getv("search_type") or "partial"
sql_text       = getv("sql_text") or ""
sql_result     = None
csv_preview_data = None
PAGE_LIST = 100
PAGE_EDIT = 50

def pager(current, total, per_page, base_url):
    pages = (total + per_page - 1) // per_page
    if pages <= 1:
        return ""
    parts = ['<nav><ul class="pagination pagination-sm flex-wrap mt-2">']
    def li(p, label=None, disabled=False):
        cls = "page-item"
        if p == current: cls += " active"
        if disabled: cls += " disabled"
        href = f"{base_url}&page={p}" if not disabled else "#"
        return f'<li class="{cls}"><a class="page-link" href="{href}">{label or p}</a></li>'
    parts.append(li(current-1, "&laquo;", current==1))
    if pages <= 10:
        for p in range(1, pages+1):
            parts.append(li(p))
    else:
        for p in [1, 2]:
            parts.append(li(p))
        if current > 4:
            parts.append('<li class="page-item disabled"><span class="page-link">…</span></li>')
        for p in range(max(3, current-2), min(pages-1, current+3)):
            parts.append(li(p))
        if current < pages - 3:
            parts.append('<li class="page-item disabled"><span class="page-link">…</span></li>')
        for p in [pages-1, pages]:
            parts.append(li(p))
    parts.append(li(current+1, "&raquo;", current==pages))
    parts.append('</ul></nav>')
    return "".join(parts)

# -----------------
# CRUD
# -----------------

if mode == "create_db":
    new = safe(getv("new_db"))
    if new:
        if not new.endswith(".db"):
            new = new + ".db"
        sqlite3.connect(db_path(new)).close()

create_table_error = None
create_table_success = None

if mode == "create_table" and db:
    new_table = (getv("new_table") or "").strip()
    use_pk    = getv("use_pk") or "no"
    pk_raw    = getv("pk_col")

    col_names = [n.strip() for n in form.getlist("col_name")]
    col_types = form.getlist("col_type")

    if not new_table:
        create_table_error = "テーブル名を入力してください"
    elif not re.match(r'^\w+$', new_table):
        create_table_error = "テーブル名に使用できない文字が含まれています"
    else:
        named_idx = [(i, n, t) for i, (n, t) in enumerate(zip(col_names, col_types)) if n]
        if not named_idx:
            create_table_error = "カラムを1つ以上入力してください"
        else:
            bad = [n for _, n, _ in named_idx if not re.match(r'^\w+$', n)]
            if bad:
                create_table_error = f"カラム名 '{bad[0]}' に使用できない文字が含まれています"
            else:
                pk_col_idx = None
                if use_pk == "yes":
                    try:
                        pk_col_idx = int(pk_raw)
                        if pk_col_idx < 0 or pk_col_idx >= len(col_names) or not col_names[pk_col_idx]:
                            create_table_error = "主キーに選択したカラムの名前を入力してください"
                            pk_col_idx = None
                    except (ValueError, TypeError):
                        create_table_error = "主キーの選択が無効です"
                elif use_pk == "yes" and pk_raw is None:
                    create_table_error = "主キーにするカラムを選択してください"

                if not create_table_error:
                    conn_c = sqlite3.connect(db_path(db))
                    existing = [r[0] for r in conn_c.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    if new_table in existing:
                        create_table_error = f"テーブル '{new_table}' は既に存在します"
                        conn_c.close()
                    else:
                        col_defs = []
                        for i, n, t in named_idx:
                            pk = " PRIMARY KEY" if pk_col_idx is not None and i == pk_col_idx else ""
                            col_defs.append(f'"{n}" {t}{pk}')
                        try:
                            conn_c.execute(f'CREATE TABLE "{new_table}" ({",".join(col_defs)})')
                            conn_c.commit()
                            create_table_success = f"テーブル '{new_table}' を作成しました"
                        except Exception as e:
                            create_table_error = str(e)
                        finally:
                            conn_c.close()

if mode == "insert" and db and table:
    conn = sqlite3.connect(db_path(db))
    cols = get_cols(conn, table)
    vals = [getv(c) for c in cols]
    conn.execute(
        f"INSERT INTO {table} VALUES ({','.join(['?']*len(cols))})",
        vals
    )
    conn.commit()
    conn.close()

if mode and mode.startswith("delete_") and db and table:
    rid = mode.split("_")[1]

    conn = sqlite3.connect(db_path(db))
    conn.execute(f'DELETE FROM "{table}" WHERE rowid=?', (rid,))
    conn.commit()
    conn.close()

if mode and mode.startswith("update_") and db and table:
    rid = mode.split("_")[1]

    conn = sqlite3.connect(db_path(db))
    cur = conn.cursor()
    cols = get_cols(conn, table)

    sets = []
    vals = []

    for c in cols:
        v = getv(f"{c}_{rid}")
        sets.append(f"{c}=?")
        vals.append(v)

    vals.append(rid)

    sql = f'UPDATE "{table}" SET {",".join(sets)} WHERE rowid=?'
    print("<pre>", sql, vals, "</pre>")  # ← デバッグ

    cur.execute(sql, vals)
    conn.commit()
    conn.close()

TMP_EXT = ".csv_tmp"

def _csv_decode(raw):
    for enc in ('utf-8-sig', 'cp932', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None

def _csv_tmp_path(tid):
    return os.path.join(base_dir, tid + TMP_EXT)

def _csv_tmp_cleanup():
    for f in os.listdir(base_dir):
        if f.endswith(TMP_EXT):
            fp = os.path.join(base_dir, f)
            if time.time() - os.path.getmtime(fp) > 3600:
                try: os.remove(fp)
                except: pass

if mode == "csv_preview" and db:
    _csv_tmp_cleanup()
    csvfile = form["csvfile"] if "csvfile" in form else None
    if csvfile is not None and csvfile.filename:
        raw = csvfile.file.read()
        decoded = _csv_decode(raw)
        if decoded:
            tid = uuid.uuid4().hex[:16]
            with open(_csv_tmp_path(tid), 'w', encoding='utf-8') as fh:
                fh.write(decoded)
            lines = decoded.splitlines()
            reader = csv.reader(lines)
            skip = bool(getv("skipheader"))
            header_row = next(reader, None) if skip else None
            preview = [r for _, r in zip(range(5), reader)]
            n_cols = len(preview[0]) if preview else (len(header_row) if header_row else 0)
            default_names = header_row if (header_row and len(header_row) == n_cols) \
                            else [f"col{i}" for i in range(n_cols)]
            csv_preview_data = {
                "tid":        tid,
                "n_cols":     n_cols,
                "col_names":  default_names,
                "preview":    preview,
                "new_table":  safe(getv("new_table")) or "",
                "skipheader": "1" if skip else "",
            }

if mode == "csv_import_new" and db:
    tid       = getv("tmp_id") or ""
    new_tbl   = safe(getv("new_table")) or ""
    skip      = bool(getv("skipheader_val"))
    col_names = [n.strip() for n in form.getlist("col_name")]
    col_types = form.getlist("col_type")
    if tid and re.match(r'^[0-9a-f]{16}$', tid) and new_tbl and col_names:
        tmp_path = _csv_tmp_path(tid)
        if os.path.exists(tmp_path):
            with open(tmp_path, encoding='utf-8') as fh:
                lines = fh.read().splitlines()
            reader = csv.reader(lines)
            if skip:
                next(reader, None)
            rows = list(reader)
            if rows:
                col_defs = [f'"{n}" {t}' for n, t in zip(col_names, col_types) if n]
                conn_c = sqlite3.connect(db_path(db))
                try:
                    conn_c.execute(f'CREATE TABLE "{new_tbl}" ({",".join(col_defs)})')
                    for row in rows:
                        if len(row) == len(col_names):
                            conn_c.execute(
                                f'INSERT INTO "{new_tbl}" VALUES ({",".join(["?"]*len(col_names))})',
                                row)
                    conn_c.commit()
                except Exception:
                    pass
                finally:
                    conn_c.close()
            try: os.remove(tmp_path)
            except: pass

if mode == "csv_import" and db:
    target = getv("target")
    csvfile = form["csvfile"] if "csvfile" in form else None
    if csvfile is not None and csvfile.filename:
        raw = csvfile.file.read()
        for enc in ('utf-8-sig', 'cp932', 'utf-8', 'latin-1'):
            try:
                data = raw.decode(enc).splitlines()
                break
            except UnicodeDecodeError:
                continue
        reader = csv.reader(data)
        
        if getv("skipheader"):
            next(reader, None)
        
        rows = list(reader)
        if not rows:
            pass
        
        conn = sqlite3.connect(db_path(db))
        if target == "new":
            new_table = safe(getv("new_table"))
            if new_table:
                cols_def = [f"col{i} TEXT" for i in range(len(rows[0]))]
                conn.execute(f"CREATE TABLE {new_table} ({','.join(cols_def)})")
                table = new_table
        else:
            table = safe(getv("table"))
        
        if table:
            if getv("truncate"):
                conn.execute(f"DELETE FROM {table}")
            
            cols = get_cols(conn, table)
            for row in rows:
                if len(row) != len(cols):
                    continue
                if getv("skipdup"):
                    cur = conn.cursor()
                    cur.execute(f"SELECT 1 FROM {table} WHERE {cols[0]}=?", (row[0],))
                    if cur.fetchone():
                        continue
                if getv("append") or not getv("truncate"):
                    conn.execute(f"INSERT INTO {table} VALUES ({','.join(['?']*len(cols))})", row)
            conn.commit()
        conn.close()

if mode == "execute_sql" and db:
    _sql = sql_text.strip()
    if _sql:
        try:
            _conn = sqlite3.connect(db_path(db))
            _cur  = _conn.cursor()
            _cur.execute(_sql)
            if _cur.description:
                _headers = [d[0] for d in _cur.description]
                _rows    = _cur.fetchall()
                sql_result = {"type": "rows", "headers": _headers, "rows": _rows}
            else:
                _conn.commit()
                sql_result = {"type": "message",
                              "msg": f"OK — {_cur.rowcount} 行に影響しました"}
            _conn.close()
        except Exception as _e:
            sql_result = {"type": "error", "msg": str(_e)}

# -----------------
# HTML
# -----------------
CSS_STYLES = """
/* ── Base ── */
*, *::before, *::after { box-sizing: border-box; }
body {
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  font-size: .875rem;
  margin: 0; padding: 0;
}

/* ── App shell ── */
#app-shell {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1.25rem 1.5rem;
}

/* ── Header ── */
#app-header {
  display: flex;
  align-items: center;
  padding-bottom: .75rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid #d2d2d7;
}
#app-header h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -.015em;
  margin: 0;
}

/* ── Topbar ── */
#topbar {
  background: #ffffff;
  border: 1px solid #d2d2d7;
  border-radius: .625rem;
  padding: .625rem .875rem;
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: .5rem;
}
#topbar label { font-size: .8125rem; color: #6e6e73; margin: 0 .25rem 0 0; }
#topbar .form-control {
  background: #f5f5f7;
  border: 1px solid #d2d2d7;
  border-radius: .375rem;
  font-size: .8125rem;
  height: auto;
  padding: .3rem .55rem;
}
#topbar .form-control:focus { border-color: #0071e3; box-shadow: none; outline: none; }
#topbar .btn { font-size: .8125rem; padding: .3rem .75rem; }

/* ── Main layout ── */
#main-layout { display: flex; align-items: flex-start; gap: .875rem; }

/* ── Sidebar ── */
#sidebar {
  flex-shrink: 0;
  width: 88px;
  background: #ffffff;
  border: 1px solid #d2d2d7;
  border-radius: .625rem;
  padding: .375rem;
}
#sidebar .nav-link {
  display: block;
  color: #3c3c43;
  border-radius: .375rem;
  padding: .45rem .5rem;
  font-size: .8125rem;
  font-weight: 500;
  text-align: center;
  white-space: nowrap;
  text-decoration: none;
}
#sidebar .nav-link:hover { background: #f0f0f5; color: #1d1d1f; }
#sidebar .nav-link.active {
  background: #0071e3;
  color: #ffffff;
  font-weight: 600;
}

/* ── Content panel ── */
#content {
  flex: 1 1 0;
  background: #ffffff;
  border: 1px solid #d2d2d7;
  border-radius: .625rem;
  padding: 1.25rem 1.5rem;
  min-height: 360px;
  min-width: 0;
}

/* ── Tab pane headings ── */
.tab-pane h5 {
  font-size: .75rem;
  font-weight: 700;
  color: #6e6e73;
  text-transform: uppercase;
  letter-spacing: .07em;
  margin-bottom: .875rem;
  padding-bottom: .4rem;
  border-bottom: 1px solid #e8e8ed;
}
.tab-pane hr { border: none; border-top: 1px solid #e8e8ed; margin: 1.25rem 0; }

/* ── Tables ── */
.table { font-size: .79rem; }
.table thead th {
  background: #f5f5f7;
  color: #6e6e73;
  font-size: .69rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  border-top: none;
  border-bottom: 1px solid #d2d2d7 !important;
}
.table td, .table th { border-color: #e8e8ed; vertical-align: middle; }
.table-bordered { border-color: #e8e8ed; }

/* ── Forms ── */
.form-control {
  border-color: #d2d2d7;
  border-radius: .375rem;
  font-size: .8125rem;
}
.form-control:focus {
  border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0,113,227,.12);
}

/* ── Buttons ── */
.btn { border-radius: .375rem; font-size: .8125rem; font-weight: 500; }
.btn-primary  { background: #0071e3; border-color: #0071e3; }
.btn-primary:hover  { background: #005ec4; border-color: #005ec4; color: #fff; }
.btn-success  { background: #28a745; border-color: #28a745; color: #fff; }
.btn-success:hover  { background: #1e8035; border-color: #1e8035; color: #fff; }
.btn-warning  { background: #ff9500; border-color: #ff9500; color: #fff; }
.btn-warning:hover  { background: #e08300; border-color: #e08300; color: #fff; }
.btn-danger   { background: #ff3b30; border-color: #ff3b30; }
.btn-danger:hover   { background: #d42b22; border-color: #d42b22; color: #fff; }
.btn-outline-secondary { border-color: #d2d2d7; color: #3c3c43; background: #fff; }
.btn-outline-secondary:hover { background: #f0f0f5; border-color: #c7c7cc; color: #1d1d1f; }
.btn-outline-danger { border-color: #ff3b30; color: #ff3b30; }
.btn-outline-danger:hover { background: #ff3b30; color: #fff; border-color: #ff3b30; }

/* ── Alerts ── */
.alert { border-radius: .5rem; font-size: .8125rem; }
.alert-success { background: #f0faf3; border-color: #a8dab5; color: #1a5c2e; }
.alert-danger  { background: #fff5f5; border-color: #f5b7b1; color: #7b1f1a; }

/* ── Pagination ── */
.page-link { color: #0071e3; border-color: #d2d2d7; font-size: .75rem; padding: .3rem .6rem; }
.page-item.active .page-link { background: #0071e3; border-color: #0071e3; }
.page-item.disabled .page-link { color: #c7c7cc; }

/* ── CodeMirror ── */
.CodeMirror {
  height: 200px;
  border: 1px solid #d2d2d7;
  border-radius: .375rem;
  font-size: 12.5px;
  font-family: "SF Mono", "Menlo", "Monaco", monospace;
}

/* ── Search highlight ── */
span[style*="color:red"] { color: #ff3b30 !important; font-weight: 600; }
"""

conn = None
cols = []
cur = None
if db and table:
    conn = sqlite3.connect(db_path(db))
    cols = get_cols(conn, table)
    cur = conn.cursor()

print(f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SQLite Admin</title>

<link rel="stylesheet"
href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">

<script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@4.5.2/dist/js/bootstrap.bundle.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
<style>{CSS_STYLES}</style>

</head>
<body>
<div id="app-shell">

<div id="app-header"><h3>SQLite Admin</h3></div>

<div id="topbar">
<form method="get" class="form-inline">
<label>DB</label>
<select name="db" onchange="this.form.submit()" class="form-control form-control-sm mr-3">
<option value="">--</option>
""")

for d in get_dbs():
    sel = "selected" if d==db else ""
    print(f'<option value="{d}" {sel}>{d}</option>')

print("""
</select>

<label>テーブル</label>
<select name="table" onchange="this.form.submit()" class="form-control form-control-sm ml-1">
<option value="">--</option>
""")

if db:
    for t in get_tables(db):
        sel = "selected" if t==table else ""
        print(f'<option value="{t}" {sel}>{t}</option>')

print(f"""
</select>
</form>

<form method="get" class="form-inline">
<input type="hidden" name="mode" value="create_db">
<input name="new_db" class="form-control form-control-sm mr-1" placeholder="新しいDB名" style="width:150px">
<button class="btn btn-sm btn-primary">DB作成</button>
</form>
</div>

<div id="main-layout">

<nav id="sidebar" class="nav flex-column">
<a class="nav-link {'active' if tab=='create' else ''}" href="?db={db or ''}&table={table or ''}&tab=create">作成</a>
<a class="nav-link {'active' if tab=='insert' else ''}" href="?db={db or ''}&table={table or ''}&tab=insert">追加</a>
<a class="nav-link {'active' if tab=='list' else ''}" href="?db={db or ''}&table={table or ''}&tab=list">一覧</a>
<a class="nav-link {'active' if tab=='edit' else ''}" href="?db={db or ''}&table={table or ''}&tab=edit">編集</a>
<a class="nav-link {'active' if tab=='search' else ''}" href="?db={db or ''}&table={table or ''}&tab=search">検索</a>
<a class="nav-link {'active' if tab=='sql' else ''}" href="?db={db or ''}&table={table or ''}&tab=sql">SQL</a>
</nav>

<div id="content" class="tab-content">
""")

# -----------------
# 作成タブ
# -----------------
print(f"""
<div id="create" class="tab-pane fade {'show active' if tab=='create' else ''}">

<h5>テーブル作成</h5>
{"<div class='alert alert-danger py-1'>" + html.escape(create_table_error) + "</div>" if create_table_error else ""}
{"<div class='alert alert-success py-1'>" + html.escape(create_table_success) + "</div>" if create_table_success else ""}
<form id="create_table_form" method="get">
<input type=hidden name=mode value=create_table>
<input type=hidden name=db value="{db or ''}">
<input name=new_table class="form-control mb-2" placeholder="テーブル名">

<div class="mb-2">
  主キー:
  <div class="form-check form-check-inline">
    <input class="form-check-input" type="radio" name="use_pk" id="pk_no" value="no" checked>
    <label class="form-check-label" for="pk_no">なし</label>
  </div>
  <div class="form-check form-check-inline">
    <input class="form-check-input" type="radio" name="use_pk" id="pk_yes" value="yes">
    <label class="form-check-label" for="pk_yes">あり</label>
  </div>
</div>

<div id="col_rows">
  <div class="d-flex align-items-center mb-1">
    <input name=col_name class="form-control form-control-sm mr-1" placeholder="カラム名" style="width:160px">
    <select name=col_type class="form-control form-control-sm mr-1" style="width:110px">
      <option>TEXT</option><option>INTEGER</option><option>REAL</option><option>BLOB</option><option>NULL</option>
    </select>
    <div class="pk-cell mr-2" style="display:none">
      <input type="radio" name="pk_col" value="0" class="pk-radio"> <small class="text-muted">PK</small>
    </div>
    <button type="button" class="btn btn-outline-danger btn-sm col-remove">✕</button>
  </div>
</div>
<button type="button" class="btn btn-outline-secondary btn-sm mb-2" id="col_add">+ カラム追加</button><br>
<button class="btn btn-success btn-sm">作成</button>
</form>

<script>
function pkVisible() {{
  var show = document.querySelector('[name=use_pk]:checked').value === 'yes';
  document.querySelectorAll('.pk-cell').forEach(function(el) {{
    el.style.display = show ? '' : 'none';
  }});
  if (!show) document.querySelectorAll('.pk-radio').forEach(function(r) {{ r.checked = false; }});
}}
document.querySelectorAll('[name=use_pk]').forEach(function(r) {{ r.onchange = pkVisible; }});

function reindexPK() {{
  document.querySelectorAll('#col_rows > div').forEach(function(row, i) {{
    row.querySelector('.pk-radio').value = i;
  }});
}}

function newRow(idx) {{
  var show = document.querySelector('[name=use_pk]:checked').value === 'yes';
  var d = document.createElement('div');
  d.className = 'd-flex align-items-center mb-1';
  d.innerHTML =
    '<input name=col_name class="form-control form-control-sm mr-1" placeholder="カラム名" style="width:160px">'
    + '<select name=col_type class="form-control form-control-sm mr-1" style="width:110px">'
    + '<option>TEXT</option><option>INTEGER</option><option>REAL</option><option>BLOB</option><option>NULL</option>'
    + '</select>'
    + '<div class="pk-cell mr-2" style="' + (show ? '' : 'display:none') + '">'
    + '<input type="radio" name="pk_col" value="' + idx + '" class="pk-radio"> <small class="text-muted">PK</small></div>'
    + '<button type="button" class="btn btn-outline-danger btn-sm col-remove">✕</button>';
  return d;
}}

document.getElementById('col_add').onclick = function() {{
  var idx = document.querySelectorAll('#col_rows > div').length;
  document.getElementById('col_rows').appendChild(newRow(idx));
}};

document.getElementById('col_rows').addEventListener('click', function(e) {{
  if (e.target.classList.contains('col-remove')) {{
    if (document.querySelectorAll('#col_rows > div').length > 1) {{
      e.target.closest('div').remove();
      reindexPK();
    }}
  }}
}});

document.getElementById('create_table_form').onsubmit = function(e) {{
  var tname = this.querySelector('[name=new_table]').value.trim();
  if (!tname) {{ alert('テーブル名を入力してください'); e.preventDefault(); return; }}
  if (!/^\w+$/.test(tname)) {{
    alert('テーブル名に使用できない文字が含まれています');
    e.preventDefault(); return;
  }}
  var allCols = Array.from(this.querySelectorAll('[name=col_name]'));
  var filled = allCols.filter(function(i) {{ return i.value.trim() !== ''; }});
  if (filled.length === 0) {{ alert('カラムを1つ以上入力してください'); e.preventDefault(); return; }}
  for (var i = 0; i < filled.length; i++) {{
    if (!/^\w+$/.test(filled[i].value.trim())) {{
      alert('カラム名「' + filled[i].value.trim() + '」に使用できない文字が含まれています');
      e.preventDefault(); return;
    }}
  }}
  if (document.querySelector('[name=use_pk]:checked').value === 'yes') {{
    if (!document.querySelector('[name=pk_col]:checked')) {{
      alert('主キーにするカラムを選択してください'); e.preventDefault(); return;
    }}
    var pkIdx = parseInt(document.querySelector('[name=pk_col]:checked').value);
    var pkRow = document.querySelectorAll('#col_rows > div')[pkIdx];
    if (!pkRow.querySelector('[name=col_name]').value.trim()) {{
      alert('主キーに選択したカラムの名前を入力してください'); e.preventDefault(); return;
    }}
  }}
}};
</script>
""")

# -----------------
# 作成タブ内 CSVインポート
# -----------------
csv_table_options = ""
if db:
    for t in get_tables(db):
        sel = "selected" if t == table else ""
        csv_table_options += f'<option value="{t}" {sel}>{t}</option>'

print(f'''
<hr>
<h5>CSVインポート</h5>

<form id="csvform" method="post" enctype="multipart/form-data">

<input type="hidden" name="mode" id="csv_mode" value="csv_import">
<input type="hidden" name="db" value="{db or ''}">
<input type="hidden" name="tab" value="create">

CSVファイル:
<input type="file" name="csvfile" class="form-control mb-2">

<h6>取り込み先</h6>
<select name="target" id="csv_target" class="form-control mb-2" onchange="csvTargetChange()">
<option value="existing">既存テーブル</option>
<option value="new">新規テーブル</option>
</select>

<div id="sec_existing">
<h6>既存テーブル設定</h6>
テーブル名:
<select name="table" class="form-control mb-2">
<option value="">--</option>
{csv_table_options}
</select>
<label><input type="checkbox" name="append" checked> 末尾に追加</label><br>
<label><input type="checkbox" name="truncate"> 既存削除して追加</label><br>
<label><input type="checkbox" name="skipdup"> 重複スキップ</label><br>
<label><input type="checkbox" name="skipheader" id="skipheader_existing" checked> 1行目スキップ</label>
</div>

<div id="sec_new" style="display:none;">
<h6>新規テーブル設定</h6>
テーブル名:
<input name="new_table" class="form-control mb-2" placeholder="テーブル名">
<label><input type="checkbox" name="skipheader" id="skipheader_new" checked> 1行目スキップ（ヘッダ行をカラム名に使用）</label>
</div>

<button class="btn btn-primary mt-2" id="csv_submit_btn">インポート</button>

</form>

<div id="progress" class="mt-3" style="display:none;">
<div class="progress">
<div class="progress-bar progress-bar-striped progress-bar-animated" style="width:100%">
処理中...
</div>
</div>
</div>

<script>
function csvTargetChange() {{
  var v = document.getElementById('csv_target').value;
  document.getElementById('sec_existing').style.display = v === 'existing' ? '' : 'none';
  document.getElementById('sec_new').style.display      = v === 'new'      ? '' : 'none';
  document.getElementById('csv_submit_btn').textContent =
    v === 'new' ? '次へ（カラム設定）→' : 'インポート';
  document.getElementById('csv_mode').value =
    v === 'new' ? 'csv_preview' : 'csv_import';
}}
document.getElementById('csvform').onsubmit = function() {{
  document.getElementById('progress').style.display = 'block';
}}
</script>
''')

if csv_preview_data:
    pd = csv_preview_data
    print(f'''
<hr>
<h5>カラム設定 <small class="text-muted">— {html.escape(pd["new_table"])}</small></h5>
<form method="post">
<input type="hidden" name="mode"         value="csv_import_new">
<input type="hidden" name="db"           value="{db or ''}">
<input type="hidden" name="tab"          value="create">
<input type="hidden" name="new_table"    value="{html.escape(pd["new_table"])}">
<input type="hidden" name="tmp_id"       value="{pd["tid"]}">
<input type="hidden" name="skipheader_val" value="{pd["skipheader"]}">
''')
    print('<div class="table-responsive"><table class="table table-bordered table-sm">')
    print('<thead class="thead-light"><tr>')
    for i in range(pd["n_cols"]):
        print(f'<th>カラム {i+1}</th>')
    print('</tr>')
    print('<tr>')
    for i in range(pd["n_cols"]):
        nm = html.escape(pd["col_names"][i]) if i < len(pd["col_names"]) else f"col{i}"
        print(f'<td><input name="col_name" value="{nm}" class="form-control form-control-sm mb-1" placeholder="カラム名"></td>')
    print('</tr><tr>')
    for i in range(pd["n_cols"]):
        print(f'''<td><select name="col_type" class="form-control form-control-sm">
<option>TEXT</option><option>INTEGER</option><option>REAL</option><option>BLOB</option>
</select></td>''')
    print('</tr></thead>')
    if pd["preview"]:
        print('<tbody>')
        for row in pd["preview"]:
            print('<tr>' + ''.join(f'<td class="text-muted small">{html.escape(str(v))}</td>' for v in row) + '</tr>')
        print('</tbody>')
    print('</table></div>')
    print(f'<p class="text-muted small">↑ プレビュー（最大5行）</p>')
    print('<button class="btn btn-success">インポート実行</button></form>')

print('</div>')

# -----------------
# 追加
# -----------------
if db and table:
    cls = "show active" if tab == "insert" else ""
    print(f'<div id="insert" class="tab-pane fade {cls}">')
    print(f'<form method="post">')
    print(f'<input type=hidden name=mode value=insert>')
    print(f'<input type=hidden name=db value="{db}">')
    print(f'<input type=hidden name=table value="{table}">')
    print('<div class="table-responsive"><table class="table table-bordered table-sm"><tr>')
    for c in cols:
        print(f'<th>{html.escape(c)}</th>')
    print('</tr><tr>')
    for c in cols:
        print(f'<td><input name="{c}" class="form-control form-control-sm"></td>')
    print('</tr></table></div>')
    print('<button class="btn btn-primary">追加</button></form></div>')

# -----------------
# 一覧
# -----------------
if db and table:
    cls = "show active" if tab == "list" else ""
    print(f'<div id="list" class="tab-pane fade {cls}">')
    total_list = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    offset_list = (page - 1) * PAGE_LIST
    base_list = f"?db={db}&table={table}&tab=list"
    print(pager(page, total_list, PAGE_LIST, base_list))
    print(f'<p class="text-muted small">{total_list}件中 {offset_list+1}〜{min(offset_list+PAGE_LIST, total_list)}件表示</p>')
    print('<div class="table-responsive"><table class="table table-bordered table-sm">')
    print('<tr><th>rowid</th>')
    for c in cols:
        print(f'<th>{html.escape(c)}</th>')
    print('</tr>')
    for r in cur.execute(f'SELECT rowid,* FROM "{table}" LIMIT {PAGE_LIST} OFFSET {offset_list}'):
        print("<tr>")
        for v in r:
            print(f"<td>{html.escape(str(v))}</td>")
        print("</tr>")
    print("</table></div>")
    print(pager(page, total_list, PAGE_LIST, base_list))
    print("</div>")

# -----------------
# 編集
# -----------------
if db and table:
    cls = "show active" if tab == "edit" else ""
    print(f'<div id="edit" class="tab-pane fade {cls}">')
    total_edit = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    offset_edit = (page - 1) * PAGE_EDIT
    base_edit = f"?db={db}&table={table}&tab=edit"
    print(pager(page, total_edit, PAGE_EDIT, base_edit))
    print(f'<p class="text-muted small">{total_edit}件中 {offset_edit+1}〜{min(offset_edit+PAGE_EDIT, total_edit)}件表示</p>')
    print('<form method="post">')
    print(f'<input type=hidden name=db value="{db}">')
    print(f'<input type=hidden name=table value="{table}">')
    print('<div class="table-responsive">')
    print('<table class="table table-bordered table-sm">')
    print("<tr><th>操作</th><th>rowid</th>")
    for c in cols:
        print(f"<th>{html.escape(c)}</th>")
    print("</tr>")
    for r in cur.execute(f'SELECT rowid,* FROM "{table}" LIMIT {PAGE_EDIT} OFFSET {offset_edit}'):
        rid = r[0]
        print("<tr>")
        print(f'<td style="white-space:nowrap"><button name="mode" value="update_{rid}" class="btn btn-warning btn-sm">更新</button> <button name="mode" value="delete_{rid}" class="btn btn-danger btn-sm" onclick="return confirm(\'削除しますか？\')">削除</button></td>')
        print(f"<td>{rid}</td>")
        for i, c in enumerate(cols):
            val = html.escape(str(r[i+1]))
            print(f'<td><input name="{c}_{rid}" value="{val}" class="form-control form-control-sm"></td>')
        print("</tr>")
    print("</table></div></form>")
    print(pager(page, total_edit, PAGE_EDIT, base_edit))
    print("</div>")

# -----------------
# 検索
# -----------------
if db and table:
    cls = "show active" if tab == "search" else ""
    st = search_type
    print(f'''<div id="search" class="tab-pane fade {cls}">
<form method="get" class="mb-3">
<input type=hidden name=db value="{db}">
<input type=hidden name=table value="{table}">
<input type=hidden name=tab value="search">
<div class="d-flex align-items-center flex-wrap" style="gap:.5rem">
<input name="search_kw" value="{html.escape(search_kw)}" class="form-control form-control-sm" style="width:220px" placeholder="キーワード">
<div class="d-flex" style="gap:1.5rem">
  <label style="white-space:nowrap">
    <input type="radio" name="search_type" value="partial" {"checked" if st=="partial" else ""}> 部分一致
  </label>
  <label style="white-space:nowrap">
    <input type="radio" name="search_type" value="exact" {"checked" if st=="exact" else ""}> 完全一致
  </label>
  <label style="white-space:nowrap">
    <input type="radio" name="search_type" value="prefix" {"checked" if st=="prefix" else ""}> 前方一致
  </label>
  <label style="white-space:nowrap">
    <input type="radio" name="search_type" value="suffix" {"checked" if st=="suffix" else ""}> 後方一致
  </label>
</div>
<button class="btn btn-primary btn-sm">検索</button>
</div>
</form>
''')

    if search_kw:
        if search_type == "exact":
            pattern, op = search_kw, "="
        elif search_type == "prefix":
            pattern, op = search_kw + "%", "LIKE"
        elif search_type == "suffix":
            pattern, op = "%" + search_kw, "LIKE"
        else:
            pattern, op = "%" + search_kw + "%", "LIKE"

        conditions = " OR ".join([f'CAST("{c}" AS TEXT) {op} ?' for c in cols])
        hits = conn.execute(
            f'SELECT rowid,* FROM "{table}" WHERE {conditions}',
            [pattern] * len(cols)
        ).fetchall()

        print(f'<p class="text-muted small">{len(hits)}件ヒット</p>')
        if hits:
            print('<div class="table-responsive"><table class="table table-bordered table-sm">')
            print('<tr><th>rowid</th>')
            for c in cols:
                print(f'<th>{html.escape(c)}</th>')
            print('</tr>')
            for r in hits:
                print('<tr>')
                print(f'<td>{r[0]}</td>')
                for v in r[1:]:
                    print(f'<td>{highlight(v, search_kw, search_type)}</td>')
                print('</tr>')
            print('</table></div>')

    print('</div>')

# -----------------
# SQL タブ
# -----------------
if db:
    cls = "show active" if tab == "sql" else ""
    print(f'''<div id="sql" class="tab-pane fade {cls}">
<form method="get" id="sql_form">
<input type=hidden name=db value="{db}">
<input type=hidden name=table value="{table or ''}">
<input type=hidden name=tab value="sql">
<input type=hidden name=mode value=execute_sql>
<textarea id="sql_editor" name="sql_text">{html.escape(sql_text)}</textarea>
<div class="mt-2 mb-3">
  <button class="btn btn-primary btn-sm">実行</button>
  <span class="text-muted small ml-2">Ctrl+Enter でも実行</span>
</div>
</form>
''')

    if sql_result:
        t = sql_result["type"]
        if t == "error":
            print(f'<div class="alert alert-danger py-2"><strong>エラー:</strong> {html.escape(sql_result["msg"])}</div>')
        elif t == "message":
            print(f'<div class="alert alert-success py-2">{html.escape(sql_result["msg"])}</div>')
        elif t == "rows":
            hdrs = sql_result["headers"]
            rws  = sql_result["rows"]
            print(f'<p class="text-muted small">{len(rws)} 件</p>')
            print('<div class="table-responsive"><table class="table table-bordered table-sm">')
            print('<tr>' + ''.join(f'<th>{html.escape(str(h))}</th>' for h in hdrs) + '</tr>')
            for r in rws:
                print('<tr>' + ''.join(
                    f'<td>{html.escape(str(v))}</td>' if v is not None
                    else '<td><em class="text-muted">NULL</em></td>'
                    for v in r) + '</tr>')
            print('</table></div>')

    print(f'''<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/sql/sql.min.js"></script>
<script>
(function() {{
  var ta = document.getElementById('sql_editor');
  if (!ta) return;
  var LS_KEY = 'sqlite_admin_sql_{db}';
  var editor = CodeMirror.fromTextArea(ta, {{
    mode: 'text/x-sql',
    lineNumbers: true,
    indentWithTabs: false,
    smartIndent: true,
    lineWrapping: true,
    autofocus: {'true' if tab == 'sql' else 'false'},
    extraKeys: {{
      'Ctrl-Enter': function() {{
        document.getElementById('sql_form').dispatchEvent(new Event('submit', {{bubbles:true}}));
        document.getElementById('sql_form').submit();
      }}
    }}
  }});

  // サーバーから送られた SQL がない場合のみ localStorage から復元
  if (!ta.value.trim()) {{
    var saved = localStorage.getItem(LS_KEY);
    if (saved) editor.setValue(saved);
  }}

  // 編集のたびに localStorage に保存
  editor.on('change', function() {{
    localStorage.setItem(LS_KEY, editor.getValue());
  }});

  document.getElementById('sql_form').addEventListener('submit', function() {{
    editor.save();
    localStorage.setItem(LS_KEY, editor.getValue());
  }});
}})();
</script>
</div>
''')

if conn:
    conn.close()

print("</div></div></div></body></html>")
