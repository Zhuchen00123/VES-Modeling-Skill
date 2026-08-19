#!/usr/bin/env python3
"""
ves_scaffold.py — VES 子问题注册与脚手架工具 (VES-MathModeling-Skill)

功能:
1. 在 Stage 2/3 自动将子问题注册到 decision_log.json 中的 VES 契约字段。
2. 校验所选切片是否在 25 个已支持切片目录中。
3. 可选自动创建数据目录脚手架 (<cwd>/data/<Qi>_public, <cwd>/data/<Qi>_host) 并写入数据契约说明。
4. 自动生成一键运行的 python run_ves_problem.py / run_ves_regression.py 执行命令建议。

用法示例:
    python scripts/ves_scaffold.py --register --qi Q1 --slice forecasting \
      --description "重点物料周需求量预测" --create-dirs --set target_column=demand time_column=week

    python scripts/ves_scaffold.py --register --qi Q2 --slice optimization \
      --description "服务水平>=85%下的滚动生产排产策略优化" --create-dirs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_SKILL_ROOT = Path(__file__).resolve().parent.parent

# 25 个支持的切片清单
SUPPORTED_SLICES = {
    "regression": {"needs_host": True, "required_public": ("train.csv", "test_features.csv"), "host_files": ("hidden_test_labels.csv",), "desc": "连续目标回归预测"},
    "forecasting": {"needs_host": True, "required_public": ("train.csv", "test_features.csv"), "host_files": ("hidden_test_labels.csv",), "desc": "时间序列多步预测"},
    "classification": {"needs_host": True, "required_public": ("train.csv", "test_features.csv"), "host_files": ("hidden_test_labels.csv",), "desc": "离散类别与多分类判定"},
    "optimization": {"needs_host": False, "required_public": (), "host_files": (), "desc": "单目标约束规划与参数搜索"},
    "multiobjective": {"needs_host": False, "required_public": (), "host_files": (), "desc": "多目标 Pareto 前沿搜索与权衡"},
    "ode": {"needs_host": True, "required_public": ("train.csv", "test_features.csv"), "host_files": ("hidden_test_values.csv",), "desc": "常微分方程与动力系统拟合"},
    "clustering": {"needs_host": True, "required_public": (), "host_files": ("hidden_test_labels.csv",), "desc": "无监督样本聚类分析"},
    "anomaly": {"needs_host": True, "required_public": (), "host_files": ("hidden_test_labels.csv",), "desc": "离群点与异常检测"},
    "queueing": {"needs_host": False, "required_public": (), "host_files": (), "desc": "排队系统性能分析与仿真优化"},
    "markov": {"needs_host": False, "required_public": (), "host_files": (), "desc": "马尔可夫链状态转移与平稳分布"},
    "game": {"needs_host": False, "required_public": (), "host_files": (), "desc": "博弈论纳什均衡与策略搜索"},
    "graph": {"needs_host": False, "required_public": (), "host_files": (), "desc": "网络图论与路径/流优化"},
    "montecarlo": {"needs_host": False, "required_public": (), "host_files": (), "desc": "蒙特卡洛随机模拟与风险评估"},
    "probabilistic": {"needs_host": True, "required_public": ("problem.json",), "host_files": ("hidden_parameters.json",), "desc": "贝叶斯概率推断与参数后验"},
    "association": {"needs_host": True, "required_public": (), "host_files": ("hidden_test_labels.csv",), "desc": "关联规则与频繁项集挖掘"},
    "binpacking": {"needs_host": False, "required_public": (), "host_files": (), "desc": "装箱与切割下料优化"},
    "cellular": {"needs_host": False, "required_public": (), "host_files": (), "desc": "元胞自动机空间演化模拟"},
    "changepoint": {"needs_host": False, "required_public": (), "host_files": (), "desc": "时序变点与结构突变检测"},
    "lqr": {"needs_host": False, "required_public": (), "host_files": (), "desc": "线性二次型最优控制"},
    "networksir": {"needs_host": False, "required_public": (), "host_files": (), "desc": "复杂网络传染病动力学传播"},
    "recommendation": {"needs_host": True, "required_public": (), "host_files": ("hidden_test_ratings.csv",), "desc": "协同过滤与推荐系统"},
    "seqpattern": {"needs_host": False, "required_public": (), "host_files": (), "desc": "序列模式挖掘与事件预测"},
    "sir": {"needs_host": False, "required_public": (), "host_files": (), "desc": "经典 SIR 传染病房室模型"},
    "survival": {"needs_host": False, "required_public": (), "host_files": (), "desc": "生存分析与风险率模型"},
}


def _atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temp_path, path.stat().st_mode)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def register_subproblem(
    qi: str,
    slice_name: str,
    decision_log_path: Path,
    description: str = "",
    public_dir: str = "",
    host_dir: str | None = None,
    workspace: str = "",
    output_manifest: str = "",
    generator: str = "llm",
    extra_sets: dict[str, str] | None = None,
    create_dirs: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"Q[1-9][0-9]*", qi):
        raise ValueError(f"qi 格式必须形如 Q1, Q2，实际输入: {qi}")
    if slice_name not in SUPPORTED_SLICES:
        raise ValueError(
            f"未知 slice {slice_name!r}。可用切片: {', '.join(sorted(SUPPORTED_SLICES.keys()))}"
        )

    cwd = cwd or Path.cwd()
    meta = SUPPORTED_SLICES[slice_name]
    public_p = Path(public_dir) if public_dir else cwd / "data" / f"{qi.lower()}_public"
    needs_host = meta["needs_host"]
    host_p = (Path(host_dir) if host_dir else cwd / "data" / f"{qi.lower()}_host") if needs_host else None
    ws_p = Path(workspace) if workspace else cwd / "ves_runs" / f"{qi.lower()}_{slice_name}"
    manifest_p = Path(output_manifest) if output_manifest else cwd / "state" / f"{qi.lower()}_manifest.json"

    # 生成脚手架目录
    if create_dirs:
        public_p.mkdir(parents=True, exist_ok=True)
        readme_pub = public_p / "README.md"
        if not readme_pub.exists():
            req_files = ", ".join(meta["required_public"]) if meta["required_public"] else "由具体问题定义"
            readme_pub.write_text(
                f"# {qi} Public Dataset Scaffolding\n\n- 切片: `{slice_name}` ({meta['desc']})\n- 建议文件: {req_files}\n",
                encoding="utf-8",
                newline="\n"
            )
        if host_p is not None:
            host_p.mkdir(parents=True, exist_ok=True)
            readme_host = host_p / "README.md"
            if not readme_host.exists():
                h_files = ", ".join(meta["host_files"]) if meta["host_files"] else "由具体问题定义"
                readme_host.write_text(
                    f"# {qi} Host Hidden Truth Scaffolding\n\n- 仅宿主 Verifier 可见\n- 建议文件: {h_files}\n",
                    encoding="utf-8",
                    newline="\n"
                )

    # 构造运行指令
    adapter_script = (
        "scripts/run_ves_regression.py" if slice_name == "regression"
        else f"scripts/run_ves_problem.py --slice {slice_name}"
    )
    cmd_parts = [
        f"python skills/ves-mathmodel-skill/{adapter_script}",
        f"--public-dir {public_p}",
    ]
    if host_p is not None:
        cmd_parts.append(f"--host-dir {host_p}")
    cmd_parts.extend([
        f"--workspace {ws_p}",
        f"--output {manifest_p}",
        f"--generator {generator}",
    ])
    if extra_sets:
        for k, v in extra_sets.items():
            cmd_parts.append(f"--set {k}={v}")
    command_hint = " \\\n  ".join(cmd_parts)

    # 读写 decision_log
    log_data: dict[str, Any] = {}
    if decision_log_path.is_file():
        try:
            log_data = json.loads(decision_log_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    stages = log_data.setdefault("stages", {})
    s2 = stages.setdefault("2", {})
    s2_subs = s2.setdefault("sub_problems", {})
    s3 = stages.setdefault("3", {})
    s3_subs = s3.setdefault("selected_per_subproblem", {})
    s5 = stages.setdefault("5", {})
    s5_subs = s5.setdefault("sub_problems", {})

    record_s2 = {
        "qi": qi,
        "description": description or meta["desc"],
        "ves_eligibility": True,
        "ves_slice": slice_name,
        "ves_reason": f"对接 VES {slice_name} 切片 ({meta['desc']}) 进行独立可执行验证",
        "ves_data_contract": {
            "public_dir": str(public_p),
            "host_dir": str(host_p) if host_p else None,
            "required_public": list(meta["required_public"]),
            "host_files": list(meta["host_files"]),
            "extra_params": extra_sets or {},
        },
        "command_hint": command_hint,
    }
    s2_subs[qi] = record_s2

    s3_subs[qi] = {
        "model_name": f"VES-{slice_name.capitalize()}-Search",
        "execution_backend": "ves",
        "verifier_compatible": True,
        "out_of_ves_scope": False,
        "reason": f"采用 VES {slice_name} 进行候选生成与宿主独立验证",
    }

    s5_subs.setdefault(qi, {})["ves_eligibility"] = True
    s5_subs[qi]["ves_slice"] = slice_name
    s5_subs[qi]["manifest_path"] = str(manifest_p)

    _atomic_write_json(decision_log_path, log_data)
    return {
        "qi": qi,
        "slice": slice_name,
        "public_dir": str(public_p),
        "host_dir": str(host_p) if host_p else None,
        "workspace": str(ws_p),
        "manifest_path": str(manifest_p),
        "command_hint": command_hint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="VES 子问题注册与脚手架工具")
    parser.add_argument("--register", action="store_true", help="注册子问题到 decision_log")
    parser.add_argument("--qi", type=str, required=True, help="子问题编号 (如 Q1, Q2)")
    parser.add_argument("--slice", type=str, required=True, choices=sorted(SUPPORTED_SLICES.keys()),
                        help="VES 切片名称 (25 类之一)")
    parser.add_argument("--description", type=str, default="", help="子问题自然语言描述")
    parser.add_argument("--decision-log", type=str, default="state/decision_log.json",
                        help="decision_log.json 路径 (默认 state/decision_log.json)")
    parser.add_argument("--public-dir", type=str, default="", help="公开数据目录 (默认 data/<qi>_public)")
    parser.add_argument("--host-dir", type=str, default=None, help="宿主真值目录 (默认 data/<qi>_host)")
    parser.add_argument("--workspace", type=str, default="", help="运行工作空间 (默认 ves_runs/<qi>_<slice>)")
    parser.add_argument("--output", type=str, default="", dest="output_manifest",
                        help="输出 manifest 路径 (默认 state/<qi>_manifest.json)")
    parser.add_argument("--generator", type=str, choices=["llm", "mock"], default="llm",
                        help="生成器类型: llm (真实比赛默认) 或 mock (测试用)")
    parser.add_argument("--create-dirs", action="store_true", help="自动创建数据脚手架目录与契约说明")
    parser.add_argument("--set", action="append", default=[],
                        help="附加参数 key=value (可多次指定)")

    args = parser.parse_args()

    extra_sets = {}
    for item in args.set:
        if "=" in item:
            k, v = item.split("=", 1)
            extra_sets[k.strip()] = v.strip()

    try:
        res = register_subproblem(
            qi=args.qi,
            slice_name=args.slice,
            decision_log_path=Path(args.decision_log).resolve(),
            description=args.description,
            public_dir=args.public_dir,
            host_dir=args.host_dir,
            workspace=args.workspace,
            output_manifest=args.output_manifest,
            generator=args.generator,
            extra_sets=extra_sets,
            create_dirs=args.create_dirs,
        )
        print(f"[OK] 子问题 {res['qi']} 已成功注册到 VES 切片 '{res['slice']}'")
        print(f"  - 公开数据路径: {res['public_dir']}")
        if res["host_dir"]:
            print(f"  - 宿主真值路径: {res['host_dir']}")
        print(f"  - 输出 Manifest: {res['manifest_path']}")
        print(f"\n【建议执行命令】\n{res['command_hint']}\n")
        return 0
    except Exception as exc:
        print(f"[FAIL] 注册失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
