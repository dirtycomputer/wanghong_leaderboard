"""Render the static leaderboard site.

f-string templates only — no jinja2 / no JS — so the produced
``site/`` is hostable on any static file server (GitHub Pages, S3, …)
and reproducible byte-for-byte.
"""

from __future__ import annotations

import html
import shutil
import time
from pathlib import Path

from leaderboard.aggregate import (
    EvaluationRecord,
    HarnessHistory,
    contamination_events,
)

_STATIC_SRC = Path(__file__).resolve().parent / "static"

#: Per-axis scoring weights (mirrors :mod:`judge.rubric`).
_AXIS_LABELS: tuple[tuple[str, str], ...] = (
    ("protocol", "Protocol / safety"),
    ("gold_graph", "Gold-graph alignment"),
    ("correctness", "Mathematical correctness"),
    ("gap_resistance", "Adversarial gap resistance"),
    ("novelty", "Novelty / independence"),
    ("clarity", "Clarity / auditability"),
)


def render_site(
    histories: list[HarnessHistory],
    out_dir: Path,
    *,
    generated_at: str | None = None,
    title: str = "Wang Hong (3D Kakeya) Leaderboard",
) -> dict[str, Path]:
    """Render index + per-evaluation detail pages + static assets.

    Returns a dict mapping output file labels to their on-disk paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    static_out = out_dir / "static"
    if static_out.exists():
        shutil.rmtree(static_out)
    shutil.copytree(_STATIC_SRC, static_out)

    if generated_at is None:
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    submissions_dir = out_dir / "submissions"
    if submissions_dir.exists():
        shutil.rmtree(submissions_dir)
    submissions_dir.mkdir()

    written: dict[str, Path] = {}
    detail_pages: dict[str, str] = {}  # eval_id -> relative href
    for h in histories:
        for ev in h.evaluations:
            slug = _slug(h.name, ev.evaluation_id)
            detail_pages[ev.evaluation_id] = f"submissions/{slug}.html"
            page_path = submissions_dir / f"{slug}.html"
            page_path.write_text(
                _render_detail(h, ev, title=title, generated_at=generated_at),
                encoding="utf-8",
            )
            written[f"submission:{slug}"] = page_path

    index_path = out_dir / "index.html"
    index_path.write_text(
        _render_index(
            histories,
            detail_pages=detail_pages,
            title=title,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    written["index"] = index_path
    return written


def _verdict_cell(verdict: str) -> str:
    safe = html.escape(verdict)
    return f"<td><span class='verdict {safe}'>{safe}</span></td>"


def _slug(harness_name: str, evaluation_id: str) -> str:
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in harness_name.lower()
    ).strip("-") or "unnamed"
    safe_eval = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in evaluation_id
    ).strip("-") or "no-eval-id"
    return f"{safe_name}_{safe_eval}"


def _render_index(
    histories: list[HarnessHistory],
    *,
    detail_pages: dict[str, str],
    title: str,
    generated_at: str,
) -> str:
    rows = []
    for rank, h in enumerate(histories, start=1):
        latest = h.latest
        href = detail_pages.get(latest.evaluation_id, "#")
        version_html = (
            f" <span class='mono'>{html.escape(h.version)}</span>" if h.version else ""
        )
        rows.append(
            "<tr>"
            f"<td class='rank'>{rank}</td>"
            f"<td><a href='{html.escape(href)}'>{html.escape(h.name)}</a>"
            + version_html
            + "</td>"
            + _verdict_cell(latest.verdict)
            + f"<td class='score'>{latest.final_score:.1f}</td>"
            f"<td class='score'>{latest.weighted_score:.1f}</td>"
            f"<td class='mono'>{html.escape(latest.evaluation_id) or '—'}</td>"
            f"<td class='mono'>{html.escape(latest.rubric_version) or '—'}</td>"
            f"<td>{len(h.evaluations)}</td>"
            "</tr>"
        )
    table = (
        "<table>"
        "<thead><tr>"
        "<th>#</th><th>Harness</th><th>Verdict</th><th>Final</th>"
        "<th>Weighted</th><th>Eval ID</th><th>Rubric</th><th>Runs</th>"
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
        if rows
        else "<p class='note'>No submissions scored yet.</p>"
    )

    events = contamination_events(histories)
    if events:
        def _event_row(e: dict) -> str:
            version_html = (
                f" <span class='mono'>{html.escape(e['harness_version'])}</span>"
                if e.get("harness_version")
                else ""
            )
            reasons = "<br>".join(html.escape(r) for r in e["cap_reasons"])
            return (
                "<tr>"
                f"<td>{html.escape(e['harness_name'])}{version_html}</td>"
                + _verdict_cell(e["verdict"])
                + f"<td class='mono'>{html.escape(e['evaluation_id']) or '—'}</td>"
                f"<td class='score'>{e['final_score']:.1f}</td>"
                f"<td>{reasons}</td>"
                "</tr>"
            )

        ev_rows = "".join(_event_row(e) for e in events)
        anti_cheat = (
            "<table><thead><tr>"
            "<th>Harness</th><th>Verdict</th><th>Eval ID</th>"
            "<th>Final</th><th>Cap reasons</th>"
            "</tr></thead><tbody>" + ev_rows + "</tbody></table>"
        )
    else:
        anti_cheat = "<p class='note'>No contamination or DQ events recorded.</p>"

    body = (
        "<header class='site'>"
        f"<h1>{html.escape(title)}</h1>"
        "<p class='lead'>Time-capsule scores for the Wang Hong (3D Kakeya) test. "
        "Rendered from <code>evaluation_report.json</code>.</p>"
        f"<p class='meta'>generated {html.escape(generated_at)}</p>"
        "</header>"
        "<main>"
        "<h2>Current scores</h2>"
        "<p class='note'>One row per harness, latest evaluation_id. "
        "Click a name for per-axis breakdown and historical evaluations.</p>"
        f"{table}"
        "<h2>Anti-cheat events</h2>"
        "<p class='note'>Every evaluation that triggered a contamination or "
        "disqualification cap, current or historical.</p>"
        f"{anti_cheat}"
        "<footer>"
        "<p>Built by <a href='https://github.com/dirtycomputer/wanghong_leaderboard'>"
        "wanghong_leaderboard</a>. "
        "See <code>docs/PUBLIC_RULES.md</code> for the rubric and "
        "<code>docs/EVAL_VERSIONING.md</code> for how scores are versioned.</p>"
        "</footer>"
        "</main>"
    )
    return _wrap_html(title, body)


def _render_detail(
    h: HarnessHistory,
    ev: EvaluationRecord,
    *,
    title: str,
    generated_at: str,
) -> str:
    subscores = ev.report.get("subscores") or {}
    bars = []
    for key, label in _AXIS_LABELS:
        value = float(subscores.get(key) or 0.0)
        pct = max(0.0, min(100.0, value))
        bars.append(
            "<li>"
            f"<span>{html.escape(label)}</span>"
            f"<span class='bar'><span style='width:{pct:.1f}%'></span></span>"
            f"<span class='value'>{value:.1f}</span>"
            "</li>"
        )

    caps_html = ""
    if ev.applied_caps:
        items = []
        for cap in ev.applied_caps:
            try:
                cap_value = float(cap.get("cap") or 0.0)
            except (TypeError, ValueError):
                cap_value = 0.0
            items.append(
                "<li>"
                f"<span class='cap-value'>≤ {cap_value:.0f}</span>"
                f"{html.escape(str(cap.get('reason') or ''))} "
                f"<span class='mono'>({html.escape(str(cap.get('source') or ''))})</span>"
                "</li>"
            )
        caps_html = "<ul class='cap-list'>" + "".join(items) + "</ul>"
    else:
        caps_html = "<p class='note'>No applied caps.</p>"

    judge_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(j.get('role') or ''))}</td>"
        f"<td class='mono'>{html.escape(str(j.get('model') or ''))}</td>"
        f"<td>{'yes' if j.get('web_access') else 'no'}</td>"
        "</tr>"
        for j in (ev.report.get("judge_models") or [])
        if isinstance(j, dict)
    )
    judges_html = (
        "<table><thead><tr><th>Role</th><th>Model</th><th>Web</th></tr></thead>"
        f"<tbody>{judge_rows}</tbody></table>"
        if judge_rows
        else "<p class='note'>No judge model record on this report.</p>"
    )

    history_rows = "".join(
        "<tr>"
        f"<td class='mono'>{html.escape(other.evaluation_id)}</td>"
        + _verdict_cell(other.verdict)
        + f"<td class='score'>{other.final_score:.1f}</td>"
        f"<td class='score'>{other.weighted_score:.1f}</td>"
        "</tr>"
        for other in h.evaluations
        if other.evaluation_id != ev.evaluation_id
    )
    history_html = (
        "<table><thead><tr>"
        "<th>Eval ID</th><th>Verdict</th><th>Final</th><th>Weighted</th>"
        "</tr></thead><tbody>" + history_rows + "</tbody></table>"
        if history_rows
        else "<p class='note'>This is the only evaluation recorded for this harness.</p>"
    )

    submission = ev.report.get("submission") or {}
    corpus_hash = str(submission.get("corpus_hash") or "—")
    gold_hash = str(ev.report.get("gold_graph_hash") or "—")

    body = (
        "<header class='site'>"
        f"<h1>{html.escape(h.name)}"
        + (
            f" <span class='mono'>{html.escape(h.version)}</span>"
            if h.version
            else ""
        )
        + "</h1>"
        f"<p class='lead'>Score <strong>{ev.final_score:.1f}</strong> "
        f"(weighted {ev.weighted_score:.1f}) — "
        f"<span class='verdict {html.escape(ev.verdict)}'>{html.escape(ev.verdict)}</span></p>"
        f"<p class='meta'>"
        f"evaluation_id={html.escape(ev.evaluation_id)} · "
        f"rubric={html.escape(ev.rubric_version)} · "
        f"corpus_hash={html.escape(corpus_hash)} · "
        f"gold_graph_hash={html.escape(gold_hash)} · "
        f"generated {html.escape(generated_at)}"
        "</p>"
        "</header>"
        "<main>"
        "<p><a href='../index.html'>← back to leaderboard</a></p>"
        "<h2>Per-axis subscores</h2>"
        f"<ul class='axis-bars'>{''.join(bars)}</ul>"
        "<h2>Applied caps</h2>"
        f"{caps_html}"
        "<h2>Judge models</h2>"
        f"{judges_html}"
        "<h2>Historical evaluations</h2>"
        f"{history_html}"
        "</main>"
    )
    return _wrap_html(
        f"{h.name} · {title}", body, style_href="../static/style.css"
    )


def _wrap_html(title: str, body: str, *, style_href: str = "static/style.css") -> str:
    return (
        "<!doctype html>"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        f'<link rel="stylesheet" href="{html.escape(style_href, quote=True)}">'
        "</head><body>" + body + "</body></html>"
    )
