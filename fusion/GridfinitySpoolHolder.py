"""Gridfinity sewing thread spool holder -- Fusion 360 script.

Run it from Utilities > Scripts and Add-Ins. It opens a dialog with the
parameters, so nothing is built and nothing is deleted until you press OK.

The dialog is seeded from the design's user parameters if they exist, and
from the defaults below otherwise. Pressing OK writes your values back to the
design, so the two stay in step.

Rebuilding is how a parameter is applied: the unit counts and the spool
spacing change how many feet and pegs exist, and a parameter cannot add or
remove bodies. Re-running is safe and repeatable -- the script clears the
previous build first.

All gridfinity constants were measured off a known-good bin rather than
recalled. See the repo README for the measurements.
"""

import math
import traceback

import adsk.core
import adsk.fusion

# ---------------------------------------------------------------------------
# Defaults. These seed the dialog the first time; after that the design's
# user parameters win.
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

ASK_BEFORE_RUN = True   # False builds immediately, for scripted use

# ---------------------------------------------------------------------------
# Gridfinity constants (measured, do not tune)
# ---------------------------------------------------------------------------

PITCH = 42.0
GAP = 0.5
TOP_INSET = GAP / 2                        # 0.25
BASE_C1, BASE_STR, BASE_C2 = 0.8, 1.8, 2.15
BASE_H = BASE_C1 + BASE_STR + BASE_C2      # 4.75
BOT_INSET = TOP_INSET + BASE_C1 + BASE_C2  # 3.20
R_TOP = 3.75
UNIT_Z = 7.0

LIP_C1, LIP_STR, LIP_C2 = 0.7, 1.8, 1.9
LIP_H = LIP_C1 + LIP_STR + LIP_C2          # 4.40
LIP_W = LIP_C1 + LIP_C2                    # 2.60

MM = 0.1    # Fusion's API works in centimetres

BODY_PREFIX = 'Gridfinity Spool Holder'
CMD_ID = 'GridfinitySpoolHolderCmd'

_handlers = []      # module level, or Fusion garbage collects the handlers


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
LIP_TIP = base_inset(LIP_H) - TOP_INSET    # 0.35


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


def all_profiles(sk):
    """Every closed region in a sketch, as one collection.

    Extruding a collection is one feature. Extruding the profiles one at a
    time is one feature each, which is what made this script produce 165
    timeline entries for a part that needs about a dozen.
    """
    coll = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        coll.add(sk.profiles.item(i))
    return coll


def extrude(root, profiles, dist, op, taper_deg=0.0, participants=None):
    """Extrude a profile or collection upward by dist mm, optionally tapered."""
    feats = root.features.extrudeFeatures
    ein = feats.createInput(profiles, op)
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
    if span_x < 0 or span_y < 0:
        return []

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
# Parameters
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


def read_parameters(des):
    """Adopt any parameters already in the design.

    Parameter.value is always in internal units, so a length comes back in
    centimetres no matter what the document displays. Getting that conversion
    wrong silently shrinks everything by a factor of ten.
    """
    g = globals()
    for name, var, unit, _ in PARAM_SPEC:
        p = des.userParameters.itemByName(name)
        if not p:
            continue
        value = p.value / MM if unit == 'mm' else p.value
        g[var] = int(round(value)) if unit == '' else value


def write_parameters(des):
    g = globals()
    for name, var, unit, comment in PARAM_SPEC:
        expr = ('%g %s' % (g[var], unit)).strip()
        p = des.userParameters.itemByName(name)
        if p:
            p.expression = expr
        else:
            des.userParameters.add(
                name, adsk.core.ValueInput.createByString(expr), unit, comment)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def reset_design(root):
    """Delete the previous build so re-running is idempotent.

    Deleting the features is the part that matters. Deleting the sketches and
    planes does NOT cascade to the features that consumed them, and calling
    deleteMe() on a body returns True while leaving the body in place -- so
    clearing anything else first looks like it worked and silently leaves the
    old bin behind, renamed to Body2 and sitting inside the new one.

    Features must go newest first, since each depends on the ones before it.
    User parameters are not features and survive, which is what lets the next
    run read the values you edited.
    """
    foreign = [b.name for b in root.bRepBodies if not b.name.startswith(BODY_PREFIX)]
    if foreign:
        raise RuntimeError(
            'This document contains geometry the script did not create (%s). '
            'Run it in a new document instead of losing that work.'
            % ', '.join(foreign[:3]))

    for _ in range(5):
        if not root.features.count:
            break
        feats = root.features
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
    """One gridfinity foot, then a rectangular pattern across the grid.

    Three extrusions and one pattern, rather than three extrusions per cell.
    """
    new_body = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation

    cx = -(GRID_X - 1) / 2.0 * PITCH
    cy = -(GRID_Y - 1) / 2.0 * PITCH

    sk = sketch_at(root, 0.0)
    size = PITCH - 2 * BOT_INSET
    rounded_rect(sk, cx, cy, size, size, radius_for(BOT_INSET))
    foot = extrude(root, sk.profiles.item(0), BASE_C1, new_body, 45.0).bodies.item(0)

    mid = PITCH - 2 * (BOT_INSET - BASE_C1)
    mid_r = radius_for(BOT_INSET - BASE_C1)

    sk = sketch_at(root, BASE_C1)
    rounded_rect(sk, cx, cy, mid, mid, mid_r)
    extrude(root, sk.profiles.item(0), BASE_STR, join, 0.0, [foot])

    sk = sketch_at(root, BASE_C1 + BASE_STR)
    rounded_rect(sk, cx, cy, mid, mid, mid_r)
    extrude(root, sk.profiles.item(0), BASE_C2, join, 45.0, [foot])

    if GRID_X == 1 and GRID_Y == 1:
        return [foot]

    coll = adsk.core.ObjectCollection.create()
    coll.add(foot)
    pats = root.features.rectangularPatternFeatures
    pin = pats.createInput(
        coll, root.xConstructionAxis,
        adsk.core.ValueInput.createByReal(GRID_X),
        adsk.core.ValueInput.createByReal(PITCH * MM),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pin.setDirectionTwo(root.yConstructionAxis,
                        adsk.core.ValueInput.createByReal(GRID_Y),
                        adsk.core.ValueInput.createByReal(PITCH * MM))
    pat = pats.add(pin)

    feet = [foot]
    for b in pat.bodies:
        feet.append(b)
    return feet


def build_shell(root, feet):
    """Outer body from the top of the base up, joined onto the feet."""
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    sk = sketch_at(root, BASE_H)
    rounded_rect(sk, 0, 0, outer(GRID_X), outer(GRID_Y), R_TOP)
    return extrude(root, sk.profiles.item(0), total_height() - BASE_H,
                   join, 0.0, feet).bodies.item(0)


def cut_cavity(root, body):
    """Interior cavity.

    It has to stop at the bottom of the lip. The wall is thinner than the lip
    ledge inset, so a full height cavity cuts straight through and silently
    erases the lip.
    """
    cut = adsk.fusion.FeatureOperations.CutFeatureOperation
    floor_z = BASE_H + FLOOR
    cavity_top = total_height() - (LIP_H if STACKING_LIP else 0.0)
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

    sk = sketch_at(root, h - LIP_H)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_W, fy - 2 * LIP_W, max(0.1, R_TOP - LIP_W))
    extrude(root, sk.profiles.item(0), LIP_C2, cut, 45.0, [body])

    sk = sketch_at(root, h - LIP_C1 - LIP_STR)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_C1, fy - 2 * LIP_C1, max(0.1, R_TOP - LIP_C1))
    extrude(root, sk.profiles.item(0), LIP_STR, cut, 0.0, [body])

    taper = math.degrees(math.atan((LIP_C1 - LIP_TIP) / LIP_C1))
    sk = sketch_at(root, h - LIP_C1)
    rounded_rect(sk, 0, 0, fx - 2 * LIP_C1, fy - 2 * LIP_C1, max(0.1, R_TOP - LIP_C1))
    extrude(root, sk.profiles.item(0), LIP_C1, cut, taper, [body])


def build_pegs(root, body):
    """All pegs in two extrusions: one shaft, one tapered lead-in.

    Every peg circle lives in a single sketch and the whole collection of
    profiles goes into one extrude feature.
    """
    join = adsk.fusion.FeatureOperations.JoinFeatureOperation
    floor_z = BASE_H + FLOOR
    pts = peg_positions()
    if not pts:
        return 0
    shaft = PEG_HEIGHT - PEG_CHAMFER

    sk = sketch_at(root, floor_z)
    for x, y in pts:
        sk.sketchCurves.sketchCircles.addByCenterRadius(_pt(x, y), PEG_DIA / 2.0 * MM)
    extrude(root, all_profiles(sk), shaft, join, 0.0, [body])

    sk = sketch_at(root, floor_z + shaft)
    for x, y in pts:
        sk.sketchCurves.sketchCircles.addByCenterRadius(_pt(x, y), PEG_DIA / 2.0 * MM)
    extrude(root, all_profiles(sk), PEG_CHAMFER, join, -45.0, [body])

    return len(pts)


def build(des):
    """Clear the previous build and generate the bin. Returns a summary."""
    root = des.rootComponent
    reset_design(root)

    feet = build_feet(root)
    body = build_shell(root, feet)
    cut_cavity(root, body)
    cut_lip(root, body)
    n = build_pegs(root, body)

    body.name = '%s %dx%dx%du' % (BODY_PREFIX, GRID_X, GRID_Y, GRID_Z)
    bb = body.boundingBox

    lines = [
        'grid: %d x %d x %du' % (GRID_X, GRID_Y, GRID_Z),
        'pegs: %d' % n,
        'size: %.2f x %.2f x %.2f mm' % (
            (bb.maxPoint.x - bb.minPoint.x) / MM,
            (bb.maxPoint.y - bb.minPoint.y) / MM,
            (bb.maxPoint.z - bb.minPoint.z) / MM),
        'stack pitch: %.2f mm' % (total_height() - LIP_H),
        'features: %d' % root.features.count,
    ]

    # A short bin still builds, it just cannot stack: the pegs stand proud of
    # the rim and foul whatever sits on top. Worth saying out loud, because
    # the geometry looks fine on screen.
    rim = total_height() - (LIP_H if STACKING_LIP else 0.0)
    tip = BASE_H + FLOOR + PEG_HEIGHT
    if tip > rim:
        need = int(math.ceil(tip / UNIT_Z))
        lines.append('')
        lines.append('WARNING: pegs end at %.1fmm but the rim is at %.1fmm, so '
                     'they stand %.1fmm proud.' % (tip, rim, tip - rim))
        lines.append('This bin will not stack. Raise the height to %d units, '
                     'or drop the peg height to %.1fmm.'
                     % (need, rim - BASE_H - FLOOR))
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        app = adsk.core.Application.get()
        ui = app.userInterface
        try:
            des = adsk.fusion.Design.cast(app.activeProduct)
            inputs = args.command.commandInputs
            g = globals()
            g['GRID_X'] = inputs.itemById('gx').value
            g['GRID_Y'] = inputs.itemById('gy').value
            g['GRID_Z'] = inputs.itemById('gz').value
            g['SPOOL_SPACING'] = inputs.itemById('spacing').value / MM
            g['PEG_HEIGHT'] = inputs.itemById('peg_h').value / MM
            g['PEG_DIA'] = inputs.itemById('peg_d').value / MM
            g['WALL'] = inputs.itemById('wall').value / MM
            g['FLOOR'] = inputs.itemById('floor').value / MM
            g['STACKING_LIP'] = inputs.itemById('lip').value

            write_parameters(des)
            ui.messageBox(build(des), 'Gridfinity Spool Holder')
        except Exception:
            ui.messageBox('Failed:\n%s' % traceback.format_exc(),
                          'Gridfinity Spool Holder')


class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        cmd.isExecutedWhenPreEmpted = False
        inputs = cmd.commandInputs

        inputs.addTextBoxCommandInput(
            'note', '',
            'Builds the bin from scratch. Any previous build in this '
            'document is deleted first.', 3, True)

        inputs.addIntegerSpinnerCommandInput('gx', 'Width (units)', 1, 20, 1, GRID_X)
        inputs.addIntegerSpinnerCommandInput('gy', 'Depth (units)', 1, 20, 1, GRID_Y)
        inputs.addIntegerSpinnerCommandInput('gz', 'Height (units)', 2, 30, 1, GRID_Z)

        def val(vid, name, mm):
            inputs.addValueInput(vid, name, 'mm',
                                 adsk.core.ValueInput.createByReal(mm * MM))

        val('spacing', 'Spool spacing', SPOOL_SPACING)
        val('peg_h', 'Peg height', PEG_HEIGHT)
        val('peg_d', 'Peg diameter', PEG_DIA)
        val('wall', 'Wall', WALL)
        val('floor', 'Floor', FLOOR)
        inputs.addBoolValueInput('lip', 'Stacking lip', True, '', STACKING_LIP)

        on_execute = _ExecuteHandler()
        cmd.execute.add(on_execute)
        _handlers.append(on_execute)


def run(_context: str):
    app = adsk.core.Application.get()
    ui = app.userInterface
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        raise RuntimeError('Open a Fusion design first.')

    # Must stay parametric: a direct design has no user parameters, and the
    # timeline is what lets you tweak the result after the script has run.
    des.designType = adsk.fusion.DesignTypes.ParametricDesignType
    read_parameters(des)

    if not ASK_BEFORE_RUN:
        write_parameters(des)
        print(build(des))
        return

    existing = ui.commandDefinitions.itemById(CMD_ID)
    if existing:
        existing.deleteMe()
    cmd_def = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'Gridfinity Spool Holder', 'Generate a gridfinity spool holder')

    on_created = _CreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)
    cmd_def.execute()

    # Keep the script alive while the dialog is open.
    adsk.autoTerminate(False)
