#!/usr/bin/env python
"""Render the two result charts used in the README, the docs and the dataset cards.

    python scripts/make_result_charts.py docs/img

The numbers are typed in from ``docs/results.md`` and ``docs/FINDINGS.md`` rather
than recomputed, because those files are the published record and a chart that
silently disagrees with them would be worse than no chart. Change a number there
and here together.

Unlike the rest of the repo this needs matplotlib (``pip install matplotlib``);
it is a one-off authoring tool, not part of the package or of CI. The colours are
a four-step palette checked for contrast and for colour-blind separation, on a
light surface so the images stay readable on GitHub, Hugging Face and Kaggle in
either theme.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#dcdbd6"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "text.color": INK,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "ytick.color": INK2,
})


def round_bars(ax, bars, radius_frac=0.45):
    """Replace rectangles with 4px-ish rounded-end versions."""
    for b in bars:
        x, y = b.get_xy()
        w, h = b.get_width(), b.get_height()
        if w <= 0:
            continue
        r = min(h * radius_frac, w / 2)
        b.set_visible(False)
        ax.add_patch(FancyBboxPatch(
            (x + r, y + r), max(w - 2 * r, 1e-6), h - 2 * r,
            boxstyle=f"round,pad={r},rounding_size={r}",
            linewidth=0, facecolor=b.get_facecolor(), mutation_aspect=1,
            clip_on=False, zorder=3))


def frame(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)


# ---------------------------------------------------------------- chart 1
def detectors(path):
    rows = [("Pattern rules", 50, 26), ("Llama Prompt Guard 2", 24, 5)]
    fig, ax = plt.subplots(figsize=(7.4, 2.7), dpi=170)
    h = 0.42
    gap = 0.045          # 2px surface gap between adjacent bars
    for i, (name, en, de) in enumerate(rows):
        b1 = ax.barh(i + (h + gap) / 2, en, height=h, color=BLUE)
        b2 = ax.barh(i - (h + gap) / 2, de, height=h, color=ORANGE)
        round_bars(ax, b1)
        round_bars(ax, b2)
        for val, off in ((en, (h + gap) / 2), (de, -(h + gap) / 2)):
            ax.text(val + 1.2, i + off, f"{val}%", va="center", ha="left",
                    fontsize=10, color=INK, fontweight="bold")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.5, color=INK)
    ax.set_ylim(-0.62, len(rows) - 0.38)
    ax.set_xlim(0, 60)
    ax.set_xticks([0, 20, 40, 60])
    ax.set_xticklabels(["0", "20", "40", "60%"], fontsize=9)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    frame(ax)
    ax.set_title("Both detectors miss far more German than English",
                 fontsize=12.5, color=INK, loc="left", pad=34, fontweight="bold")
    ax.text(0, 1.02, "Share of injection attacks caught  ·  deepset test split, n = 34 EN / 19 DE",
            transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    ax.legend(handles=[plt.Line2D([], [], marker="s", linestyle="", markersize=8,
                                  color=BLUE, label="English"),
                       plt.Line2D([], [], marker="s", linestyle="", markersize=8,
                                  color=ORANGE, label="German")],
              loc="upper left", bbox_to_anchor=(-0.002, -0.17), ncol=2,
              frameon=False, fontsize=9.5, labelcolor=INK2,
              handletextpad=0.4, borderpad=0.1, columnspacing=1.4)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)


# ---------------------------------------------------------------- chart 2
def defence(path):
    rows = [            # model, no defence, layered, note
        ("Qwen 3.8 27B", 6, 4, ""),
        ("Gemini 3.5 Flash-Lite", 10, 7, ""),
        ("gpt-oss 120B", 25, 27, ""),
        ("gpt-oss 20B", 29, 19, "p = 0.014"),
    ]
    fig, ax = plt.subplots(figsize=(7.4, 3.1), dpi=170)
    for i, (name, before, after, note) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.plot([before, after], [y, y], color=GRID, linewidth=2, zorder=1,
                solid_capstyle="round")
        ax.plot([before], [y], marker="o", markersize=10, color=BLUE, zorder=3,
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.plot([after], [y], marker="o", markersize=10, color=ORANGE, zorder=3,
                markeredgecolor=SURFACE, markeredgewidth=2)
        lo, hi = (before, after) if before < after else (after, before)
        ax.text(lo - 1.4, y, f"{lo}%", va="center", ha="right", fontsize=10,
                color=INK, fontweight="bold")
        ax.text(hi + 1.4, y, f"{hi}%", va="center", ha="left", fontsize=10,
                color=INK, fontweight="bold")
        if note:
            ax.text(hi + 6.5, y, note, va="center", ha="left", fontsize=9.5,
                    color=INK2, style="italic")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=10.5, color=INK)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlim(0, 45)
    ax.set_xticks([0, 10, 20, 30, 40])
    ax.set_xticklabels(["0", "10", "20", "30", "40%"], fontsize=9)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    frame(ax)
    ax.set_title("The layered defence clearly helped one model of four",
                 fontsize=12.5, color=INK, loc="left", pad=34, fontweight="bold")
    ax.text(0, 1.02, "Share of 138 attacks that worked  ·  temperature 0, paired McNemar test",
            transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    ax.legend(handles=[plt.Line2D([], [], marker="o", linestyle="", markersize=8,
                                  color=BLUE, label="No defence"),
                       plt.Line2D([], [], marker="o", linestyle="", markersize=8,
                                  color=ORANGE, label="Layered defence")],
              loc="upper left", bbox_to_anchor=(-0.002, -0.17), ncol=2,
              frameon=False, fontsize=9.5, labelcolor=INK2,
              handletextpad=0.4, borderpad=0.1, columnspacing=1.4)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)


if __name__ == "__main__":
    import sys
    out = sys.argv[1]
    detectors(out + "/detectors-by-language.png")
    defence(out + "/defence-effect.png")
    print("written")
