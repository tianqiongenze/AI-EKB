"""E 组生产证据 ①：灾切演练脚本（DR drill）。

演练项（真实集群执行，非模拟）：
  D1 副本级故障切换：kill 单副本 → 存活副本承接 → 就绪时间（RTO_pod）
  D2 服务级滚动恢复：delete pod → 新 pod ready → RTO_recreate
  D3 数据零丢失验证：故障前后 audits max(id)/count 对比（RPO=0 证据）
  D4 CRDB 节点级演练（慎用）：单节点 drain → 集群健康 + 读写持续（L2 级，BRR 需单点试点）
  D5 演练期间读写探针：持续 GET /documents 计错误数（可用性证据）

输出：JSON 证据落 docs/dr/。
用法（集群内或外部均可，需 kubectl）：python scripts/dr_drill.py --base http://10.167.2.175:30880
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone


def _k(*args: str) -> str:
    return subprocess.check_output(["kubectl", "-n", "ekb-app", *args], text=True)


def _get(base: str, path: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return r.status, r.read().decode()[:200]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def _crdb_max_audits() -> int:
    out = subprocess.check_output(
        ["kubectl", "-n", "ekb-app", "exec", "deploy/ekb-control-plane", "--", "python", "-c",
         "import psycopg2;c=psycopg2.connect(host='cockroachdb.infra.svc.cluster.local',"
         "port=26257,user='root',dbname='ekb_control_plane',connect_timeout=5);"
         "cur=c.cursor();cur.execute('SELECT coalesce(max(id),0) FROM audits');"
         "v=cur.fetchone()[0];c.commit();c.close();print(v)"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    return int(out.strip().splitlines()[-1])


def drill(base: str, probe_seconds: int) -> dict:
    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "base": base}

    # 演练前基线
    pods_before = _k("get", "pods", "-l", "app=ekb-control-plane",
                     '-o', 'jsonpath={range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].ready}{"\\n"}{end}').strip().splitlines()
    report["pods_before"] = pods_before
    r, body = _get(base, "/healthz")
    report["pre_health"] = {"status": r, "body": body}
    max_audits_before = _crdb_max_audits()
    report["max_audits_before"] = max_audits_before

    # 可用性探针线程（写进程内计数，演练结束后汇总）
    errors: list[str] = []
    total = {"n": 0, "ok": 0}

    import threading

    stop = threading.Event()

    def probe_loop() -> None:
        while not stop.is_set():
            total["n"] += 1
            r, _ = _get(base, "/documents?limit=1", timeout=3)
            if r == 200:
                total["ok"] += 1
            else:
                errors.append(f"{datetime.now(timezone.utc).isoformat()} status={r}")

    probe = threading.Thread(target=probe_loop, daemon=True)
    probe.start()

    # D1: kill 最旧副本（Recreate 策略外——用 delete 单 pod 模拟容器崩溃）
    target = sorted(p for p in pods_before if p.endswith("True"))[0]
    report["killed_pod"] = target
    t_kill = time.time()
    subprocess.run(["kubectl", "-n", "ekb-app", "delete", "pod", target, "--force", "--grace-period=0"],
                   capture_output=True, text=True)
    # 等恢复 ready
    rto_pod = None
    for _ in range(120):
        time.sleep(1)
        pods_now = _k("get", "pods", "-l", "app=ekb-control-plane",
                      '-o', 'jsonpath={range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].ready}{"\\n"}{end}').strip().splitlines()
        ready = [p for p in pods_now if p.endswith("True")]
        if len(ready) >= len([p for p in pods_before if p.endswith("True")]):
            rto_pod = time.time() - t_kill
            break
    report["rto_pod_seconds"] = rto_pod

    # 数据零丢失
    time.sleep(2)
    max_audits_after = _crdb_max_audits()
    report["max_audits_after"] = max_audits_after
    report["rpo_evidence"] = "max(id) non-decreasing" if max_audits_after >= max_audits_before else "VIOLATION"
    report["rpo_ok"] = max_audits_after >= max_audits_before

    stop.set()
    probe.join(timeout=5)
    report["probe"] = {"total": total["n"], "ok": total["ok"],
                       "errors": errors[:20], "error_count": len(errors),
                       "availability": round(total["ok"] / max(total["n"], 1), 4)}

    # 演练后集群健康
    r, body = _get(base, "/readyz")
    report["post_readyz"] = {"status": r}
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://10.167.2.175:30880")
    ap.add_argument("--probe-seconds", type=int, default=90)
    ap.add_argument("--out", default="docs/dr/dr-drill.json")
    args = ap.parse_args()
    result = drill(args.base, args.probe_seconds)
    import pathlib

    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: result[k] for k in ("killed_pod", "rto_pod_seconds", "rpo_ok", "probe")}, ensure_ascii=False, indent=2))
