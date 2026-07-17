"""Server-rendered SVG/HTML chart helpers for the Analytics screen.

No charting library, no new JS dependency - htmx stays the only vendored JS in
this app. Colors come from the dataviz skill's validated reference palette
(light mode only - this app has no dark theme). See the skill's
references/palette.md for where each hex comes from and
scripts/validate_palette.js for how the WIP-over-time ordinal ramp below was
checked before use.
"""
import math

# --- Palette (light mode only; see dataviz skill references/palette.md) ---
CHART_SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

SEQUENTIAL_BLUE = "#2a78d6"  # default single hue for magnitude (bars)

# 5-step ordinal ramp for the WIP-over-time stage-phase buckets (light -> dark =
# least complete -> most complete). Validated: all checks pass, see
# `validate_palette.js "<these 5 hexes>" --mode light --ordinal`.
ORDINAL_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]

# Full sequential range for the continuous heatmap (palette.md: "the full
# 100->700 range is for sequential encoding... heatmaps").
HEATMAP_LIGHT = (0xCD, 0xE2, 0xFB)  # step 100
HEATMAP_DARK = (0x0D, 0x36, 0x6B)  # step 700

STATUS_CRITICAL = "#d03b3b"

BAR_MAX_THICKNESS = 20
BAR_GAP = 10
SEGMENT_GAP = 2  # true "touching marks" gap, per marks-and-anatomy.md


def _esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def bucket_stages(stage_order: list[str], max_buckets: int = 5) -> list[tuple[str, list[str]]]:
    """Group ordered stage names into at most `max_buckets` contiguous buckets,
    for color-safe display on the WIP-over-time chart. Generic over stage count
    and names (stages are user-editable in Settings), never hardcodes a stage
    name -> bucket mapping."""
    n = len(stage_order)
    if n == 0:
        return []
    if n <= max_buckets:
        return [(s, [s]) for s in stage_order]
    bucket_size = math.ceil(n / max_buckets)
    buckets = []
    for i in range(0, n, bucket_size):
        chunk = stage_order[i : i + bucket_size]
        label = chunk[0] if len(chunk) == 1 else f"{chunk[0]} – {chunk[-1]}"
        buckets.append((label, chunk))
    return buckets


def heatmap_color(value: float, min_value: float, max_value: float) -> str:
    """Linear-interpolate along the sequential blue ramp for a magnitude heatmap cell."""
    if max_value <= min_value:
        t = 0.0
    else:
        t = (value - min_value) / (max_value - min_value)
        t = max(0.0, min(1.0, t))
    r = round(HEATMAP_LIGHT[0] + (HEATMAP_DARK[0] - HEATMAP_LIGHT[0]) * t)
    g = round(HEATMAP_LIGHT[1] + (HEATMAP_DARK[1] - HEATMAP_LIGHT[1]) * t)
    b = round(HEATMAP_LIGHT[2] + (HEATMAP_DARK[2] - HEATMAP_LIGHT[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def heatmap_text_color(bg_hex: str) -> str:
    """White or ink text, chosen by the fill's luminance, so a label inside a
    colored cell always clears contrast (marks-and-anatomy.md)."""
    r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#ffffff" if luminance < 0.55 else TEXT_PRIMARY


def bar_chart_horizontal(data: list[tuple[str, float]], *, unit: str = "") -> str:
    """Ranked/categorical horizontal bars, single hue. `data` is pre-sorted by caller."""
    if not data:
        return '<p class="chart-empty">Not enough data yet.</p>'

    label_col = 170
    value_col = 60
    plot_width = 380
    row_h = BAR_MAX_THICKNESS + 8
    width = label_col + plot_width + value_col
    height = row_h * len(data)
    max_value = max(v for _, v in data) or 1

    bars = []
    for i, (label, value) in enumerate(data):
        y = i * row_h
        bar_len = max(2, (value / max_value) * plot_width)
        bar_y = y + (row_h - BAR_MAX_THICKNESS) / 2
        bars.append(
            f'<text x="{label_col - 8}" y="{y + row_h / 2 + 4}" text-anchor="end" '
            f'font-size="12" fill="{TEXT_SECONDARY}">{_esc(label)}</text>'
            f'<rect x="{label_col}" y="{bar_y:.1f}" width="{bar_len:.1f}" height="{BAR_MAX_THICKNESS}" '
            f'rx="4" fill="{SEQUENTIAL_BLUE}"><title>{_esc(label)}: {value:g}{unit}</title></rect>'
            f'<text x="{label_col + bar_len + 6:.1f}" y="{y + row_h / 2 + 4}" '
            f'font-size="12" fill="{TEXT_PRIMARY}">{value:g}{unit}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Bar chart">{"".join(bars)}</svg>'
    )


def bar_chart_vertical(data: list[tuple[str, float]], *, unit: str = "") -> str:
    """Time-series vertical bars, single hue. `data` is (label, value) in x order."""
    if not data:
        return '<p class="chart-empty">Not enough data yet.</p>'

    bar_w = BAR_MAX_THICKNESS
    plot_h = 160
    axis_h = 28
    width = len(data) * (bar_w + BAR_GAP) + BAR_GAP
    height = plot_h + axis_h
    max_value = max(v for _, v in data) or 1

    bars = []
    for i, (label, value) in enumerate(data):
        x = BAR_GAP + i * (bar_w + BAR_GAP)
        bar_h = max(2, (value / max_value) * plot_h)
        y = plot_h - bar_h
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{bar_h:.1f}" rx="4" '
            f'fill="{SEQUENTIAL_BLUE}"><title>{_esc(label)}: {value:g}{unit}</title></rect>'
            f'<text x="{x + bar_w / 2}" y="{y - 4:.1f}" text-anchor="middle" font-size="11" '
            f'fill="{TEXT_PRIMARY}">{value:g}</text>'
            f'<text x="{x + bar_w / 2}" y="{plot_h + 16}" text-anchor="middle" font-size="10" '
            f'fill="{MUTED}">{_esc(label)}</text>'
        )

    baseline = f'<line x1="0" y1="{plot_h}" x2="{width}" y2="{plot_h}" stroke="{BASELINE}" stroke-width="1"/>'
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Bar chart">{baseline}{"".join(bars)}</svg>'
    )


def stacked_bar_chart_vertical(
    dates: list[str], stage_order: list[str], by_date: dict[str, dict[str, int]]
) -> str:
    """WIP-over-time: one bar per date, segments per stage-phase bucket, using
    the validated 5-step ordinal ramp (light = least complete, dark = most
    complete) instead of a 13-color categorical set - see bucket_stages()."""
    if not dates:
        return '<p class="chart-empty">No movement history yet.</p>'

    # stage_order arrives most-complete-first (rank 1 = FI Done); the ordinal
    # ramp is light->dark = least-complete->most-complete, so bucket in the
    # reverse (progress) direction to match.
    buckets = bucket_stages(list(reversed(stage_order)), max_buckets=len(ORDINAL_RAMP))
    bucket_totals_per_date = []
    grand_max = 1
    for d in dates:
        by_stage = by_date.get(d, {})
        totals = [sum(by_stage.get(s, 0) for s in stages) for _, stages in buckets]
        bucket_totals_per_date.append(totals)
        grand_max = max(grand_max, sum(totals))

    bar_w = BAR_MAX_THICKNESS
    plot_h = 200
    axis_h = 28
    legend_h = 22
    width = len(dates) * (bar_w + BAR_GAP) + BAR_GAP
    height = legend_h + plot_h + axis_h

    legend_items = []
    lx = 0
    for (label, _stages), color in zip(buckets, ORDINAL_RAMP):
        legend_items.append(
            f'<rect x="{lx}" y="4" width="10" height="10" rx="2" fill="{color}"/>'
            f'<text x="{lx + 14}" y="13" font-size="10" fill="{TEXT_SECONDARY}">{_esc(label)}</text>'
        )
        lx += 18 + 7 * len(label) + 14
    legend = f'<g>{"".join(legend_items)}</g>'

    bars = []
    for i, d in enumerate(dates):
        x = BAR_GAP + i * (bar_w + BAR_GAP)
        cursor_y = plot_h
        for seg_value, color, (label, _stages) in zip(bucket_totals_per_date[i], ORDINAL_RAMP, buckets):
            if seg_value <= 0:
                continue
            seg_h = (seg_value / grand_max) * plot_h
            seg_h = max(0, seg_h - SEGMENT_GAP)
            cursor_y -= seg_h + SEGMENT_GAP
            bars.append(
                f'<rect x="{x}" y="{cursor_y + legend_h:.1f}" width="{bar_w}" height="{seg_h:.1f}" '
                f'fill="{color}"><title>{_esc(label)} on {_esc(d)}: {seg_value}</title></rect>'
            )
        bars.append(
            f'<text x="{x + bar_w / 2}" y="{legend_h + plot_h + 16}" text-anchor="middle" '
            f'font-size="9" fill="{MUTED}">{_esc(d[5:])}</text>'
        )

    baseline = (
        f'<line x1="0" y1="{legend_h + plot_h}" x2="{width}" y2="{legend_h + plot_h}" '
        f'stroke="{BASELINE}" stroke-width="1"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Stacked bar chart">{legend}{baseline}{"".join(bars)}</svg>'
    )
