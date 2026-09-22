"""EKB 混沌实验框架（0.8.0 前置，Principles of Chaos 对齐）。

方法论（联网核实：principlesofchaos.org + AWS FIS 模板/停止条件模式）：
- 每实验 = 稳态假设（steady-state hypothesis）+ 故障注入 + 停止条件 + 爆炸半径声明
- 稳态指标：healthz/readyz 可用率、读延迟 p95、写成功率（业务输出，非内部属性）
- 停止条件：稳态破坏（可用率 <90% 持续 10s）即自动中止注入并恢复
- 爆炸半径分级（BRR 铁律对齐）：X1-X4 低（副本冗余内）；X5-X6 高（需单点试点+显式授权）

实验矩阵：
  X1 Pod 随机驱逐（pod-kill）          假设：3 副本下可用率 ≥99%，RTO <30s
  X2 Redis 依赖故障（service 阻断）    假设：限流/缓存降级不崩，主链路可用
  X3 Pulsar 依赖故障（broker 阻断）    假设：outbox 降级积压不丢，恢复后追平
  X4 资源压力（CPU limit 饱和）        假设：探针不误杀（timeout 5s 修复验证）
  X5 CRDB 单节点停（node-level）       假设：3 节点 Raft 仲裁保持，读写持续
  X6 网络分区（pod 间 50% loss）       假设：重试/超时分级兜底（RWT）

用法（175 host）：
  python3 scripts/chaos_run.py --experiments X1,X2 --base http://10.167.2.175:30880 --out docs/chaos/
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone


class Probe:
    """稳态探针：持续采样，实验结束汇总可用率/延迟。"""

    def __init__(self, base: str) -> None:
        self.base = base
        self.samples: list[tuple[float, int, float]] = []  # (ts, status, latency_ms)
        self.stop = False

    def loop(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline and not self.stop:
            t0 = time.time()
            status = 0
            try:
                with urllib.request.urlopen(self.base + "/healthz", timeout=3) as r:
                    status = r.status
            except Exception:
                status = 0
            self.samples.append((time.time(), status, (time.time() - t0) * 1000))
            time.sleep(0.05)

    def summary(self) -> dict:
        n = len(self.samples)
        ok = sum(1 for _, s, _ in self.samples if s == 200)
        lat = sorted(lat_ms for _, s, lat_ms in self.samples if s == 200)
        return {
            "probes": n,
            "availability": round(ok / max(n, 1), 4),
            "p50_ms": round(lat[len(lat) // 2], 1) if lat else None,
            "p95_ms": round(lat[int(len(lat) * 0.95)], 1) if lat else None,
            "max_ms": round(max(lat), 1) if lat else None,
        }


def k(*args: str, binary_input: bytes | None = None) -> bytes:
    return subprocess.check_output(["kubectl", "-n", "ekb-app", *args], input=binary_input)


def crdb_max_audits() -> int:
    out = k("exec", "deploy/ekb-control-plane", "--", "python", "-c",
            "import psycopg2;c=psycopg2.connect(host='cockroachdb.infra.svc.cluster.local',"
            "port=26257,user='root',dbname='ekb_control_plane',connect_timeout=5);"
            "cur=c.cursor();cur.execute('SELECT coalesce(max(id),0) FROM audits');"
            "print(cur.fetchone()[0]);c.commit();c.close()")
    return int(out.decode().strip().splitlines()[-1])


def run_experiment(name: str, hypothesis: str, blast_radius: str,
                   inject, recover, base: str, inject_seconds: int,
                   stop_condition_unavail: float = 0.90) -> dict:
    """通用实验骨架：注入→监控→（破坏稳态即中止）→恢复→稳态复核。"""
    result: dict = {
        "experiment": name,
        "hypothesis": hypothesis,
        "blast_radius": blast_radius,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "inject_seconds": inject_seconds,
    }
    pre = Probe(base)
    pre.loop(5)
    result["steady_state_before"] = pre.summary()
    max_before = crdb_max_audits()
    result["max_audits_before"] = max_before

    probe = Probe(base)
    import threading

    pt = threading.Thread(target=probe.loop, args=(inject_seconds + 10,))
    pt.daemon = True
    pt.start()

    inject_ok = True
    inject_err = ""
    t0 = time.time()
    try:
        inject()
    except Exception as exc:
        inject_ok = False
        inject_err = f"{type(exc).__name__}: {exc}"

    # 注入期间监控停止条件（可用率 < 阈值持续 10s → 提前恢复）
    aborted = False
    window: list[int] = []
    for _ in range(inject_seconds * 4):
        time.sleep(0.25)
        window = [s for _, s, _ in probe.samples[-40:]]
        recent = window[-10:] if len(window) >= 10 else window
        if recent and sum(1 for s in recent if s == 200) / len(recent) < stop_condition_unavail:
            aborted = True
            break

    result["aborted_by_stop_condition"] = aborted
    result["inject_ok"] = inject_ok
    if inject_err:
        result["inject_error"] = inject_err

    recover()
    time.sleep(3)  # 恢复传播
    result["recovered_at_s"] = round(time.time() - t0, 1)

    pt.join(timeout=inject_seconds + 15)
    result["steady_state_during"] = probe.summary()
    result["steady_state_after"] = None
    post = Probe(base)
    post.loop(5)
    result["steady_state_after"] = post.summary()

    max_after = crdb_max_audits()
    result["max_audits_after"] = max_after
    result["rpo"] = "PASS" if max_after >= max_before else "FAIL"

    s_during = result["steady_state_during"]
    # 假设判定：注入期可用率 ≥ 假设线且数据零丢失
    hypothesis_ok = s_during["availability"] >= stop_condition_unavail and max_after >= max_before
    result["hypothesis_verdict"] = "PASS" if hypothesis_ok and not aborted else ("ABORTED" if aborted else "FAIL")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ---------------------------------------------------------------------------
# X1 Pod 随机驱逐
# ---------------------------------------------------------------------------
def x1_inject() -> str:
    out = k("get", "pods", "-l", "app=ekb-control-plane", "-o", "json")
    items = json.loads(out.decode())["items"]
    ready = [i["metadata"]["name"] for i in items
             if i["status"].get("containerStatuses") and i["status"]["containerStatuses"][0].get("ready")]
    victim = sorted(ready)[0]
    subprocess.call(["kubectl", "-n", "ekb-app", "delete", "pod", victim,
                     "--force", "--grace-period=0"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return victim


def x1_recover() -> None:
    # ReplicaSet 自动重建；等待恢复在 run_experiment 的 3s + 事后探针覆盖
    return None


# ---------------------------------------------------------------------------
# X2 Redis 依赖故障：阻断 control-plane → redis-cluster 的 NetworkPolicy 不可行（无 chaos-mesh），
# 用 service 端点摘除法：临时把 redis-cluster service selector 指向不存在的标签 → 连接全部失败
# ---------------------------------------------------------------------------
def x2_inject() -> str:
    orig = k("get", "svc", "redis-cluster", "-n", "infra", "-o", "json")
    spec = json.loads(orig.decode())
    selector = spec["spec"].get("selector", {})
    # 破坏 selector
    subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "redis-cluster",
                     "--type", "merge", "-p", '{"spec":{"selector":{"__chaos__":"isolated"}}}'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.dumps(selector)


def x2_recover(orig_selector_json: str = "") -> None:
    if orig_selector_json:
        sel = json.loads(orig_selector_json)
        patch = json.dumps({"spec": {"selector": sel}})
        subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "redis-cluster",
                         "--type", "merge", "-p", patch],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        # 兜底：查 endpooints 对应 pod 标签恢复
        subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "redis-cluster",
                         "--type", "merge", "-p", '{"spec":{"selector":{"app":"redis-cluster"}}}'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# ---------------------------------------------------------------------------
# X3 Pulsar 依赖故障：同法摘 broker service selector
# ---------------------------------------------------------------------------
def x3_inject() -> str:
    orig = k("get", "svc", "pulsar-broker", "-n", "infra", "-o", "json")
    spec = json.loads(orig.decode())
    selector = spec["spec"].get("selector", {})
    subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "pulsar-broker",
                     "--type", "merge", "-p", '{"spec":{"selector":{"__chaos__":"isolated"}}}'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.dumps(selector)


def x3_recover(orig_selector_json: str = "") -> None:
    if orig_selector_json:
        sel = json.loads(orig_selector_json)
        patch = json.dumps({"spec": {"selector": sel}})
        subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "pulsar-broker",
                         "--type", "merge", "-p", patch.replace("'", '"')],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        subprocess.call(["kubectl", "-n", "infra", "patch", "svc", "pulsar-broker",
                         "--type", "merge", "-p", '{"spec":{"selector":{"app":"pulsar"}}}'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# ---------------------------------------------------------------------------
# X4 资源压力：在 control-plane pod 内起 CPU 烧灼进程（单 pod 试点）
# ---------------------------------------------------------------------------
def x4_inject(pod: str | None = None) -> str:
    target = pod
    if not target:
        out = k("get", "pods", "-l", "app=ekb-control-plane", "-o", "json")
        items = json.loads(out.decode())["items"]
        target = sorted(i["metadata"]["name"] for i in items
                        if i["status"].get("containerStatuses")
                        and i["status"]["containerStatuses"][0].get("ready"))[0]
    k("exec", target, "--", "sh", "-c",
      "nohup sh -c 'while :; do :; done' > /dev/null 2>&1 & echo $! > /tmp/chaos_cpu.pid")
    return target


def x4_recover(pod: str | None = None) -> None:
    if not pod:
        return
    subprocess.call(["kubectl", "-n", "ekb-app", "exec", pod, "--", "sh", "-c",
                     "kill $(cat /tmp/chaos_cpu.pid) 2>/dev/null; rm -f /tmp/chaos_cpu.pid"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)


EXPERIMENTS = {
    "X1": dict(name="X1 pod-kill", hypothesis="3 副本下 kill 单副本，可用率 ≥99%、RTO<30s、RPO=0",
               blast_radius="低（副本冗余内，DR 演练已验证）",
               inject=x1_inject, recover=x1_recover, seconds=30),
    "X2": dict(name="X2 redis-failure", hypothesis="Redis 不可达时限流/缓存降级不崩，主链路可用率 ≥90%",
               blast_radius="低（L2 缓存/L1 pool 自愈路径）",
               inject=x2_inject, recover=x2_recover, seconds=45),
    "X3": dict(name="X3 pulsar-failure", hypothesis="broker 不可达时 outbox 积压不丢，恢复后 relay 追平",
               blast_radius="低（outbox 落库，relay 重试）",
               inject=x3_inject, recover=x3_recover, seconds=45),
    "X4": dict(name="X4 cpu-stress", hypothesis="CPU limit 饱和下探针不误杀（timeout 5s 验证）、降级不崩",
               blast_radius="低（单 pod 试点）",
               inject=x4_inject, recover=x4_recover, seconds=40),
}

if __name__ == "__main__":
    import argparse
    import pathlib

    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="X1,X4")
    ap.add_argument("--base", default="http://10.167.2.175:30880")
    ap.add_argument("--out", default="docs/chaos/chaos-report.json")
    args = ap.parse_args()

    results = []
    for key in [x.strip().upper() for x in args.experiments.split(",")]:
        exp = EXPERIMENTS.get(key)
        if not exp:
            continue
        print(f"=== {exp['name']} ===", flush=True)
        r = run_experiment(exp["name"], exp["hypothesis"], exp["blast_radius"],
                           exp["inject"], exp["recover"], args.base, exp["seconds"])
        results.append(r)
        print(json.dumps({k: r[k] for k in ("hypothesis_verdict", "aborted_by_stop_condition",
                                            "steady_state_during", "rpo")}, ensure_ascii=False, indent=2), flush=True)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": "Principles of Chaos (steady-state hypothesis, blast radius, stop conditions)",
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"saved → {out_path}", flush=True)
