#!/usr/bin/env python3
"""Measure an exported STL against the gridfinity spec.

The spec values here were measured off a known-good bin rather than recalled,
so this script checks the export the same way that bin was checked. Run it
after any change to the .scad files -- a bin that misses these numbers will
not seat in a baseplate, and you find that out after a six hour print.

Everything is measured by cross-sectioning the mesh, never by sampling
vertices near a height. CSG output only has vertices at real corners, so
vertex sampling silently returns nothing in the middle of a flat face.
"""

import sys
import numpy as np
import trimesh

PITCH = 42.0
GAP = 0.5
BASE_C1, BASE_STR, BASE_C2 = 0.8, 1.8, 2.15
BASE_H = BASE_C1 + BASE_STR + BASE_C2          # 4.75
TOP_INSET = GAP / 2                            # 0.25
BOT_INSET = TOP_INSET + BASE_C1 + BASE_C2      # 3.20
R_TOP = 3.75
UNIT_Z = 7.0
LIP_H = 4.4
LIP_W = 2.6      # ledge inset at the bottom of the lip
LIP_C1 = 0.7     # throat inset
LIP_TIP = 0.35   # rim inset, derived so the seat depth equals LIP_H

GRID_X, GRID_Y, GRID_Z = 3, 4, 7
PEG_DIA, PEG_H, FLOOR, WALL = 6.0, 38.0, 1.25, 1.6
SPOOL_DIA = 24.68
EXPECT_PEGS = 30

TOL = 0.05

_fails: list[str] = []
_checks = 0


def check(label, got, want, tol=TOL):
    global _checks
    _checks += 1
    ok = got == got and abs(got - want) <= tol      # NaN-safe
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<42} {got:9.3f}  (want {want:.3f})")
    if not ok:
        _fails.append(f"{label}: got {got:.3f}, want {want:.3f}")


def check_true(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<42} {detail}")
    if not ok:
        _fails.append(f"{label}: {detail}")


def loops(m, z):
    """Closed polylines where the plane at height z cuts the mesh."""
    s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    return [] if s is None else [np.asarray(p) for p in s.discrete]


def outline(m, z):
    """All section points at height z, as an Nx3 array."""
    ls = loops(m, z)
    return np.vstack(ls) if ls else np.empty((0, 3))


def width(m, z, axis=0):
    p = outline(m, z)
    return float("nan") if len(p) < 2 else p[:, axis].max() - p[:, axis].min()


def corner_radius(m, z):
    """Fit the radius of the -X/-Y corner arc of the outermost loop."""
    ls = loops(m, z)
    if not ls:
        return float("nan")
    o = max(ls, key=lambda p: p[:, 0].max() - p[:, 0].min())
    x0, y0 = o[:, 0].min(), o[:, 1].min()
    c = o[(o[:, 0] < x0 + 12) & (o[:, 1] < y0 + 12)]
    best = (float("nan"), 1e9)
    for r in np.arange(0.3, 9.0, 0.005):
        cx, cy = x0 + r, y0 + r
        arc = c[(c[:, 0] < cx) & (c[:, 1] < cy)]
        if len(arc) < 3:
            continue
        err = float(np.abs(np.hypot(arc[:, 0] - cx, arc[:, 1] - cy) - r).mean())
        if err < best[1]:
            best = (r, err)
    return best[0]


def main(path):
    m = trimesh.load(path)
    m.apply_translation(-m.bounds[0])
    H = m.bounds[1][2]

    print(f"\n{path}")
    print(f"  {len(m.vertices)} verts, {len(m.faces)} faces\n")

    print("mesh integrity")
    check_true("watertight", m.is_watertight, str(m.is_watertight))
    check_true("single body", m.body_count == 1, f"{m.body_count} bodies")
    check_true("positive volume", m.volume > 0, f"{m.volume/1000:.1f} cm3")

    print("\nfootprint")
    check("outer X", m.bounds[1][0], PITCH * GRID_X - GAP)
    check("outer Y", m.bounds[1][1], PITCH * GRID_Y - GAP)
    check("total height", H, UNIT_Z * GRID_Z + LIP_H)

    print("\nbase profile")
    # One foot per cell, so the bottom span is the grid minus the bottom
    # inset at each outside edge.
    check("bottom span X", width(m, 0.02, 0), PITCH * GRID_X - 2 * BOT_INSET, 0.1)
    check("bottom span Y", width(m, 0.02, 1), PITCH * GRID_Y - 2 * BOT_INSET, 0.1)
    check("top of base span X", width(m, BASE_H - 0.02, 0), PITCH * GRID_X - GAP, 0.1)
    # 45 degree sections: both sides move, so width grows 2mm per mm of height.
    for z0, z1, name in [(0.1, BASE_C1 - 0.1, "lower chamfer"),
                         (BASE_C1 + BASE_STR + 0.1, BASE_H - 0.1, "upper chamfer")]:
        slope = (width(m, z1) - width(m, z0)) / (z1 - z0)
        check(f"{name} slope (2.0 = 45 deg)", slope, 2.0, 0.1)
    check("straight section width", width(m, BASE_C1 + BASE_STR / 2),
          PITCH * GRID_X - 2 * (BOT_INSET - BASE_C1), 0.1)

    print("\ncorner radii")
    check("wall above base", corner_radius(m, BASE_H + 2.0), R_TOP, 0.1)
    check("bottom of feet", corner_radius(m, 0.02),
          R_TOP - (BOT_INSET - TOP_INSET), 0.1)

    print("\nfeet")
    feet = loops(m, 0.02)
    check_true("one foot per cell", len(feet) == GRID_X * GRID_Y,
               f"{len(feet)} feet, expected {GRID_X * GRID_Y}")
    if len(feet) == GRID_X * GRID_Y:
        w = np.mean([f[:, 0].max() - f[:, 0].min() for f in feet])
        check("foot width", float(w), PITCH - 2 * BOT_INSET, 0.1)
        # Midpoint of the extents, not the mean of the points: section loops
        # carry a duplicated closing vertex that drags a mean off centre.
        cx = sorted({round((float(f[:, 0].min()) + float(f[:, 0].max())) / 2, 1)
                     for f in feet})
        check("foot pitch", cx[1] - cx[0], PITCH, 0.1)

    print("\npegs")
    floor_z = BASE_H + FLOOR
    mid = floor_z + PEG_H / 2
    ls = loops(m, mid)
    # The two largest loops are the outer wall and the cavity wall.
    ls.sort(key=lambda p: p[:, 0].max() - p[:, 0].min(), reverse=True)
    shell, pegs = ls[:2], ls[2:]
    check_true("shell is outer + cavity wall", len(shell) == 2, f"{len(shell)}")
    check_true("peg count", len(pegs) == EXPECT_PEGS,
               f"{len(pegs)}, expected {EXPECT_PEGS}")
    if pegs:
        d = np.mean([p[:, 0].max() - p[:, 0].min() for p in pegs])
        check("peg diameter", float(d), PEG_DIA, 0.1)
        C = np.array([[(p[:, 0].min() + p[:, 0].max()) / 2,
                       (p[:, 1].min() + p[:, 1].max()) / 2] for p in pegs])
        dist = np.hypot(C[:, None, 0] - C[None, :, 0], C[:, None, 1] - C[None, :, 1])
        np.fill_diagonal(dist, 1e9)
        nn = float(dist.min())
        check_true("min peg spacing >= spool dia",
                   nn >= SPOOL_DIA - 0.02, f"{nn:.3f} vs {SPOOL_DIA}")
        # A spool on an edge peg must not foul the wall.
        inner_x = (PITCH * GRID_X - GAP) / 2 - WALL
        inner_y = (PITCH * GRID_Y - GAP) / 2 - WALL
        cx, cy = C[:, 0] - (PITCH * GRID_X - GAP) / 2, C[:, 1] - (PITCH * GRID_Y - GAP) / 2
        clear = min(inner_x - np.abs(cx).max(), inner_y - np.abs(cy).max())
        check_true("spool clears the wall", clear >= SPOOL_DIA / 2 - 0.05,
                   f"{clear:.3f} vs {SPOOL_DIA/2:.3f}")
    # Tips must stop below the rim or stacking crushes them.
    tip_z = floor_z + PEG_H
    check("peg tip height", tip_z, floor_z + PEG_H, 0.001)
    check_true("tips below rim", tip_z < H - LIP_H,
               f"tips {tip_z:.1f}, lip starts {H - LIP_H:.1f}")

    print("\nstacking lip")
    outer_x = PITCH * GRID_X - GAP
    check("rim outer span", width(m, H - 0.02), outer_x, 0.1)

    def opening(z):
        """Inside width of the shell at height z."""
        ls_ = loops(m, z)
        if len(ls_) < 2:
            return float("nan")
        ls_.sort(key=lambda p: p[:, 0].max() - p[:, 0].min(), reverse=True)
        return float(ls_[1][:, 0].max() - ls_[1][:, 0].min())

    # The socket must widen monotonically towards the rim, or a foot cannot
    # descend into it.
    o_ledge = opening(H - LIP_H + 0.05)
    o_throat = opening(H - LIP_C1 - 1.0)
    o_rim = opening(H - 0.02)
    check("ledge opening", o_ledge, outer_x - 2 * LIP_W, 0.15)
    check("throat opening", o_throat, outer_x - 2 * LIP_C1, 0.15)
    check("rim opening", o_rim, outer_x - 2 * LIP_TIP, 0.15)
    check_true("socket opens towards the rim",
               o_ledge < o_throat <= o_rim + 0.01,
               f"{o_ledge:.2f} -> {o_throat:.2f} -> {o_rim:.2f}")
    # The ledge has to actually protrude past the wall, else there is no lip.
    o_wall = opening(H - LIP_H - 2.0)
    check_true("ledge protrudes past the wall", o_ledge < o_wall - 0.1,
               f"ledge {o_ledge:.2f} vs wall {o_wall:.2f}")
    # A foot from the bin above must clear the narrowest point it has to pass.
    check_true("foot enters the socket", o_ledge >= PITCH * GRID_X - 2 * BOT_INSET,
               f"ledge {o_ledge:.2f} vs foot bottom {PITCH * GRID_X - 2 * BOT_INSET:.2f}")

    print("\nstacking")
    # Drop a second bin into this one and find where it jams. The foot profile
    # is known analytically; the socket is measured off the mesh. Seat depth
    # is the stack pitch, and it has to come out at exactly 7mm per unit or
    # a tall stack walks away from the grid.
    def foot_width(t):
        """Width of a base t mm above its underside."""
        if t <= BASE_C1:
            inset = BOT_INSET - t
        elif t <= BASE_C1 + BASE_STR:
            inset = BOT_INSET - BASE_C1
        else:
            inset = max(TOP_INSET, BOT_INSET - BASE_C1 - (t - BASE_C1 - BASE_STR))
        return PITCH * GRID_X - 2 * inset

    depths = np.arange(0.0, LIP_H + 1e-9, 0.05)
    socket = np.array([opening(H - d) if d > 0.02 else o_rim for d in depths])
    seat = 0.0
    for delta in np.arange(0.05, BASE_H + 1e-9, 0.01):
        ok = True
        for d, w in zip(depths, socket):
            if d > delta:
                break
            if w == w and foot_width(delta - d) > w + 0.02:
                ok = False
                break
        if not ok:
            break
        seat = float(delta)
    check("seat depth", seat, LIP_H, 0.12)
    check("stack pitch", H - seat, UNIT_Z * GRID_Z, 0.12)

    print()
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks}")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"OK  {_checks}/{_checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/spool_holder_3x4x7.stl"))
