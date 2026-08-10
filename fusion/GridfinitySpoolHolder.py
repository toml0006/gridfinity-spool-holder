"""Gridfinity sewing thread spool holder -- Fusion 360 script.

Two ways to drive it, and they agree:

  * Edit the parameters below and run.
  * Edit them in Modify > Change Parameters and run the script again.

The design parameters win if they exist, so whichever you touch last is what
you get. Either way you must re-run: the script generates the geometry, so
changing a parameter alone does not rebuild the model.

That is a real limit, not an oversight. The unit counts and the spool spacing
change how many feet and pegs exist, and a parameter cannot add or remove
bodies -- only a rebuild can. Re-running is safe and repeatable: everything
is built inside a component that the script deletes and recreates each run,
so you never end up with two bins stacked on top of each other.

All gridfinity constants were measured off a known-good bin rather than
recalled. See the repo README for the measurements.
"""

import math

import adsk.core
import adsk.fusion

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

GRID_X = 3          # width, in gridfinity units (42mm each)
GRID_Y = 4          # depth, in gridfinity units
GRID_Z = 7          # height, in gridfinity units (7mm each)

SPOOL_SPACING = 24.68   # centre to centre; the widest spool flange that fits
PEG_DIA = 6.0           # spool bore is about 6.3
PEG_HEIGHT = 38.0       # proud of the floor
PEG_CHAMFER = 0.75      # lead-in at the tip

WALL = 1.6              # side wall thickness
FLOOR = 1.25            # floor above the top of the gridfinity base
STACKING_LIP = True     # False seats in a baseplate but will not stack

# ---------------------------------------------------------------------------
# Gridfinity constants (measured, do not tune)
# ---------------------------------------------------------------------------

PITCH = 42.0
GAP = 0.5
TOP_INSET = GAP / 2                       # 0.25
BASE_C1, BASE_STR, BASE_C2 = 0.8, 1.8, 2.15
BASE_H = BASE_C1 + BASE_STR + BASE_C2     # 4.75
BOT_INSET = TOP_INSET + BASE_C1 + BASE_C2  # 3.20
R_TOP = 3.75
UNIT_Z = 7.0

LIP_C1, LIP_STR, LIP_C2 = 0.7, 1.8, 1.9
LIP_H = LIP_C1 + LIP_STR + LIP_C2         # 4.40
LIP_W = LIP_C1 + LIP_C2                   # 2.60

MM = 0.1    # Fusion's API works in centimetres

BODY_PREFIX = 'Gridfinity Spool Holder'


def base_inset(t):
    """Inset per side of a gridfinity base, t mm above its underside."""
    if t <= BASE_C1:
        return BOT_INSET - t
    if t <= BASE_C1 + BASE_STR:
        return BOT_INSET - BASE_C1
    return max(TOP_INSET, BOT_INSET - BASE_C1 - (t - BASE_C1 - BASE_STR))


# The bin above sinks until its base flare jams on the rim, and that depth is
# the stack pitch. Seating at exactly LIP_H makes the pitch exactly UNIT_Z per
# height unit, which is what keeps a tall stack on the grid.
LIP_TIP = base_inset(LIP_H) - TOP_INSET   # 0.35


def outer(n):
    return PITCH * n - GAP


def total_height():
    return UNIT_Z * GRID_Z + (LIP_H if STACKING_LIP else 3.8)


def radius_for(inset):
    """Corner radius shrinks 1:1 with inset, so the base is one swept shape."""
    return max(0.01, R_TOP - (inset - TOP_INSET))


# ---------------------------------------------------------------------------
# Sketch helpers
# ---------------------------------------------------------------------------

def _pt(x, y):
    return adsk.core.Point3D.create(x * MM, y * MM, 0)


def rounded_rect(sk, cx, cy, w, h, r):
    """Draw a centred rounded rectangle. All arguments in mm."""
    lines = sk.sketchCurves.sketchLines
    arcs = sk.sketchCurves.sketchArcs
    x0, x1 = cx - w / 2.0, cx + w / 2.0
    y0, y1 = cy - h / 2.0, cy + h / 2.0

    if r <= 0.01:
        lines.addTwoPointRectangle(_pt(x0, y0), _pt(x1, y1))
        return

    l1 = lines.addByTwoPoints(_pt(x0 + r, y0), _pt(x1 - r, y0))
    l2 = lines.addByTwoPoints(_pt(x1, y0 + r), _pt(x1, y1 - r))
    l3 = lines.addByTwoPoints(_pt(x1 - r, y1), _pt(x0 + r, y1))
    l4 = lines.addByTwoPoints(_pt(x0, y1 - r), _pt(x0, y0 + r))

    quarter = math.pi / 2.0
    arcs.addByCenterStartSweep(_pt(x1 - r, y0 + r), l1.endSketchPoint.geometry, quarter)
    arcs.addByCenterStartSweep(_pt(x1 - r, y1 - r), l2.endSketchPoint.geometry, quarter)
    arcs.addByCenterStartSweep(_pt(x0 + r, y1 - r), l3.endSketchPoint.geometry, quarter)
    arcs.addByCenterStartSweep(_pt(x0 + r, y0 + r), l4.endSketchPoint.geometry, quarter)


def plane_at(root, z):
    """Construction plane parallel to XY, z mm up."""
    if abs(z) < 1e-9:
        return root.xYConstructionPlane
    planes = root.constructionPlanes
    pin = planes.createInput()
    pin.setByOffset(root.xYConstructionPlane,
                    adsk.core.ValueInput.createByReal(z * MM))
    return planes.add(pin)


def sketch_at(root, z):
    return root.sketches.add(plane_at(root, z))


def extrude(root, profile, dist, op, taper_deg=0.0, participants=None):
    """Extrude a profile upward by dist mm, optionally tapered."""
    feats = root.features.extrudeFeatures
    ein = feats.createInput(profile, op)
    extent = adsk.fusion.DistanceExtentDefinition.create(
        adsk.core.ValueInput.createByReal(dist * MM))
    ein.setOneSideExtent(extent,
                         adsk.fusion.ExtentDirections.PositiveExtentDirection,
                         adsk.core.ValueInput.createByString('%g deg' % taper_deg))
    if participants:
        ein.participantBodies = participants
    return feats.add(ein)


# ---------------------------------------------------------------------------
# Peg lattice
# ---------------------------------------------------------------------------

def peg_positions():
    """Hex packed, columns running along Y.

    The spacing is the only real constraint: it is the widest a spool flange
    can be. Columns along Y pack 30 into a 3x4; the other orientation packs 28.
    """
    col_spacing = SPOOL_SPACING * math.sqrt(3.0) / 2.0
    span_x = outer(GRID_X) - 2 * WALL - SPOOL_SPACING
    span_y = outer(GRID_Y) - 2 * WALL - SPOOL_SPACING

    pts = []
    n_cols = int(span_x / col_spacing) + 1
    for j in range(n_cols):
        off = SPOOL_SPACING / 2.0 if j % 2 else 0.0
        n = int((span_y - off) / SPOOL_SPACING) + 1
        for i in range(n):
            pts.append((j * col_spacing, off + i * SPOOL_SPACING))

    # Centre the pattern: offset columns end at a different Y than even ones,
    # so the generated block is not symmetric about its own origin.
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ox = (min(xs) + max(xs)) / 2.0
    oy = (min(ys) + max(ys)) / 2.0
    return [(x - ox, y - oy) for x, y in pts]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

#: name in the design, module global, unit, description
PARAM_SPEC = [
    ('gf_units_x', 'GRID_X', '', 'width in gridfinity units'),
    ('gf_units_y', 'GRID_Y', '', 'depth in gridfinity units'),
    ('gf_units_z', 'GRID_Z', '', 'height in gridfinity units'),
    ('spool_spacing', 'SPOOL_SPACING', 'mm', 'peg centre spacing'),
    ('peg_height', 'PEG_HEIGHT', 'mm', 'peg proud of floor'),
    ('peg_dia', 'PEG_DIA', 'mm', 'peg diameter'),
    ('wall', 'WALL', 'mm', 'side wall thickness'),
    ('floor_thickness', 'FLOOR', 'mm', 'floor above the base'),
]


def sync_parameters(des):
    """Design parameters win if present; otherwise seed them from this file.

    Parameter.value is always in internal units, so a length comes back in
    centimetres no matter what the document displays. Unitless counts come
    back as-is. Getting that conversion wrong silently shrinks everything by
    a factor of ten.
    """
    g = globals()
    adopted = []
    for name, var, unit, comment in PARAM_SPEC:
        existing = des.userParameters.itemByName(name)
        if existing:
            value = existing.value / MM if unit == 'mm' else existing.value
            if unit == '':
                value = int(round(value))
            if abs(value - g[var]) > 1e-9:
                adopted.append('%s %g -> %g' % (name, g[var], value))
            g[var] = value
        else:
            expr = ('%g %s' % (g[var], unit)).strip()
            des.userParameters.add(
                name, adsk.core.ValueInput.createByString(expr), unit, comment)
    return adopted


def reset_design(root):
    """Delete the previous build so re-running is idempotent.

    Deleting the features is the part that matters. Deleting the sketches and
    planes does NOT cascade to the features that consumed them, and calling
    deleteMe() on a body returns True while leaving the body in place -- so
    clearing anything else first looks like it worked and silently leaves the
    old bin behind, renamed to Body2 and sitting on top of the new one.

    Features must go newest first, since each depends on the ones before it.
    User parameters are not features and survive, which is what lets the next
    run read the values you edited.

    A Part Design document allows only one component, so the build cannot be
    isolated in its own component and dropped by deleting an occurrence.
    """
    foreign = [b.name for b in root.bRepBodies if not b.name.startswith(BODY_PREFIX)]
    if foreign:
        raise RuntimeError(
            'This document contains geometry the script did not create (%s). '
            'Run it in a new document instead of losing that work.'
            % ', '.join(foreign[:3]))

    for _ in range(5):
        feats = root.features
        if not feats.count:
            break
        for i in range(feats.count - 1, -1, -1):
            try:
                feats.item(i).deleteMe()
            except Exception:
                pass

    for sk in list(root.sketches):
        sk.deleteMe()
    for pl in list(root.constructionPlanes):
        pl.deleteMe()
    for body in list(root.bRepBodies):
        body.deleteMe()

    if root.bRepBodies.count:
        raise RuntimeError('Could not clear the previous build; %d bodies remain.'
                           % root.bRepBodies.count)


def build_feet(root):
    """One gridfinity foot per cell, arrayed on the grid."""
    new_body = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation

    feet = []
    for i in range(GRID_X):
        for j in range(GRID_Y):
            cx = (i - (GRID_X - 1) / 2.0) * PITCH
            cy = (j - (GRID_Y - 1) / 2.0) * PITCH

            # lower 45 chamfer
            sk = sketch_at(root, 0.0)
            size = PITCH - 2 * BOT_INSET
            rounded_rect(sk, cx, cy, size, size, radius_for(BOT_INSET))
            f = extrude(root, sk.profiles.item(0), BASE_C1, new_body, 45.0)
            body = f.bodies.item(0)

            # straight section
            sk = sketch_at(root, BASE_C1)
            size = PITCH - 2 * (BOT_INSET - BASE_C1)
            rounded_rect(sk, cx, cy, size, size, radius_for(BOT_INSET - BASE_C1))
            extrude(root, sk.profiles.item(0), BASE_STR, join, 0.0, [body])

            # upper 45 flare out to full width
            sk = sketch_at(root, BASE_C1 + BASE_STR)
            rounded_rect(sk, cx, cy, size, size, radius_for(BOT_INSET - BASE_C1))
            extrude(root, sk.profiles.item(0), BASE_C2, join, 45.0, [body])

            feet.append(body)
    return feet


def build_shell(root, feet):
    """Outer body from the top of the base up, joined onto the feet."""
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    h = total_height()
    sk = sketch_at(root, BASE_H)
    rounded_rect(sk, 0, 0, outer(GRID_X), outer(GRID_Y), R_TOP)
    f = extrude(root, sk.profiles.item(0), h - BASE_H, join, 0.0, feet)
    return f.bodies.item(0)


def cut_cavity(root, body):
    """Interior cavity.

    It has to stop at the bottom of the lip. The wall is thinner than the lip
    ledge inset, so a full height cavity cuts straight through and silently
    erases the lip.
    """
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation
    h = total_height()
    floor_z = BASE_H + FLOOR
    cavity_top = h - LIP_H if STACKING_LIP else h
    sk = sketch_at(root, floor_z)
    rounded_rect(sk, 0, 0,
                 outer(GRID_X) - 2 * WALL, outer(GRID_Y) - 2 * WALL,
                 max(0.1, R_TOP - WALL))
    extrude(root, sk.profiles.item(0), cavity_top - floor_z, cut, 0.0, [body])


def cut_lip(root, body):
    """Stacking lip: a funnel that opens towards the rim.

    Widest at the top so the feet of the bin above drop in, narrowing to an
    inward ledge at the bottom of the lip which is what takes the load. Build
    it the other way up and the cavity just swallows it.
    """
    if not STACKING_LIP:
        return
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation
    h = total_height()
    fx, fy = outer(GRID_X), outer(GRID_Y)

    # ledge, flaring out to the throat
    sk = sketch_at(root, h - LIP_H)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_W, fy - 2 * LIP_W,
                 max(0.1, R_TOP - LIP_W))
    extrude(root, sk.profiles.item(0), LIP_C2, cut, 45.0, [body])

    # vertical throat
    sk = sketch_at(root, h - LIP_C1 - LIP_STR)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_C1, fy - 2 * LIP_C1,
                 max(0.1, R_TOP - LIP_C1))
    extrude(root, sk.profiles.item(0), LIP_STR, cut, 0.0, [body])

    # final flare to the rim
    taper = math.degrees(math.atan((LIP_C1 - LIP_TIP) / LIP_C1))
    sk = sketch_at(root, h - LIP_C1)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_C1, fy - 2 * LIP_C1,
                 max(0.1, R_TOP - LIP_C1))
    extrude(root, sk.profiles.item(0), LIP_C1, cut, taper, [body])


def build_pegs(root, body):
    """Pegs, as a straight shaft plus a tapered lead-in at the tip."""
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    floor_z = BASE_H + FLOOR
    pts = peg_positions()
    shaft = PEG_HEIGHT - PEG_CHAMFER

    sk = sketch_at(root, floor_z)
    circles = sk.sketchCurves.sketchCircles
    for x, y in pts:
        circles.addByCenterRadius(_pt(x, y), PEG_DIA / 2.0 * MM)
    for i in range(sk.profiles.count):
        extrude(root, sk.profiles.item(i), shaft, join, 0.0, [body])

    sk = sketch_at(root, floor_z + shaft)
    circles = sk.sketchCurves.sketchCircles
    for x, y in pts:
        circles.addByCenterRadius(_pt(x, y), PEG_DIA / 2.0 * MM)
    for i in range(sk.profiles.count):
        extrude(root, sk.profiles.item(i), PEG_CHAMFER, join, -45.0, [body])

    return len(pts)


def run(_context: str):
    app = adsk.core.Application.get()
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        raise RuntimeError('Open a Fusion design first.')

    # Must stay parametric: a direct design has no user parameters, and the
    # timeline is what lets you tweak the result after the script has run.
    des.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = des.rootComponent

    adopted = sync_parameters(des)
    for line in adopted:
        print('adopted from design: %s' % line)

    reset_design(root)

    feet = build_feet(root)
    body = build_shell(root, feet)
    cut_cavity(root, body)
    cut_lip(root, body)
    n = build_pegs(root, body)

    body.name = '%s %dx%dx%du' % (BODY_PREFIX, GRID_X, GRID_Y, GRID_Z)
    bb = body.boundingBox
    print('grid: %d x %d x %du' % (GRID_X, GRID_Y, GRID_Z))
    print('pegs: %d' % n)
    print('bodies: %d' % root.bRepBodies.count)
    print('size: %.2f x %.2f x %.2f mm' % (
        (bb.maxPoint.x - bb.minPoint.x) / MM,
        (bb.maxPoint.y - bb.minPoint.y) / MM,
        (bb.maxPoint.z - bb.minPoint.z) / MM))
    print('stack pitch: %.2f mm' % (total_height() - LIP_H))

    # A short bin still builds, it just cannot stack: the pegs stand proud of
    # the rim and foul whatever sits on top. Worth saying out loud, because
    # the geometry looks fine on screen.
    rim = total_height() - (LIP_H if STACKING_LIP else 0.0)
    tip = BASE_H + FLOOR + PEG_HEIGHT
    if tip > rim:
        need = int(math.ceil((BASE_H + FLOOR + PEG_HEIGHT) / UNIT_Z))
        print('')
        print('WARNING: pegs end at %.1fmm but the rim is at %.1fmm, so they '
              'stand %.1fmm proud.' % (tip, rim, tip - rim))
        print('         This bin will not stack. Raise gf_units_z to %d, or '
              'drop peg_height to %.1fmm.' % (need, rim - BASE_H - FLOOR))
