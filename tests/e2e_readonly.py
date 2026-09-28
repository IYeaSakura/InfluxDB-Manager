# -*- coding: utf-8 -*-
"""只读端到端测试：连接图中时序库（10.82.10.103:31123 / zn_data / sa）。
仅使用只读操作，禁止任何增删改（无 CREATE/DROP/WRITE/KILL/GRANT 等）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from net.sakurain.influxdbstudio.core.client import InfluxDbApiError, create_client
from net.sakurain.influxdbstudio.core.models import InfluxDbConnection

conn = InfluxDbConnection.create(name="zn_data", host="10.82.10.103", port=31123,
                                 username="sa", password="sa", database="zn_data")
client = create_client(conn)

ok = lambda name: print(f"[PASS] {name}")
fail = lambda name, e: print(f"[FAIL] {name}: {type(e).__name__}: {e}")

# 1. Ping
try:
    p = client.ping()
    ok(f"ping -> success={p.Success}, version={p.Version}, {p.ResponseTime:.0f} ms")
except Exception as e:
    fail("ping", e); sys.exit(1)

# 2. 数据库列表
try:
    dbs = client.get_database_names()
    ok(f"SHOW DATABASES -> {dbs}")
except Exception as e:
    fail("get_database_names", e)

# 3. measurement 列表
try:
    ms = client.get_measurement_names("zn_data")
    ok(f"SHOW MEASUREMENTS -> {len(ms)} 个: {ms[:10]}{' ...' if len(ms) > 10 else ''}")
except Exception as e:
    fail("get_measurement_names", e); ms = []

# 4. 取前 2 个 measurement 做 tag/field/series 只读探测
for m in ms[:2]:
    for name, fn in [
        (f"tag_keys({m})", lambda: client.get_tag_keys("zn_data", m)),
        (f"field_keys({m})", lambda: client.get_field_keys("zn_data", m)),
        (f"series({m})", lambda: client.get_series_names("zn_data", m)),
    ]:
        try:
            r = fn()
            ok(f"{name} -> {len(r)} 条")
        except Exception as e:
            fail(name, e)
    try:
        keys = client.get_tag_keys("zn_data", m)
        if keys:
            tvs = client.get_tag_values("zn_data", m, keys[0])
            ok(f"tag_values({m}, {keys[0]}) -> {len(tvs)} 条, 示例: "
               f"{[(t.Name, t.Value) for t in tvs[:3]]}")
    except Exception as e:
        fail(f"tag_values({m})", e)

# 5. SELECT 只读查询（带 LIMIT，双保险）
for m in ms[:2]:
    try:
        results = client.query("zn_data", f'SELECT * FROM "{m}" LIMIT 3')
        total = sum(len(s.Values) for s in results)
        cols = results[0].Columns if results else []
        ok(f"SELECT * FROM {m} LIMIT 3 -> {len(results)} 个 series, {total} 行, 列: {cols[:8]}")
    except Exception as e:
        fail(f"select({m})", e)

# 6. 运行中查询（SHOW QUERIES 为只读）
try:
    rq = client.get_running_queries()
    ok(f"SHOW QUERIES -> {len(rq)} 条")
except Exception as e:
    fail("get_running_queries", e)

# 7. 诊断与统计（只读）
try:
    d = client.get_diagnostics()
    ok(f"SHOW DIAGNOSTICS -> version={d.BuildVersion}, go={d.GoVersion}, "
       f"host={d.Hostname}, uptime={d.Uptime}")
except Exception as e:
    fail("get_diagnostics", e)

try:
    st = client.get_stats()
    groups = {k: len(v) for k, v in st.groups().items() if v}
    ok(f"SHOW STATS -> {groups}")
except Exception as e:
    fail("get_stats", e)

print("\n只读测试完成，未执行任何增删改操作。")
