#!/usr/bin/env python3
"""Render pure-SVG DORA trend charts from dora-ai-history.json."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import dora_history  # noqa: E402

DEFAULT_HISTORY = os.path.join(
    REPO, "engine", "skills", "reflect", "baselines", "dora-ai-history.json"
)
DEFAULT_OUT_DIR = os.path.join(REPO, "engine", "skills", "reflect", "baselines", "charts")

ELITE_REWORK = 0.15


def _fmt_axis(v: float, *, kind: str) -> str:
    if kind == "duration":
        if v < 60:
            return f"{int(round(max(0, v)))}s"
        if v < 3600:
            return f"{max(0, v) / 60:.0f}m"
        if v < 86400:
            return f"{max(0, v) / 3600:.1f}h"
        return f"{max(0, v) / 86400:.1f}d"
    if kind == "rate":
        return f"{v * 100:.0f}%"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.1f}"


def _series(
    points: list[dict[str, Any]], window: str, group: str, field: str
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for p in points:
        win = (p.get("windows") or {}).get(window) or {}
        blob = win.get(group) or {}
        val = blob.get(field)
        if val is None:
            continue
        try:
            out.append((str(p.get("captured_at") or "")[:10], float(val)))
        except (TypeError, ValueError):
            continue
    return out


def _svg_line_chart(
    series: list[tuple[str, float]],
    *,
    title: str,
    ylabel: str,
    width: int = 640,
    height: int = 240,
    y_min: float | None = None,
    y_max: float | None = None,
    guideline: float | None = None,
    guideline_label: str | None = None,
    lower_is_better: bool = True,
    axis_kind: str = "plain",
) -> str:
    pad_l, pad_r, pad_t, pad_b = 56, 16, 28, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    if not series:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<text x="20" y="40" font-family="system-ui,sans-serif" font-size="14">'
            f"No data yet for {title}</text></svg>\n"
        )
    ys = [v for _, v in series]
    lo = min(ys) if y_min is None else y_min
    hi = max(ys) if y_max is None else y_max
    if guideline is not None:
        lo = min(lo, guideline)
        hi = max(hi, guideline)
    if hi <= lo:
        hi = lo + 1.0
    # Preserve explicit bounds so a fixed 0–100% axis visibly labels 0% and
    # 100% instead of padding to misleading -5% and 105% ticks.
    span = hi - lo
    if y_min is None:
        lo -= span * 0.05
    if y_max is None:
        hi += span * 0.05

    def x_at(i: int) -> float:
        if len(series) == 1:
            return pad_l + plot_w / 2
        return pad_l + (i / (len(series) - 1)) * plot_w

    def y_at(v: float) -> float:
        return pad_t + (1 - (v - lo) / (hi - lo)) * plot_h

    pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_, v) in enumerate(series))
    circles = "\n".join(
        f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="4.5" fill="#2563eb"/>'
        for i, (_, v) in enumerate(series)
    )
    labels = "\n".join(
        f'<text x="{x_at(i):.1f}" y="{height - 12}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="11" fill="#64748b">{label[5:]}</text>'
        for i, (label, _) in enumerate(series)
    )
    point_labels = ""
    if axis_kind == "rate" and width >= 640:
        point_labels = "\n".join(
            f'<text x="{x_at(i):.1f}" y="{y_at(value) + (18 if y_at(value) < pad_t + 24 else -10):.1f}" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" font-size="11" '
            f'font-weight="600" fill="#1d4ed8">{_fmt_axis(value, kind="rate")}</text>'
            for i, (_, value) in enumerate(series)
        )
    guide = ""
    if guideline is not None:
        gy = y_at(guideline)
        glabel = guideline_label or str(guideline)
        guide = (
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" '
            f'stroke="#16a34a" stroke-dasharray="4 3" stroke-width="1.5"/>'
            f'<text x="{width - pad_r - 4}" y="{gy - 4:.1f}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="10" fill="#16a34a">{glabel}</text>'
        )
    direction = "lower is better" if lower_is_better else "higher is better"
    y_ticks = ""
    for v in (lo, (lo + hi) / 2, hi):
        yy = y_at(v)
        y_ticks += (
            f'<text x="{pad_l - 6}" y="{yy + 3:.1f}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="10" fill="#64748b">'
            f"{_fmt_axis(v, kind=axis_kind)}</text>\n"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{pad_l}" y="20" font-family="system-ui,sans-serif" font-size="17" font-weight="600" fill="#0f172a">{title}</text>
  <text x="{width - pad_r}" y="20" text-anchor="end" font-family="system-ui,sans-serif" font-size="12" fill="#94a3b8">{direction}</text>
  <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="#e2e8f0"/>
  <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" stroke="#e2e8f0"/>
  {y_ticks}
  <text x="14" y="{pad_t + plot_h / 2}" transform="rotate(-90 14 {pad_t + plot_h / 2})" text-anchor="middle" font-family="system-ui,sans-serif" font-size="11" fill="#64748b">{ylabel}</text>
  {guide}
  <polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{pts}"/>
  {circles}
{point_labels}
  {labels}
</svg>
"""


def render_all(history: dict[str, Any], out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    points = list(history.get("points") or [])
    written: list[str] = []

    specs = [
        ("rework-7d.svg", "7d", "rework_rate", "rate", "Rework rate (7d)", "rate", 0.0, 1.0, ELITE_REWORK, "elite 15%", True, "rate"),
        ("rework-30d.svg", "30d", "rework_rate", "rate", "Rework rate (30d)", "rate", 0.0, 1.0, ELITE_REWORK, "elite 15%", True, "rate"),
        ("deploy-7d.svg", "7d", "deploy_frequency", "per_day", "Deploy frequency (7d)", "merges/day", None, None, None, None, False, "plain"),
        ("mttr-7d.svg", "7d", "mttr", "median_seconds", "MTTR median (7d)", "time", None, None, None, None, True, "duration"),
    ]
    for fname, window, group, field, title, ylabel, ymin, ymax, guide, glabel, lower, axis_kind in specs:
        series = _series(points, window, group, field)
        svg = _svg_line_chart(
            series,
            title=title,
            ylabel=ylabel,
            width=960,
            height=360,
            y_min=ymin,
            y_max=ymax,
            guideline=guide,
            guideline_label=glabel,
            lower_is_better=lower,
            axis_kind=axis_kind,
        )
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(svg)
        written.append(path)

    # Front-page chart for README (rework 7d only, sized for point labels).
    series = _series(points, "7d", "rework_rate", "rate")
    spark = _svg_line_chart(
        series,
        title="Rework 7d",
        ylabel="",
        width=640,
        height=220,
        y_min=0.0,
        y_max=1.0,
        guideline=ELITE_REWORK,
        guideline_label="15%",
        lower_is_better=True,
        axis_kind="rate",
    )
    spark_path = os.path.join(out_dir, "rework-7d-spark.svg")
    with open(spark_path, "w", encoding="utf-8") as handle:
        handle.write(spark)
    written.append(spark_path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", default=DEFAULT_HISTORY)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)
    history = dora_history.load_history(args.history)
    paths = render_all(history, args.out_dir)
    for p in paths:
        print(f"wrote {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
