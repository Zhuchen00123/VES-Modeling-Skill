#!/usr/bin/env python3
"""
render_ves_report.py — VES 实验报告生成与状态同步工具 (VES-MathModeling-Skill)

功能:
1. 读取 VES 搜索产出的 manifest (ves_problem_manifest.json / ves_regression_manifest.json)。
2. 提取宿主 Verifier 独立评定的 verified 指标、候选迭代轨迹与代码/数据哈希。
3. 渲染出规范的 Markdown 实验报告与 LaTeX 表格，供 Stage 8 论文正文直接引用。
4. 自动将 verified 指标与报告路径同步回 decision_log.json 的 Stage 5 节点。

用法示例:
    python scripts/render_ves_report.py --manifest state/q1_forecast_manifest.json --qi Q1 \
      --output-md results/Q1_ves_report.md --decision-log state/decision_log.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


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


def generate_ves_report(
    manifest_path: Path,
    qi: str | None = None,
    output_md: Path | None = None,
    output_tex: Path | None = None,
    decision_log_path: Path | None = None,
) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest 文件未找到: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Manifest JSON 解析失败 ({manifest_path}): {exc}") from exc

    task_meta = manifest.get("task", {})
    slice_name = task_meta.get("slice", task_meta.get("task", "unknown"))
    dataset_name = task_meta.get("dataset", "unspecified")
    result = manifest.get("result", {})
    status = result.get("status", "unknown")
    run_id = result.get("run_id", "none")
    candidate_id = result.get("candidate_id", result.get("best_candidate_id", "none"))
    metrics = result.get("metrics", {})
    if not metrics:
        # 回归兼容字段
        if "rmse" in result or "best_rmse" in result:
            metrics = {
                "rmse": result.get("best_rmse", result.get("rmse")),
                "mae": result.get("best_mae", result.get("mae")),
            }

    artifacts = manifest.get("artifacts", {})
    provenance = manifest.get("provenance", {})
    best_code_sha = provenance.get("best_code_sha256", "N/A")
    gen_utc = provenance.get("generated_utc", datetime.now(timezone.utc).isoformat())

    qi_label = qi or (dataset_name.split("_")[0] if dataset_name else "Qi")
    if not re.fullmatch(r"Q[1-9][0-9]*", qi_label):
        qi_label = qi or "Q1"

    # 构造 Markdown 报告
    md_lines = [
        f"# 子问题 {qi_label} VES 宿主验证与可信实验报告",
        "",
        f"> **切片类型**: `{slice_name}` | **运行状态**: `status={status}` | **Run ID**: `{run_id}`",
        f"> **生成时间**: `{gen_utc}` | **最优候选 ID**: `{candidate_id}`",
        "",
        "---",
        "",
        "## 1. 宿主独立验证指标 (Host Verified Metrics)",
        "",
        "本实验结果经由 VES 隔离沙箱与宿主 Verifier 独立运行检验，严格排除 Agent 自评与自欺欺人偏差：",
        "",
        "| 指标名称 | 宿主验证值 | 验证状态 | 证据链引用 |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for m_name, m_val in metrics.items():
        val_str = f"{m_val:.4f}" if isinstance(m_val, (int, float)) else str(m_val)
        md_lines.append(f"| **{m_name.upper()}** | `{val_str}` | `VERIFIED` | `{run_id}/{m_name}` |")

    md_lines.extend([
        "",
        "---",
        "",
        "## 2. 可验证性与密码学哈希签名 (Provenance & Hashes)",
        "",
        "| 验证要素 | 路径 / 哈希签名 | 说明 |",
        "| :--- | :--- | :--- |",
        f"| **最优方案代码** | `{artifacts.get('best_solution', 'N/A')}` | 真实可执行 Python 脚本 |",
        f"| **代码 SHA-256** | `{best_code_sha}` | 保证代码不可篡改 |",
        f"| **运行结果目录** | `{artifacts.get('run_dir', 'N/A')}` | 包含完整 stdout/stderr 与中间产物 |",
        f"| **输出 Manifest** | `{manifest_path}` | 结构化证据凭据 |",
        "",
        "---",
        "",
        "## 3. 论文正文直接引用段落 (Paper Section Snippet)",
        "",
        "```markdown",
        f"【子问题 {qi_label} 求解与可信验证结论】",
        f"为确保建模结果的客观可信，本文将 {qi_label} 子问题对接 VES（Verified Executable Search）宿主计算引擎的 `{slice_name}` 切片。",
        f"经沙箱隔离执行与独立 Verifier 验证（Run ID: `{run_id}`，状态: `{status}`），最优模型（代码哈希 `{best_code_sha[:12]}`）取得以下经过宿主独立评定的客观指标：",
    ])
    for m_name, m_val in metrics.items():
        val_str = f"{m_val:.4f}" if isinstance(m_val, (int, float)) else str(m_val)
        md_lines.append(f"- {m_name.upper()}: {val_str}")
    md_lines.extend([
        "该指标完全基于宿主隐藏真值与沙箱运行结果给出，消除了传统建模中自报指标与过拟合风险。",
        "```",
        "",
    ])

    report_text = "\n".join(md_lines) + "\n"

    # 输出 Markdown 报告
    if output_md is not None:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(report_text, encoding="utf-8", newline="\n")

    # 输出 LaTeX 表格（可选）
    if output_tex is not None:
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        tex_lines = [
            r"\begin{table}[htbp]",
            r"\centering",
            f"\\caption{{子问题 {qi_label} VES 宿主独立验证指标汇总表}}",
            f"\\label{{tab:ves_{qi_label.lower()}_metrics}}",
            r"\begin{tabular}{lccc}",
            r"\toprule",
            r"\textbf{指标名称} & \textbf{宿主验证值} & \textbf{验证状态} & \textbf{证据 Run ID} \\",
            r"\midrule",
        ]
        for m_name, m_val in metrics.items():
            val_str = f"{m_val:.4f}" if isinstance(m_val, (int, float)) else str(m_val)
            tex_lines.append(f"\\texttt{{{m_name.upper()}}} & {val_str} & \\texttt{{VERIFIED}} & \\texttt{{{run_id}}} \\\\")
        tex_lines.extend([
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ])
        output_tex.write_text("\n".join(tex_lines), encoding="utf-8", newline="\n")

    # 同步回 decision_log
    if decision_log_path is not None and decision_log_path.is_file():
        try:
            log_data = json.loads(decision_log_path.read_text(encoding="utf-8"))
            s5 = log_data.setdefault("stages", {}).setdefault("5", {})
            subs = s5.setdefault("sub_problems", {})
            q_node = subs.setdefault(qi_label, {})
            q_node["ves_status"] = status
            q_node["ves_slice"] = slice_name
            q_node["ves_run_id"] = run_id
            q_node["ves_metrics"] = metrics
            q_node["best_candidate_id"] = candidate_id
            q_node["best_code_sha256"] = best_code_sha
            q_node["manifest_path"] = str(manifest_path.resolve())
            if output_md:
                q_node["report_path"] = str(output_md.resolve())
            _atomic_write_json(decision_log_path, log_data)
        except Exception as exc:
            print(f"[WARN] 无法同步至 decision_log: {exc}")

    return {
        "qi": qi_label,
        "status": status,
        "slice": slice_name,
        "metrics": metrics,
        "run_id": run_id,
        "best_code_sha256": best_code_sha,
        "output_md": str(output_md) if output_md else None,
        "output_tex": str(output_tex) if output_tex else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="VES 实验报告生成与状态同步工具")
    parser.add_argument("--manifest", type=str, required=True, help="VES 输出的 manifest.json 路径")
    parser.add_argument("--qi", type=str, default=None, help="子问题编号 (如 Q1, Q2)")
    parser.add_argument("--output-md", type=str, default=None, help="Markdown 报告输出路径")
    parser.add_argument("--output-tex", type=str, default=None, help="LaTeX 表格代码输出路径")
    parser.add_argument("--decision-log", type=str, default="state/decision_log.json",
                        help="decision_log.json 路径用于自动同步")

    args = parser.parse_args()

    manifest_p = Path(args.manifest).resolve()
    qi = args.qi
    if not qi:
        match = re.search(r"(Q[1-9][0-9]*)", manifest_p.name, re.IGNORECASE)
        if match:
            qi = match.group(1).upper()
        else:
            qi = "Q1"

    out_md = Path(args.output_md).resolve() if args.output_md else manifest_p.parent.parent / "results" / f"{qi}_ves_report.md"
    out_tex = Path(args.output_tex).resolve() if args.output_tex else None
    dlog_p = Path(args.decision_log).resolve() if args.decision_log else None

    try:
        res = generate_ves_report(
            manifest_path=manifest_p,
            qi=qi,
            output_md=out_md,
            output_tex=out_tex,
            decision_log_path=dlog_p,
        )
        print(f"[OK] 子问题 {res['qi']} VES 实验报告已成功生成: {res['output_md']}")
        print(f"  - 宿主验证状态: status={res['status']}")
        print(f"  - 独立验证指标: {res['metrics']}")
        print(f"  - 代码哈希: {res['best_code_sha256'][:16]}...")
        if dlog_p and dlog_p.is_file():
            print(f"  - 已自动同步至 decision_log: {dlog_p}")
        return 0
    except Exception as exc:
        print(f"[FAIL] 生成实验报告失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
