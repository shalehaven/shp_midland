"""Interactive Plotly HTML viewer for the Midland Basin landing zones.

UX mirrors `delaware_basin_viewer.html`: structure on the left, isopach on
the right, formation dropdown at top, click-to-query at the bottom.
The Midland is entirely in Texas, which uses the survey/abstract block
system rather than PLSS, so the NM Section/Township/Range lookup that
exists in the Delaware viewer is not present here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import geo
from .shapefiles import FORMATIONS_ORDERED
from .surfaces import Surface


def _surface_to_json(s: Surface) -> dict:
    vals = np.where(np.isnan(s.values), None, s.values)
    return {
        "formation": s.formation,
        "layer": s.layer,
        "lats": s.lats.tolist(),
        "lons": s.lons.tolist(),
        "values": [
            [(None if v is None else float(v)) for v in row]
            for row in vals.tolist()
        ],
    }


def build_html(
    surfaces: dict[tuple[str, str], Surface],
    output_path: Path,
    *,
    lat_axis: np.ndarray,
    lon_axis: np.ndarray,
) -> None:
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Structure — TVD from surface (ft)", "Isopach — thickness (ft)"),
        horizontal_spacing=0.10,
    )

    # Two contour traces per formation, plus 14 invisible scaffold traces
    # whose visibility is toggled by the dropdown. First formation visible.
    trace_groups: list[list[int]] = []
    n_traces = 0
    for f_idx, fm in enumerate(FORMATIONS_ORDERED):
        idx_struct = n_traces
        s = surfaces[(fm, "structure")]
        fig.add_trace(
            go.Contour(
                z=s.values, x=s.lons, y=s.lats,
                colorscale="Viridis", reversescale=True,
                contours=dict(
                    coloring="heatmap",
                    showlabels=True,
                    labelfont=dict(size=9, color="white"),
                ),
                colorbar=dict(title=dict(text="TVD (ft)"), x=0.45, len=0.85),
                hovertemplate="lat %{y:.3f}<br>lon %{x:.3f}<br>TVD %{z:,.0f} ft<extra></extra>",
                name=f"{fm} — structure",
                visible=(f_idx == 0),
                connectgaps=False,
            ),
            row=1, col=1,
        )
        n_traces += 1

        idx_iso = n_traces
        s = surfaces[(fm, "isopach")]
        fig.add_trace(
            go.Contour(
                z=s.values, x=s.lons, y=s.lats,
                colorscale="YlOrBr",
                contours=dict(
                    coloring="heatmap",
                    showlabels=True,
                    labelfont=dict(size=9, color="black"),
                ),
                colorbar=dict(title=dict(text="Thickness (ft)"), x=1.02, len=0.85),
                hovertemplate="lat %{y:.3f}<br>lon %{x:.3f}<br>thickness %{z:,.0f} ft<extra></extra>",
                name=f"{fm} — isopach",
                visible=(f_idx == 0),
                connectgaps=False,
            ),
            row=1, col=2,
        )
        n_traces += 1

        trace_groups.append([idx_struct, idx_iso])

    # ---- Texas county overlay (always on, regardless of formation) ----
    overlay_count = 0
    counties = geo.get_tx_county_lines(
        lat_range=(float(lat_axis[0]), float(lat_axis[-1])),
        lon_range=(float(lon_axis[0]), float(lon_axis[-1])),
    )
    for i, c in enumerate(counties):
        first_in_group = (i == 0)
        common = dict(
            x=c["lons"], y=c["lats"], mode="lines",
            line=dict(color="rgba(70,70,70,0.7)", width=0.9),
            legendgroup="counties",
            hoverinfo="text",
            text=[f"{c['name']} County, TX"] * len(c["lons"]),
            connectgaps=False,
        )
        fig.add_trace(go.Scatter(name="County boundary", showlegend=first_in_group, **common), row=1, col=1)
        fig.add_trace(go.Scatter(name="County boundary", showlegend=False,           **common), row=1, col=2)
        n_traces += 2
        overlay_count += 2

    # County name labels at centroids
    if counties:
        labels = geo.county_label_points(counties)
        lab_lons = [l["lon"] for l in labels]
        lab_lats = [l["lat"] for l in labels]
        lab_text = [l["name"] for l in labels]
        common = dict(
            x=lab_lons, y=lab_lats, mode="text",
            text=lab_text, textposition="middle center",
            textfont=dict(size=10, color="rgba(40,40,40,0.85)", family="Arial"),
            legendgroup="county_labels",
            hoverinfo="skip",
        )
        fig.add_trace(go.Scatter(name="County labels", showlegend=True,  **common), row=1, col=1)
        fig.add_trace(go.Scatter(name="County labels", showlegend=False, **common), row=1, col=2)
        n_traces += 2
        overlay_count += 2

    # Picked-point markers (one per subplot). The click handler restyles
    # these via Plotly.restyle to drop the marker where the user clicked.
    pick_idx_left = n_traces
    fig.add_trace(
        go.Scatter(
            x=[], y=[], mode="markers",
            marker=dict(symbol="x-thin", size=14,
                        line=dict(color="#d62728", width=3),
                        color="#d62728"),
            name="Picked point",
            legendgroup="pick", showlegend=True, hoverinfo="skip",
        ),
        row=1, col=1,
    )
    n_traces += 1
    overlay_count += 1
    pick_idx_right = n_traces
    fig.add_trace(
        go.Scatter(
            x=[], y=[], mode="markers",
            marker=dict(symbol="x-thin", size=14,
                        line=dict(color="#d62728", width=3),
                        color="#d62728"),
            name="Picked point",
            legendgroup="pick", showlegend=False, hoverinfo="skip",
        ),
        row=1, col=2,
    )
    n_traces += 1
    overlay_count += 1

    # Dropdown: 14 formation traces toggle; the 2 pick-marker traces stay on.
    buttons = []
    for f_idx, fm in enumerate(FORMATIONS_ORDERED):
        vis = [False] * (n_traces - overlay_count)
        for t in trace_groups[f_idx]:
            vis[t] = True
        vis_full = vis + [True] * overlay_count
        buttons.append(dict(
            label=fm,
            method="update",
            args=[
                {"visible": vis_full},
                {"title.text": f"{fm} — Midland Basin (EIA shale-play maps)"},
            ],
        ))

    fig.update_layout(
        title=dict(
            text=f"{FORMATIONS_ORDERED[0]} — Midland Basin (EIA shale-play maps)",
            x=0.5, xanchor="center",
        ),
        updatemenus=[dict(
            buttons=buttons,
            x=0.0, xanchor="left",
            y=1.18, yanchor="top",
            showactive=True,
            direction="down",
        )],
        height=760,
        margin=dict(l=60, r=60, t=140, b=60),
        plot_bgcolor="white",
        legend=dict(
            x=0.5, xanchor="center",
            y=-0.10, yanchor="top",
            orientation="h",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1,
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
    )
    lat_lo, lat_hi = float(lat_axis[0]), float(lat_axis[-1])
    lon_lo, lon_hi = float(lon_axis[0]), float(lon_axis[-1])
    fig.update_xaxes(title_text="Longitude", range=[lon_lo, lon_hi], row=1, col=1)
    fig.update_xaxes(title_text="Longitude", range=[lon_lo, lon_hi],
                     matches="x", row=1, col=2)
    fig.update_yaxes(title_text="Latitude", range=[lat_lo, lat_hi],
                     scaleanchor="x", scaleratio=1.0, row=1, col=1)
    fig.update_yaxes(title_text="Latitude", range=[lat_lo, lat_hi],
                     matches="y", scaleanchor="x2", scaleratio=1.0, row=1, col=2)

    # Embed surfaces and formation order for the click handler
    surface_payload = {
        f"{fm}__{layer}": _surface_to_json(s)
        for (fm, layer), s in surfaces.items()
    }
    formation_order = [
        {
            "name": fm,
            "structure_key": f"{fm}__structure",
            "isopach_key":   f"{fm}__isopach",
        }
        for fm in FORMATIONS_ORDERED
    ]
    embed = {
        "surfaces": surface_payload,
        "formations": formation_order,
        "pick_trace_indices": [pick_idx_left, pick_idx_right],
    }
    click_js = _click_handler_js(embed)

    html = fig.to_html(
        include_plotlyjs=True,  # full embed -> works offline / behind proxies
        full_html=True,
        post_script=click_js,
        div_id="mbv_plot",
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            "toImageButtonOptions": {"format": "png", "filename": "midland_basin_view"},
        },
    )

    panel_html = """
<div id="mbv_panel" style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 1300px; margin: 12px auto; padding: 14px 18px; border: 1px solid #ddd; border-radius: 8px; background: #fafafa;">
  <div style="display:flex; align-items:center; gap:18px; flex-wrap: wrap;">
    <div style="font-weight:600;">Click any point on either map to query depth/thickness for all formations at that location.</div>
    <div id="mbv_click_loc" style="color:#333;"><b>Lat:</b> &mdash; &nbsp;&nbsp;<b>Lon:</b> &mdash;</div>
  </div>

  <div id="mbv_lookup" style="margin-top:14px; padding:12px 14px; background:#fff; border:1px solid #e0e0e0; border-radius:6px;">
    <div style="font-weight:600; margin-bottom:8px;">Look up a specific point</div>
    <div style="display:flex; gap:24px; flex-wrap:wrap; align-items:flex-end; font-size:13px;">
      <div>
        <div style="color:#555; margin-bottom:3px;">Lat / Lon (decimal &deg;)</div>
        <input id="mbv_in_lat" type="number" step="0.0001" placeholder="32.20" style="width:110px; padding:4px;" />
        <input id="mbv_in_lon" type="number" step="0.0001" placeholder="-101.80" style="width:110px; padding:4px;" />
      </div>
      <div>
        <div style="color:#555; margin-bottom:3px;">TVD (ft from surface, optional)</div>
        <input id="mbv_in_depth" type="number" step="100" placeholder="9500" style="width:110px; padding:4px;" />
      </div>
      <button id="mbv_lookup_btn" type="button" style="padding:6px 14px; font-weight:600; background:#1f4e79; color:#fff; border:none; border-radius:4px; cursor:pointer;">Look up</button>
      <button id="mbv_clear_btn" type="button" style="padding:6px 10px; background:#eee; border:1px solid #ccc; border-radius:4px; cursor:pointer;">Clear</button>
    </div>
    <div id="mbv_lookup_result" style="margin-top:10px; font-size:13px; min-height:18px;"></div>
  </div>

  <div id="mbv_table_container" style="margin-top:12px;"></div>
  <div style="margin-top:10px; font-size: 12px; color: #666;">
    Structure values are <b>TVD from ground surface in feet</b> (positive; deeper = larger). Isopach values are <b>true vertical thickness in feet</b>.
    Source: EIA Midland Basin shale-play structure &amp; isopach map series, with subsea elevations shifted by SRTM 1 arc-second ground elevation. Cells outside the data convex hull display "outside coverage".
  </div>
</div>
"""
    html = html.replace("</body>", panel_html + "</body>")
    output_path.write_text(html, encoding="utf-8")


def _click_handler_js(embed: dict) -> str:
    payload = json.dumps(embed)
    return f"""
const MBV_DATA = {payload};

function mbv_bilinear(surf, lat, lon) {{
  const lats = surf.lats, lons = surf.lons, vals = surf.values;
  if (lat < lats[0] || lat > lats[lats.length-1]) return null;
  if (lon < lons[0] || lon > lons[lons.length-1]) return null;
  let iy = 0;
  for (let i = 0; i < lats.length - 1; i++) {{
    if (lats[i] <= lat && lat <= lats[i+1]) {{ iy = i; break; }}
  }}
  let ix = 0;
  for (let j = 0; j < lons.length - 1; j++) {{
    if (lons[j] <= lon && lon <= lons[j+1]) {{ ix = j; break; }}
  }}
  const fy = (lat - lats[iy]) / (lats[iy+1] - lats[iy]);
  const fx = (lon - lons[ix]) / (lons[ix+1] - lons[ix]);
  const v00 = vals[iy][ix], v01 = vals[iy][ix+1], v10 = vals[iy+1][ix], v11 = vals[iy+1][ix+1];
  if (v00 === null || v01 === null || v10 === null || v11 === null) return null;
  return (1-fy)*((1-fx)*v00 + fx*v01) + fy*((1-fx)*v10 + fx*v11);
}}

// Find which formation interval contains a target depth (positive ft below sea level).
// Depths increase downward, so shallow formations have small tops and deep
// ones have large tops.
function mbv_find_formation_at_depth(lat, lon, depth) {{
  const intervals = [];
  for (const f of MBV_DATA.formations) {{
    const surf = MBV_DATA.surfaces[f.structure_key];
    if (!surf) continue;
    const top = mbv_bilinear(surf, lat, lon);
    if (top === null || !isFinite(top)) continue;
    let thickness = null;
    const isoSurf = MBV_DATA.surfaces[f.isopach_key];
    if (isoSurf) {{
      const t = mbv_bilinear(isoSurf, lat, lon);
      if (t !== null && isFinite(t)) thickness = t;
    }}
    intervals.push({{name: f.name, top: top, thickness: thickness}});
  }}
  if (intervals.length === 0) return {{outside: true}};
  // Sort shallow -> deep (smallest depth first)
  intervals.sort((a, b) => a.top - b.top);

  if (depth < intervals[0].top) {{
    return {{above_shallowest: true, name: intervals[0].name, top: intervals[0].top}};
  }}
  for (let i = 0; i < intervals.length; i++) {{
    const cur = intervals[i];
    const nextTop = (i + 1 < intervals.length) ? intervals[i+1].top : null;
    let base = nextTop;
    if (base === null && cur.thickness !== null) base = cur.top + cur.thickness;
    if (depth >= cur.top && (base === null || depth < base)) {{
      return {{
        in_formation: true,
        name: cur.name, top: cur.top, base: base,
        depth_into: depth - cur.top,
      }};
    }}
  }}
  const last = intervals[intervals.length - 1];
  const lastBase = (last.thickness !== null) ? last.top + last.thickness : null;
  return {{below_deepest: true, name: last.name, top: last.top, base: lastBase}};
}}

function mbv_update_pick_marker(lat, lon) {{
  const idx = MBV_DATA.pick_trace_indices;
  if (!idx || idx.length !== 2) return;
  Plotly.restyle('mbv_plot', {{x: [[lon], [lon]], y: [[lat], [lat]]}}, idx);
}}

function mbv_update_cursor_readout(lat, lon, kind) {{
  const loc = document.getElementById('mbv_click_loc');
  if (!loc) return;
  const tag = (kind === 'hover') ? '<span style="color:#888;">[hover]</span>' : '<span style="color:#1f4e79;">[picked]</span>';
  loc.innerHTML = tag + ' <b>Lat:</b> ' + lat.toFixed(4) + '&nbsp;&nbsp;<b>Lon:</b> ' + lon.toFixed(4);
}}

function mbv_render_table(lat, lon) {{
  mbv_update_pick_marker(lat, lon);
  mbv_update_cursor_readout(lat, lon, 'pick');
  const rows = ['<tr><th style="text-align:left;padding:4px 12px;border-bottom:1px solid #ccc;">Formation</th>' +
                '<th style="text-align:right;padding:4px 12px;border-bottom:1px solid #ccc;">TVD from surface (ft)</th>' +
                '<th style="text-align:right;padding:4px 12px;border-bottom:1px solid #ccc;">Thickness (ft)</th></tr>'];
  for (const f of MBV_DATA.formations) {{
    const sSurf = MBV_DATA.surfaces[f.structure_key];
    const iSurf = MBV_DATA.surfaces[f.isopach_key];
    const s = sSurf ? mbv_bilinear(sSurf, lat, lon) : null;
    const i = iSurf ? mbv_bilinear(iSurf, lat, lon) : null;
    const fmt = v => (v === null || !isFinite(v))
      ? '<span style="color:#999;">outside coverage</span>'
      : v.toLocaleString(undefined, {{maximumFractionDigits: 0}});
    rows.push('<tr>' +
      '<td style="padding:3px 12px;">' + f.name + '</td>' +
      '<td style="text-align:right;padding:3px 12px; font-variant-numeric: tabular-nums;">' + fmt(s) + '</td>' +
      '<td style="text-align:right;padding:3px 12px; font-variant-numeric: tabular-nums;">' + fmt(i) + '</td>' +
    '</tr>');
  }}
  document.getElementById('mbv_table_container').innerHTML =
    '<table style="border-collapse: collapse; width: 100%; font-size: 13px;">' + rows.join('') + '</table>';
}}

function mbv_lookup_submit() {{
  const result = document.getElementById('mbv_lookup_result');
  result.innerHTML = '';
  const latStr = document.getElementById('mbv_in_lat').value;
  const lonStr = document.getElementById('mbv_in_lon').value;
  const depthStr = document.getElementById('mbv_in_depth').value;

  const lat = parseFloat(latStr);
  const lon = parseFloat(lonStr);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {{
    result.innerHTML = '<span style="color:#c00;">Lat and Lon must be numbers (decimal degrees).</span>';
    return;
  }}
  mbv_render_table(lat, lon);

  if (depthStr !== '') {{
    const depth = parseFloat(depthStr);
    if (!Number.isFinite(depth)) {{
      result.innerHTML = '<span style="color:#c00;">Depth must be a number.</span>';
      return;
    }}
    const found = mbv_find_formation_at_depth(lat, lon, depth);
    let msg = '';
    if (found.outside) {{
      msg = '<span style="color:#c00;">No formation tops mapped at this location (outside coverage).</span>';
    }} else if (found.above_shallowest) {{
      msg = '<b>' + depth.toLocaleString() + ' ft</b> is <b>above</b> the shallowest mapped top (' +
            found.name + ' top is at <b>' + found.top.toFixed(0) + ' ft</b>).';
    }} else if (found.below_deepest) {{
      msg = '<b>' + depth.toLocaleString() + ' ft</b> is <b>below</b> the deepest mapped top (' +
            found.name + ' top at ' + found.top.toFixed(0) + ' ft';
      if (found.base !== null) msg += ', base ~' + found.base.toFixed(0) + ' ft';
      msg += '). May be in or below ' + found.name + '.';
    }} else {{
      msg = 'At <b>' + depth.toLocaleString() + ' ft</b> you are in <b style="color:#1f4e79;">' + found.name + '</b>';
      msg += ' (top ' + found.top.toFixed(0) + ' ft';
      if (found.base !== null) msg += ', base ~' + found.base.toFixed(0) + ' ft';
      msg += '; ' + found.depth_into.toFixed(0) + ' ft below the top).';
    }}
    result.innerHTML = msg;
  }}
}}

function mbv_lookup_clear() {{
  ['mbv_in_lat','mbv_in_lon','mbv_in_depth'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.value = '';
  }});
  const r = document.getElementById('mbv_lookup_result');
  if (r) r.innerHTML = '';
}}

function mbv_setup() {{
  const plot = document.getElementById('mbv_plot');
  if (plot && !plot.__mbv_clicked_wired) {{
    plot.__mbv_clicked_wired = true;
    plot.on('plotly_click', function(ev) {{
      if (!ev || !ev.points || !ev.points.length) return;
      const p = ev.points[0];
      const lat = p.y, lon = p.x;
      if (typeof lat !== 'number' || typeof lon !== 'number') return;
      mbv_render_table(lat, lon);
      const r = document.getElementById('mbv_lookup_result');
      if (r) r.innerHTML = '';
    }});
    plot.on('plotly_hover', function(ev) {{
      if (!ev || !ev.points || !ev.points.length) return;
      const p = ev.points[0];
      const lat = p.y, lon = p.x;
      if (typeof lat !== 'number' || typeof lon !== 'number') return;
      const traceType = p.fullData && p.fullData.type;
      if (traceType !== 'contour') return;
      mbv_update_cursor_readout(lat, lon, 'hover');
    }});
  }}
  const btn = document.getElementById('mbv_lookup_btn');
  if (!btn) return false;
  if (btn.__mbv_wired) return true;
  btn.__mbv_wired = true;
  btn.addEventListener('click', mbv_lookup_submit);
  const clr = document.getElementById('mbv_clear_btn');
  if (clr) clr.addEventListener('click', mbv_lookup_clear);
  ['mbv_in_lat','mbv_in_lon','mbv_in_depth'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => {{ if (e.key === 'Enter') mbv_lookup_submit(); }});
  }});
  return true;
}}

if (!mbv_setup()) {{
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', mbv_setup);
  }} else {{
    setTimeout(mbv_setup, 0);
    setTimeout(mbv_setup, 100);
  }}
}}
"""
