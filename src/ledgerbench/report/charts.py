"""Server-side inline SVG charts: no JavaScript, no CDN, renders anywhere.

Two figures: the headline gap bars ("ran fine" vs "business-correct") and the
per-axis breakdown. Pure string assembly over already-computed rates; all text
is escaped, so nothing agent-controlled can reach the markup unescaped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

_BAR_HEIGHT = 26
_GAP = 10
_LABEL_W = 170
_CHART_W = 460
_VALUE_W = 64

_GREEN = "#2e7d32"
_RED = "#c62828"
_GREY = "#9e9e9e"
_BLUE = "#1565c0"


def _bar_svg(rows: Sequence[tuple[str, float, str]], *, title: str) -> str:
    """Render labeled horizontal bars; rates in [0, 1]."""
    height = len(rows) * (_BAR_HEIGHT + _GAP) + 28
    width = _LABEL_W + _CHART_W + _VALUE_W
    parts = [
        f'<svg role="img" aria-label="{escape(title)}" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        f'<text x="0" y="16" font-size="14" font-weight="bold">{escape(title)}</text>',
    ]
    y = 28
    for label, rate, color in rows:
        bar = max(0.0, min(1.0, rate)) * _CHART_W
        parts += [
            f'<text x="0" y="{y + 17}" font-size="12">{escape(label)}</text>',
            f'<rect x="{_LABEL_W}" y="{y}" width="{_CHART_W}" height="{_BAR_HEIGHT}" '
            f'fill="#eeeeee"/>',
            f'<rect x="{_LABEL_W}" y="{y}" width="{bar:.1f}" height="{_BAR_HEIGHT}" '
            f'fill="{color}"/>',
            f'<text x="{_LABEL_W + _CHART_W + 8}" y="{y + 17}" font-size="12">'
            f"{rate * 100:.1f}%</text>",
        ]
        y += _BAR_HEIGHT + _GAP
    parts.append("</svg>")
    return "".join(parts)


def gap_chart(ran_fine: float, business_correct: float) -> str:
    """The headline: execution success vs business correctness."""
    return _bar_svg(
        [
            ("queries that ran fine", ran_fine, _BLUE),
            ("business-correct answers", business_correct, _GREEN),
        ],
        title="The gap: execution success is not business correctness",
    )


def axis_chart(rates: Mapping[str, float]) -> str:
    """Per-axis pass rates."""
    rows = [
        (axis, rate, _GREEN if rate >= 0.8 else (_RED if rate < 0.5 else _GREY))
        for axis, rate in rates.items()
    ]
    return _bar_svg(rows, title="Per-axis pass rate")


def condition_chart(closed: Mapping[str, float], open_: Mapping[str, float]) -> str:
    """Closed-book vs open-book comparison, interleaved per axis."""
    rows: list[tuple[str, float, str]] = []
    for axis in closed:
        rows.append((f"{axis} (closed book)", closed[axis], _GREY))
        rows.append((f"{axis} (open book)", open_.get(axis, 0.0), _BLUE))
    return _bar_svg(rows, title="Closed book vs open book (does the rulebook help?)")
