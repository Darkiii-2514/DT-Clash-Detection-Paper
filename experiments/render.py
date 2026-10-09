"""Static 3D snapshots of a clash (structural member, MEP element, intersection region,
nearby structure) for the expert survey and the paper's example figures."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
STRUCT, MEP, CONTEXT, HIT = "#9c9a92", "#2a78d6", "#d9d8d2", "#e34948"


def _add_mesh(ax, mesh, color, alpha, lw=0.0, max_faces=6000):
    f = mesh.faces
    if len(f) > max_faces:                       # keep renders light for very dense families
        f = f[np.linspace(0, len(f) - 1, max_faces).astype(int)]
    pc = Poly3DCollection(mesh.vertices[f], facecolor=color, edgecolor=color if lw else "none",
                          linewidths=lw, alpha=alpha)
    ax.add_collection3d(pc)


def _box_equal(ax, lo, hi):
    c, r = (lo + hi) / 2, max(hi - lo) / 2
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))


def render_clash(model, s_uid, m_uid, point, path, context_radius=2.0, title=None, dpi=200):
    s, m = model.by_uid[s_uid], model.by_uid[m_uid]
    p = np.asarray(point, float)
    lo = p - context_radius
    hi = p + context_radius
    ctx = [e for e in model.structural
           if e.uid != s.uid and np.all(e.bbox[:3] <= hi) and np.all(e.bbox[3:] >= lo)][:25]
    fig = plt.figure(figsize=(7.2, 3.6))
    views = [("Isometric", 22, -55), ("View along member", 0,
                                       float(np.degrees(np.arctan2(s.frame.u[1], s.frame.u[0]))))]
    for k, (name, elev, azim) in enumerate(views):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        for e in ctx:
            _add_mesh(ax, e.mesh, CONTEXT, 0.25)
        _add_mesh(ax, s.mesh, STRUCT, 0.45)
        _add_mesh(ax, m.mesh, MEP, 0.85)
        ax.scatter([p[0]], [p[1]], [p[2]], s=40, c=HIT, depthshade=False, edgecolors="white", linewidths=1.0)
        _box_equal(ax, lo, hi)
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(name, fontsize=8, color=MUTED, pad=0)
        ax.tick_params(labelsize=5, colors=MUTED, pad=0)
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.pane.fill = False
            axis.pane.set_edgecolor(GRID)
        ax.set_xlabel("x (m)", fontsize=6, color=MUTED, labelpad=-8)
        ax.set_ylabel("y (m)", fontsize=6, color=MUTED, labelpad=-8)
        ax.set_zlabel("z (m)", fontsize=6, color=MUTED, labelpad=-8)
    if title:
        fig.suptitle(title, fontsize=8, color=INK, x=0.02, ha="left")
    handles = [plt.Line2D([], [], marker="s", ls="", color=STRUCT, label="structural member"),
               plt.Line2D([], [], marker="s", ls="", color=MEP, label="MEP element"),
               plt.Line2D([], [], marker="s", ls="", color=CONTEXT, label="nearby structure"),
               plt.Line2D([], [], marker="o", ls="", color=HIT, label="clash centroid")]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=7, frameon=False)
    fig.subplots_adjust(left=0.0, right=1.0, top=0.9, bottom=0.1, wspace=0.0)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
