"""Build real toolpath geometry from sliced G-code.

Shading a CAD shell can only ever approximate a print. This builds the actual
extrusion paths as geometry, so the layer stepping, the seams, the contour
rings on top surfaces and the scalloped silhouette are all real shape -- and
the material is then just plastic, with the geometry doing the lighting.

Only the visible features are built. Internal perimeters are more than a third
of the moves and are never seen, so they are dropped; keeping them costs
memory and buys nothing.

    slice:  PrusaSlicer --export-gcode --layer-height=0.28 ... model.stl
    build:  paths = parse(gcode); build_curves(paths, ...)
"""

import math

import bpy

MM = 0.001

#: Feature types to build. PrusaSlicer emits these as ;TYPE: comments.
#:
#: Internal perimeters and solid infill are included even though they are
#: never directly seen: a wall built from its external perimeter alone is one
#: bead thick with gaps between beads, so the camera looks straight through it
#: into the bin. They are also cheap -- the whole part is about 2.4M verts.
VISIBLE = {
    "External perimeter",
    "Perimeter",
    "Overhang perimeter",
    "Solid infill",
    "Top solid infill",
    "Bridge infill",
}


def parse(path, visible=None, min_seg=0.0):
    """Return [(feature, [(x, y, z), ...]), ...] in millimetres.

    A run breaks whenever the extruder stops (a travel move), the feature type
    changes, or the layer changes, which is what keeps each polyline a single
    continuous bead.
    """
    visible = VISIBLE if visible is None else visible
    runs = []
    cur_type = None
    run = []
    x = y = z = 0.0
    last_e = 0.0
    relative_e = False

    for line in open(path):
        if line.startswith(";TYPE:"):
            if len(run) > 1:
                runs.append((cur_type, run))
            run = []
            cur_type = line.strip()[6:]
            continue
        if line.startswith("M83"):
            relative_e = True
            continue
        if line.startswith("M82"):
            relative_e = False
            continue

        if not (line.startswith("G1 ") or line.startswith("G0 ")):
            continue

        nx, ny, nz, ne = x, y, z, None
        for token in line.split():
            c = token[0]
            try:
                v = float(token[1:])
            except ValueError:
                continue
            if c == "X":
                nx = v
            elif c == "Y":
                ny = v
            elif c == "Z":
                nz = v
            elif c == "E":
                ne = v

        extruding = False
        if ne is not None:
            extruding = ne > 0.0 if relative_e else ne > last_e
            last_e = ne if not relative_e else last_e

        moved = (nx != x or ny != y)
        if extruding and moved and cur_type in visible:
            if not run:
                run.append((x, y, nz))
            run.append((nx, ny, nz))
        else:
            # Travel, retraction or a Z hop ends the bead.
            if len(run) > 1:
                runs.append((cur_type, run))
            run = []

        x, y, z = nx, ny, nz

    if len(run) > 1:
        runs.append((cur_type, run))
    return runs


def bead_profile(name, width=0.45, height=0.28, segments=16):
    """Cross-section of a deposited bead: a squashed round, not a circle.

    The nozzle lays a round bead and the layer above squashes it against the
    one below, so the section is roughly an ellipse wider than it is tall.
    """
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    spline = curve.splines.new("POLY")
    spline.points.add(segments - 1)
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        spline.points[i].co = (
            math.cos(a) * width / 2 * MM,
            math.sin(a) * height / 2 * MM,
            0.0,
            1.0,
        )
    spline.use_cyclic_u = True
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.hide_render = True
    return obj


def build_curves(runs, name="toolpaths", width=0.45, height=0.28,
                 origin=(0.0, 0.0, 0.0), resolution=1):
    """One curve object holding every visible bead as a spline.

    Splines share a single object and a single bevel profile, so this stays
    one datablock rather than tens of thousands of objects.
    """
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = resolution
    curve.bevel_mode = "OBJECT"
    curve.bevel_object = bead_profile(name + "_profile", width, height)
    curve.use_fill_caps = True

    ox, oy, oz = origin
    for _feature, pts in runs:
        spline = curve.splines.new("POLY")
        spline.points.add(len(pts) - 1)
        for i, (px, py, pz) in enumerate(pts):
            spline.points[i].co = ((px - ox) * MM, (py - oy) * MM,
                                   (pz - oz) * MM, 1.0)

    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    return obj


def bounds(runs):
    xs = [p[0] for _f, pts in runs for p in pts]
    ys = [p[1] for _f, pts in runs for p in pts]
    zs = [p[2] for _f, pts in runs for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
