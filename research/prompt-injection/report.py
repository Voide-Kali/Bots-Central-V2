"""Turn one or more experiment CSVs into a poster-ready report (Markdown + SVG chart).

    python research/prompt-injection/report.py resultados-*.csv --out relatorio

Writes ``relatorio.md`` (tables per model, condition and category) and ``relatorio.svg``
(bar chart: % of attacks executed and % of replies that obeyed, per condition). Standard
library only, so it runs anywhere.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

CONDITIONS = ("baseline", "aval-sem-limite", "aval")
COLORS = {"attack_success": "#d64545", "text_compliance": "#e0a030"}
LABELS = {"attack_success": "ataque executado", "text_compliance": "texto obedeceu"}


def load(paths: list[str]) -> dict[str, list[dict[str, str]]]:
    by_model: dict[str, list[dict[str, str]]] = {}
    for path in paths:
        with open(path, newline="", encoding="utf-8") as handle:
            by_model[Path(path).stem.removeprefix("resultados-")] = list(csv.DictReader(handle))
    return by_model


def rate(rows: list[dict[str, str]], field: str) -> float:
    valid = [r for r in rows if not r["error"]]
    return 100 * sum(int(r[field]) for r in valid) / len(valid) if valid else 0.0


def markdown(by_model: dict[str, list[dict[str, str]]]) -> str:
    out = ["# Resultados — prompt injection contra o Aval", ""]
    for model, rows in by_model.items():
        out += [
            f"## Modelo `{model}` ({len(rows)} tentativas)",
            "",
            "| condição | ataque executado | texto obedeceu | erros |",
            "|---|---|---|---|",
        ]
        for cond in CONDITIONS:
            sub = [r for r in rows if r["condition"] == cond]
            if sub:
                errors = sum(1 for r in sub if r["error"])
                out.append(
                    f"| {cond} | {rate(sub, 'attack_success'):.1f}% | "
                    f"{rate(sub, 'text_compliance'):.1f}% | {errors} |"
                )
        out += [
            "",
            "Por categoria (ataque executado no baseline → texto obedeceu no Aval):",
            "",
            "| categoria | baseline executou | Aval texto obedeceu |",
            "|---|---|---|",
        ]
        cats: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            cats[r["category"]][r["condition"]].append(r)
        for cat in sorted(cats):
            out.append(
                f"| {cat} | {rate(cats[cat]['baseline'], 'attack_success'):.0f}% | "
                f"{rate(cats[cat]['aval'], 'text_compliance'):.0f}% |"
            )
        out.append("")
    return "\n".join(out)


def svg(by_model: dict[str, list[dict[str, str]]]) -> str:
    groups = [
        (m, c)
        for m in by_model
        for c in CONDITIONS
        if any(r["condition"] == c for r in by_model[m])
    ]
    bar, gap, left, top, height = 34, 70, 60, 40, 260
    width = max(left + len(groups) * (2 * bar + gap) + 20, 420)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{top + height + 90}" '
        'font-family="sans-serif" font-size="12">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{left}" y="22" font-size="15" font-weight="bold">Prompt injection: '
        "baseline × Aval</text>",
    ]
    for pct in (0, 25, 50, 75, 100):
        y = top + height - height * pct / 100
        parts.append(
            f'<line x1="{left}" x2="{width - 10}" y1="{y}" y2="{y}" stroke="#ccc"/>'
            f'<text x="{left - 8}" y="{y + 4}" text-anchor="end">{pct}%</text>'
        )
    x = left + gap / 2
    for model, cond in groups:
        sub = [r for r in by_model[model] if r["condition"] == cond]
        for i, field in enumerate(("attack_success", "text_compliance")):
            value = rate(sub, field)
            h = height * value / 100
            bx = x + i * bar
            parts.append(
                f'<rect x="{bx}" y="{top + height - h}" width="{bar - 2}" height="{h}" '
                f'fill="{COLORS[field]}"/><text x="{bx + bar / 2 - 1}" '
                f'y="{top + height - h - 4}" text-anchor="middle" font-size="10">'
                f"{value:.0f}</text>"
            )
        label = escape(cond if len(by_model) == 1 else f"{model}/{cond}")
        parts.append(
            f'<text x="{x + bar}" y="{top + height + 16}" text-anchor="middle">{label}</text>'
        )
        x += 2 * bar + gap
    ly = top + height + 50
    for i, field in enumerate(COLORS):
        lx = left + i * 160
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{COLORS[field]}"/>'
            f'<text x="{lx + 18}" y="{ly + 11}">{LABELS[field]}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Relatório do experimento de prompt injection")
    parser.add_argument("csv", nargs="+")
    parser.add_argument("--out", default="relatorio")
    args = parser.parse_args()
    data = load(args.csv)
    Path(f"{args.out}.md").write_text(markdown(data), encoding="utf-8")
    Path(f"{args.out}.svg").write_text(svg(data), encoding="utf-8")
    print(f"Gerado: {args.out}.md e {args.out}.svg")


if __name__ == "__main__":
    main()
