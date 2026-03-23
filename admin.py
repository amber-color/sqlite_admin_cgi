#!/usr/local/bin/python3.7
# -*- coding: utf-8 -*-

import cgi, cgitb, sqlite3, os, html, csv
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

# -----------------
# params
# -----------------
db = safe(getv("db"))
table = safe(getv("table"))
mode = getv("mode")
tab = getv("tab") or "create"
page = max(1, int(getv("page") or 1))
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

if mode == "create_table" and db:
    new_table = safe(getv("new_table"))
    cols = []
    for n,t in zip(form.getlist("col_name"), form.getlist("col_type")):
        if n:
            cols.append(f"{n} {t}")
    if new_table and cols:
        sqlite3.connect(db_path(db)).execute(
            f"CREATE TABLE {new_table} ({','.join(cols)})"
        )

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

# -----------------
# HTML
# -----------------
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

</head>
<body class="p-3">

<h3>SQLite Admin</h3>

<form method="get" class="mb-3">
DB:
<select name="db" onchange="this.form.submit()">
<option value="">--</option>
""")

for d in get_dbs():
    sel = "selected" if d==db else ""
    print(f'<option value="{d}" {sel}>{d}</option>')

print("""
</select>

テーブル:
<select name="table" onchange="this.form.submit()">
<option value="">--</option>
""")

if db:
    for t in get_tables(db):
        sel = "selected" if t==table else ""
        print(f'<option value="{t}" {sel}>{t}</option>')

print(f"""
</select>
</form>

<ul class="nav nav-tabs">
<li class="nav-item"><a class="nav-link {'active' if tab=='create' else ''}" href="?db={db or ''}&table={table or ''}&tab=create">作成</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='insert' else ''}" href="?db={db or ''}&table={table or ''}&tab=insert">追加</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='list' else ''}" href="?db={db or ''}&table={table or ''}&tab=list">一覧</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='edit' else ''}" href="?db={db or ''}&table={table or ''}&tab=edit">編集</a></li>
</ul>

<div class="tab-content mt-3">
""")

# -----------------
# 作成タブ
# -----------------
print(f"""
<div id="create" class="tab-pane fade {'show active' if tab=='create' else ''}">

<h5>DB作成</h5>
<form>
<input type=hidden name=mode value=create_db>
<input name=new_db class="form-control mb-2">
<button class="btn btn-primary">作成</button>
</form>

<h5>テーブル作成</h5>
<form>
<input type=hidden name=mode value=create_table>
<input type=hidden name=db value="{db or ''}">
<input name=new_table class="form-control mb-2">

""")

for i in range(5):
    print(f"""
    <div class="form-inline mb-1">
    <input name=col_name class="form-control mr-2">
    <select name=col_type class="form-control">
    <option>TEXT</option>
    <option>INTEGER</option>
    <option>REAL</option>
    <option>BLOB</option>
    <option>NULL</option>
    </select>
    </div>
    """)

print('<button class="btn btn-success">作成</button></form>')

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

<input type="hidden" name="mode" value="csv_import">
<input type="hidden" name="db" value="{db or ''}">

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
<label><input type="checkbox" name="skipheader" checked> 1行目スキップ</label>
</div>

<div id="sec_new" style="display:none;">
<h6>新規テーブル設定</h6>
テーブル名:
<input name="new_table" class="form-control mb-2">
<label><input type="checkbox" name="skipheader" checked> 1行目スキップ</label>
</div>

<button class="btn btn-primary mt-2">インポート</button>

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
}}
document.getElementById('csvform').onsubmit = function() {{
  document.getElementById('progress').style.display = 'block';
}}
</script>
''')

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

if conn:
    conn.close()

print("</div></body></html>")
