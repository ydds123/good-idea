#!/usr/bin/env python3
"""Evaluate trigger overlap and scenario routing across all Good idea Skills."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = PROJECT_ROOT / ".agents" / "skills"
DEFAULT_CASES = PROJECT_ROOT / "tests" / "fixtures" / "skill-routing-cases.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "skill-routing"
NO_ROUTE = "no_route"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return payload


def extract_description(skill_file: Path) -> str:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"Skill 缺少 Frontmatter：{skill_file}")
    frontmatter = text.split("---", 2)[1]
    for line in frontmatter.splitlines():
        if not line.strip().startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not value:
            break
        return value
    raise ValueError(f"Skill 缺少 description：{skill_file}")


def discover_descriptions(skills_root: Path) -> dict[str, str]:
    if not skills_root.is_dir():
        raise ValueError(f"Skill 目录不存在：{skills_root}")
    descriptions: dict[str, str] = {}
    for skill_dir in sorted(skills_root.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            descriptions[skill_dir.name] = extract_description(skill_file)
    if not descriptions:
        raise ValueError(f"没有发现项目 Skill：{skills_root}")
    return descriptions


def description_fingerprint(descriptions: dict[str, str]) -> str:
    canonical = json.dumps(descriptions, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalized_description(text: str) -> str:
    text = text.lower().replace("good idea", "")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def pair_key(names: list[str] | tuple[str, str]) -> tuple[str, str]:
    if len(names) != 2:
        raise ValueError(f"Skill 重叠声明必须恰好包含两个名称：{names}")
    return tuple(sorted(names))


def validate_contract(
    contract: dict[str, Any], descriptions: dict[str, str]
) -> list[str]:
    errors: list[str] = []
    expected_skills = contract.get("skills")
    if not isinstance(expected_skills, list) or not all(
        isinstance(name, str) for name in expected_skills
    ):
        return ["skills 必须是 Skill 名称数组"]
    if set(expected_skills) != set(descriptions):
        errors.append(
            "Skill 集合不一致："
            f"契约={sorted(expected_skills)}，实际={sorted(descriptions)}"
        )
    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        return [*errors, "cases 必须是非空数组"]
    route_names = set(expected_skills) | {NO_ROUTE}
    ids: set[str] = set()
    expected_counts: Counter[str] = Counter()
    for index, case in enumerate(cases):
        label = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{label} 必须是对象")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{label}.id 必须是非空字符串")
        elif case_id in ids:
            errors.append(f"重复 case id：{case_id}")
        else:
            ids.add(case_id)
        if not isinstance(case.get("text"), str) or not case["text"].strip():
            errors.append(f"{label}.text 必须是非空字符串")
        primary = case.get("expected_primary")
        if primary not in route_names:
            errors.append(f"{label}.expected_primary 非法：{primary}")
        elif primary != NO_ROUTE:
            expected_counts[primary] += 1
        allowed = case.get("allowed_supporting", [])
        required = case.get("required_supporting", [])
        if not isinstance(allowed, list) or not set(allowed).issubset(route_names - {NO_ROUTE}):
            errors.append(f"{label}.allowed_supporting 非法")
            allowed = []
        if not isinstance(required, list) or not set(required).issubset(set(allowed)):
            errors.append(f"{label}.required_supporting 必须是 allowed_supporting 子集")
        if primary in allowed:
            errors.append(f"{label} 的主 Skill 不能同时列为 supporting")
        if not isinstance(case.get("expected_conflict"), bool):
            errors.append(f"{label}.expected_conflict 必须是布尔值")
    minimum = int(contract.get("minimum_primary_cases_per_skill", 1))
    for skill in expected_skills:
        if expected_counts[skill] < minimum:
            errors.append(
                f"{skill} 只有 {expected_counts[skill]} 个主路由案例，至少需要 {minimum} 个"
            )
    try:
        allowed_pairs = {
            pair_key(item["skills"])
            for item in contract.get("allowed_overlap_pairs", [])
        }
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
        allowed_pairs = set()
    for pair in allowed_pairs:
        if not set(pair).issubset(set(expected_skills)):
            errors.append(f"重叠声明引用未知 Skill：{pair}")
    known_case_ids = ids
    for bucket in ("semantic_risk_hypotheses", "recall_risk_hypotheses"):
        for index, item in enumerate(contract.get(bucket, [])):
            if not isinstance(item, dict):
                errors.append(f"{bucket}[{index}] 必须是对象")
                continue
            referenced_skills = item.get("skills", [item.get("skill")])
            if not set(referenced_skills).issubset(set(expected_skills)):
                errors.append(f"{bucket}[{index}] 引用未知 Skill")
            referenced_cases = item.get("case_ids", [])
            if not set(referenced_cases).issubset(known_case_ids):
                errors.append(f"{bucket}[{index}] 引用未知 case id")
    return errors


def scan_static_overlap(
    descriptions: dict[str, str], contract: dict[str, Any]
) -> dict[str, Any]:
    threshold = float(contract.get("similarity_warning_threshold", 0.55))
    allowed_specs = {
        pair_key(item["skills"]): item
        for item in contract.get("allowed_overlap_pairs", [])
    }
    pairs: list[dict[str, Any]] = []
    unapproved: list[dict[str, Any]] = []
    declared: list[dict[str, Any]] = []
    names = sorted(descriptions)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            ratio = difflib.SequenceMatcher(
                None,
                normalized_description(descriptions[left]),
                normalized_description(descriptions[right]),
            ).ratio()
            key = pair_key((left, right))
            record = {
                "skills": list(key),
                "similarity": round(ratio, 3),
                "above_threshold": ratio >= threshold,
                "declared_overlap": key in allowed_specs,
            }
            if key in allowed_specs:
                record["overlap_kind"] = allowed_specs[key].get("kind", "declared")
                record["reason"] = allowed_specs[key].get("reason", "")
            pairs.append(record)
            if ratio >= threshold:
                if key in allowed_specs:
                    declared.append(record)
                else:
                    unapproved.append(record)
    duplicate_groups: list[list[str]] = []
    by_description: dict[str, list[str]] = {}
    for name, description in descriptions.items():
        by_description.setdefault(normalized_description(description), []).append(name)
    for group in by_description.values():
        if len(group) > 1:
            duplicate_groups.append(sorted(group))
    return {
        "ok": not unapproved and not duplicate_groups,
        "threshold": threshold,
        "pair_scores": sorted(
            pairs, key=lambda item: item["similarity"], reverse=True
        ),
        "declared_high_overlaps": declared,
        "unapproved_high_overlaps": unapproved,
        "duplicate_description_groups": duplicate_groups,
    }


def routing_output_schema(route_names: list[str]) -> dict[str, Any]:
    allowed = [*route_names, NO_ROUTE]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "case_id": {"type": "string"},
                        "primary_skill": {"type": "string", "enum": allowed},
                        "supporting_skills": {
                            "type": "array",
                            "items": {"type": "string", "enum": route_names},
                        },
                        "conflict": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "case_id",
                        "primary_skill",
                        "supporting_skills",
                        "conflict",
                        "reason",
                    ],
                },
            }
        },
        "required": ["results"],
    }


def model_prompt(
    descriptions: dict[str, str], cases: list[dict[str, Any]]
) -> str:
    public_cases = [{"case_id": case["id"], "text": case["text"]} for case in cases]
    payload = {
        "skills": descriptions,
        "cases": public_cases,
    }
    return (
        "你是 Good idea 项目 Skill 路由评测器。只做路由判断，不执行用户请求，"
        "不调用工具，也不要修改文件。逐条独立判断，不能让相邻案例影响当前案例。\n\n"
        "规则：\n"
        "1. primary_skill 是请求当前第一阶段的唯一所有者；没有足够信息或不属于七个 Skill 时用 no_route。\n"
        "2. supporting_skills 只放用户明确要求、且必须在后续不同阶段交接的 Skill；"
        "某 Skill 在主 Skill 内部被引用但无需独立接管时不要列出。\n"
        "3. 多个 Skill 出现在不同阶段不是冲突；两个 Skill 同时声称拥有同一阶段且无法区分时 conflict=true。\n"
        "4. 不要根据 Skill 名称猜测，必须依据 description 中的对象、动作、排除条件和请求上下文。\n"
        "5. 每个 case_id 恰好返回一次。\n\n"
        "评测输入：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def parse_runner_metadata(stderr: str, codex_version: str) -> dict[str, Any]:
    model_match = re.search(r"(?m)^model:\s*(.+)$", stderr)
    token_match = re.search(r"tokens used\s*\n([\d,]+)", stderr)
    return {
        "kind": "model_backed_batch_classifier",
        "codex_version": codex_version.strip(),
        "model": model_match.group(1).strip() if model_match else "unknown",
        "tokens_used": int(token_match.group(1).replace(",", "")) if token_match else None,
        "note": (
            "一次模型调用中逐条分类，验证当前 description 与项目路由规则；"
            "它不是 Codex 原生 Skill 激活遥测，也不等同于逐案例独立会话。"
        ),
    }


def run_codex_classifier(
    project_root: Path,
    descriptions: dict[str, str],
    cases: list[dict[str, Any]],
    *,
    codex_bin: str,
    model: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which(codex_bin) if "/" not in codex_bin else codex_bin
    if not executable or not Path(executable).exists():
        raise RuntimeError(f"找不到 Codex CLI：{codex_bin}")
    try:
        version = subprocess.run(
            [str(executable), "--version"],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        ).stdout.strip()
    except subprocess.SubprocessError as error:
        raise RuntimeError(f"无法读取 Codex 版本：{error}") from error
    with tempfile.TemporaryDirectory(prefix="goodidea-skill-routing-") as temporary:
        temporary_root = Path(temporary)
        schema_path = temporary_root / "schema.json"
        output_path = temporary_root / "result.json"
        schema_path.write_text(
            json.dumps(
                routing_output_schema(sorted(descriptions)),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        command = [
            str(executable),
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "-s",
            "read-only",
            "-C",
            str(project_root),
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")
        try:
            completed = subprocess.run(
                command,
                cwd=project_root,
                input=model_prompt(descriptions, cases),
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Codex 路由评测超过 {timeout_seconds} 秒"
            ) from error
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip()[-4000:]
            raise RuntimeError(
                f"Codex 路由评测失败，退出码 {completed.returncode}：\n{diagnostic}"
            )
        raw = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
        try:
            predictions = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Codex 未返回合法 JSON：{raw[-2000:]}") from error
        return predictions, parse_runner_metadata(completed.stderr, version)


def evaluate_predictions(
    cases: list[dict[str, Any]],
    predictions: dict[str, Any],
    route_names: set[str],
) -> dict[str, Any]:
    raw_results = predictions.get("results")
    if not isinstance(raw_results, list):
        return {
            "ok": False,
            "summary": {"total": len(cases), "passed": 0, "failed": len(cases)},
            "errors": ["模型结果缺少 results 数组"],
            "cases": [],
        }
    errors: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in raw_results:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            errors.append("模型结果包含缺少 case_id 的记录")
            continue
        if item["case_id"] in by_id:
            errors.append(f"模型重复返回 case_id：{item['case_id']}")
            continue
        by_id[item["case_id"]] = item
    case_ids = {case["id"] for case in cases}
    for unexpected in sorted(set(by_id) - case_ids):
        errors.append(f"模型返回未知 case_id：{unexpected}")
    evaluated: list[dict[str, Any]] = []
    for case in cases:
        prediction = by_id.get(case["id"])
        if prediction is None:
            evaluated.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "text": case["text"],
                    "expected_primary": case["expected_primary"],
                    "predicted_primary": None,
                    "passed": False,
                    "failures": ["模型没有返回该案例"],
                }
            )
            continue
        primary = prediction.get("primary_skill")
        supporting = prediction.get("supporting_skills")
        conflict = prediction.get("conflict")
        failures: list[str] = []
        if primary not in route_names | {NO_ROUTE}:
            failures.append(f"非法主路由：{primary}")
        if primary != case["expected_primary"]:
            failures.append(
                f"主路由期望 {case['expected_primary']}，实际 {primary}"
            )
        if not isinstance(supporting, list):
            failures.append("supporting_skills 不是数组")
            supporting = []
        if len(supporting) != len(set(supporting)):
            failures.append("supporting_skills 包含重复 Skill")
        invalid_supporting = set(supporting) - route_names
        if invalid_supporting:
            failures.append(f"非法 supporting：{sorted(invalid_supporting)}")
        unexpected_supporting = set(supporting) - set(case["allowed_supporting"])
        if unexpected_supporting:
            failures.append(f"不允许的 supporting：{sorted(unexpected_supporting)}")
        missing_supporting = set(case["required_supporting"]) - set(supporting)
        if missing_supporting:
            failures.append(f"缺少后续路由：{sorted(missing_supporting)}")
        if conflict is not case["expected_conflict"]:
            failures.append(
                f"conflict 期望 {case['expected_conflict']}，实际 {conflict}"
            )
        evaluated.append(
            {
                "id": case["id"],
                "family": case["family"],
                "text": case["text"],
                "expected_primary": case["expected_primary"],
                "predicted_primary": primary,
                "allowed_supporting": case["allowed_supporting"],
                "required_supporting": case["required_supporting"],
                "predicted_supporting": supporting,
                "expected_conflict": case["expected_conflict"],
                "predicted_conflict": conflict,
                "reason": prediction.get("reason", ""),
                "passed": not failures,
                "failures": failures,
            }
        )
    passed = sum(1 for item in evaluated if item["passed"])
    failures = [item for item in evaluated if not item["passed"]]
    per_route: dict[str, dict[str, int | float | None]] = {}
    for route in sorted(route_names | {NO_ROUTE}):
        matching = [item for item in evaluated if item["expected_primary"] == route]
        route_passed = sum(1 for item in matching if item["passed"])
        per_route[route] = {
            "total": len(matching),
            "passed": route_passed,
            "pass_rate": round(route_passed / len(matching), 3) if matching else None,
        }
    return {
        "ok": not errors and not failures,
        "summary": {
            "total": len(evaluated),
            "passed": passed,
            "failed": len(evaluated) - passed,
            "pass_rate": round(passed / len(evaluated), 3) if evaluated else None,
            "predicted_conflicts": sum(
                1 for item in evaluated if item.get("predicted_conflict") is True
            ),
        },
        "per_route": per_route,
        "errors": errors,
        "failures": failures,
        "cases": evaluated,
    }


def render_markdown(report: dict[str, Any]) -> str:
    static = report["static_overlap"]
    lines = [
        "# Good idea Skill 路由评测",
        "",
        f"- 状态：`{report['status']}`",
        f"- 证据类型：`{report['evidence_kind']}`",
        f"- Skill：`{report['skill_count']}`",
        f"- 场景案例：`{report['case_count']}`",
        f"- description 指纹：`{report['description_fingerprint']}`",
        "",
        "## 证据边界",
        "",
        "静态扫描只说明 description 文本是否高度重叠。模型批量评测会逐条分类真实中文请求，"
        "但不是 Codex 原生 Skill 激活遥测，也不等同于每个案例单独启动一次完整任务。",
        "多个 Skill 只在不同阶段顺序交接时属于正常协作；争夺同一阶段才算冲突。",
        "",
        "## 静态重叠",
        "",
        f"- 阈值：`{static['threshold']}`",
        f"- 未声明的高重叠：`{len(static['unapproved_high_overlaps'])}`",
        f"- 已声明的高重叠：`{len(static['declared_high_overlaps'])}`",
        "",
        "| Skill A | Skill B | 相似度 | 解释 |",
        "|---|---|---:|---|",
    ]
    for pair in static["pair_scores"][:7]:
        explanation = pair.get("overlap_kind", "")
        if pair.get("reason"):
            explanation = f"{explanation}：{pair['reason']}"
        lines.append(
            f"| `{pair['skills'][0]}` | `{pair['skills'][1]}` | "
            f"{pair['similarity']:.3f} | {explanation or '—'} |"
        )
    lines.extend(["", "## 重点覆盖的语义风险场景", ""])
    for item in report.get("semantic_risk_hypotheses", []):
        skills = " / ".join(f"`{name}`" for name in item["skills"])
        lines.append(
            f"- **{item['severity']} · {item['id']}** · {skills}：{item['hypothesis']}"
        )
    lines.extend(["", "## 重点覆盖的召回风险场景", ""])
    for item in report.get("recall_risk_hypotheses", []):
        lines.append(
            f"- `{item['skill']}`：description 可能没有充分覆盖“{item['missing_intent']}”。"
        )
    model = report.get("model_evaluation")
    if model:
        summary = model["summary"]
        lines.extend(
            [
                "",
                "## 模型路由结果",
                "",
                f"- 通过：`{summary['passed']}/{summary['total']}`",
                f"- 失败：`{summary['failed']}`",
                f"- 模型判断为冲突：`{summary['predicted_conflicts']}`",
                f"- 模型：`{report.get('runner', {}).get('model', 'unknown')}`",
                "",
                "| 路由 | 通过 | 总数 | 通过率 |",
                "|---|---:|---:|---:|",
            ]
        )
        for route, stats in model["per_route"].items():
            value = "—" if stats["pass_rate"] is None else f"{stats['pass_rate']:.3f}"
            lines.append(
                f"| `{route}` | {stats['passed']} | {stats['total']} | {value} |"
            )
        lines.extend(["", "## 失败案例", ""])
        if not model["failures"] and not model["errors"]:
            lines.append("无。")
        else:
            for error in model["errors"]:
                lines.append(f"- 结果结构错误：{error}")
            for item in model["failures"]:
                lines.append(
                    f"- `{item['id']}`：{'；'.join(item['failures'])}。"
                    f"请求：{item['text']}"
                )
    else:
        lines.extend(
            [
                "",
                "## 模型路由结果",
                "",
                "本次只运行静态扫描，缺少模型路由证据。",
            ]
        )
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "latest.md").write_text(
        render_markdown(report), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--skills-root", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--codex", action="store_true", help="调用只读 Codex 模型批量评测")
    source.add_argument("--predictions-file", type=Path, help="评估已有 predictions JSON")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    skills_root = (args.skills_root or project_root / ".agents" / "skills").resolve()
    cases_path = args.cases.resolve()
    report_dir = args.report_dir.resolve()
    try:
        descriptions = discover_descriptions(skills_root)
        contract = load_json(cases_path)
        contract_errors = validate_contract(contract, descriptions)
        static = scan_static_overlap(descriptions, contract)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Skill 路由评测配置错误：{error}", file=sys.stderr)
        return 2
    report: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "evidence_kind": "static_description_scan",
        "status": "static_passed",
        "skill_count": len(descriptions),
        "case_count": len(contract.get("cases", [])),
        "skills": sorted(descriptions),
        "description_fingerprint": description_fingerprint(descriptions),
        "contract_file": cases_path.relative_to(project_root).as_posix()
        if cases_path.is_relative_to(project_root)
        else str(cases_path),
        "contract_errors": contract_errors,
        "semantic_risk_hypotheses": contract.get("semantic_risk_hypotheses", []),
        "recall_risk_hypotheses": contract.get("recall_risk_hypotheses", []),
        "static_overlap": static,
        "runner": None,
        "model_evaluation": None,
    }
    predictions: dict[str, Any] | None = None
    runner: dict[str, Any] | None = None
    if args.predictions_file:
        try:
            predictions = load_json(args.predictions_file.resolve())
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"无法读取 predictions：{error}", file=sys.stderr)
            return 2
        runner = {
            "kind": "recorded_fixture",
            "note": "只用于验证评测器契约，不是模型执行证据。",
        }
    elif args.codex:
        try:
            predictions, runner = run_codex_classifier(
                project_root,
                descriptions,
                contract["cases"],
                codex_bin=args.codex_bin,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
        except RuntimeError as error:
            report["status"] = "runner_failed"
            report["runner_error"] = str(error)
            if not args.no_write:
                write_reports(report, report_dir)
            print(error, file=sys.stderr)
            return 2
    if predictions is not None:
        model_evaluation = evaluate_predictions(
            contract["cases"], predictions, set(descriptions)
        )
        report["evidence_kind"] = runner["kind"] if runner else "unknown"
        report["runner"] = runner
        report["model_evaluation"] = model_evaluation
        report["status"] = (
            "passed"
            if not contract_errors and static["ok"] and model_evaluation["ok"]
            else "failed"
        )
    elif contract_errors or not static["ok"]:
        report["status"] = "failed"
    if not args.no_write:
        write_reports(report, report_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"passed", "static_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
