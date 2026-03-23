#!/usr/local/bin/python3.7
# -*- coding: utf-8 -*-

import cgi, cgitb, sqlite3, os, html, csv, re
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

<div class="d-flex align-items-center flex-wrap mb-3" style="gap:.5rem">
<form method="get" class="form-inline">
DB:
<select name="db" onchange="this.form.submit()" class="form-control form-control-sm ml-1 mr-3">
<option value="">--</option>
""")

for d in get_dbs():
    sel = "selected" if d==db else ""
    print(f'<option value="{d}" {sel}>{d}</option>')

print("""
</select>

テーブル:
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

<ul class="nav nav-tabs">
<li class="nav-item"><a class="nav-link {'active' if tab=='create' else ''}" href="?db={db or ''}&table={table or ''}&tab=create">作成</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='insert' else ''}" href="?db={db or ''}&table={table or ''}&tab=insert">追加</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='list' else ''}" href="?db={db or ''}&table={table or ''}&tab=list">一覧</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='edit' else ''}" href="?db={db or ''}&table={table or ''}&tab=edit">編集</a></li>
<li class="nav-item"><a class="nav-link {'active' if tab=='search' else ''}" href="?db={db or ''}&table={table or ''}&tab=search">検索</a></li>
</ul>

<div class="tab-content mt-3">
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
<div>
  <label class="form-check-label mr-2 ml-1">
    <input class="form-check-input" type="radio" name="search_type" value="partial" {"checked" if st=="partial" else ""}> 部分一致
  </label>
  <label class="form-check-label mr-2">
    <input class="form-check-input" type="radio" name="search_type" value="exact" {"checked" if st=="exact" else ""}> 完全一致
  </label>
  <label class="form-check-label mr-2">
    <input class="form-check-input" type="radio" name="search_type" value="prefix" {"checked" if st=="prefix" else ""}> 前方一致
  </label>
  <label class="form-check-label mr-2">
    <input class="form-check-input" type="radio" name="search_type" value="suffix" {"checked" if st=="suffix" else ""}> 後方一致
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

if conn:
    conn.close()

print("</div></body></html>")
