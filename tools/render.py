"""Craft room renders of the spool holder, for a model listing.

    /Applications/Blender.app/Contents/MacOS/Blender -b --python tools/render.py
    /Applications/Blender.app/Contents/MacOS/Blender -b --python tools/render.py -- hero_loaded

Everything is built in real world units -- the bin is 125.5mm across, the mat
is 620mm, the window is a metre and a half of soft light -- so falloff, shadow
softness and depth of field come out of physical numbers.

Three things here are less obvious than they look:

* Anything resting on a surface is lifted CONTACT_LIFT above it. The bin's
  underside is at exactly z=0 and so is the table, and two coplanar faces
  z-fight: the renderer lets the table cut through the feet and the part
  reads as sunk into the ground.
* The filament shader textures top faces differently from walls. A print
  shows layer lines on its sides and extrusion beads on its top surfaces,
  and using one texture everywhere is most of what makes a render read as
  CAD rather than as a printed object.
* The spools are dirty. Clean procedural plastic reads as a product mockup;
  thread spools in a real craft room have dust in the flange corners and
  scuffs on the sides.
"""

import math
import os
import sys

import bpy
import bmesh
from mathutils import Vector

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STL = os.path.join(HERE, "out", "spool_holder_3x4x7.stl")
OUT = os.path.join(HERE, "renders")

MM = 0.001
RES = (2000, 1500)
SAMPLES = int(os.environ.get("RENDER_SAMPLES", "320"))

# Sub-visible, but enough to stop coplanar faces fighting.
CONTACT_LIFT = 0.00015

PITCH, GAP = 42.0, 0.5
GRID_X, GRID_Y, GRID_Z = 3, 4, 7
SPOOL_SPACING = 24.68
WALL = 1.6
BASE_H, FLOOR_T = 4.75, 1.25
PEG_HEIGHT = 38.0
UNIT_Z = 7.0
STACK_PITCH = UNIT_Z * GRID_Z          # 49.0, verified against the mesh

SP_H = 40.0
SP_FLANGE_D = 24.0
SP_FLANGE_T = 1.5
SP_CORE_D = 13.0
SP_BORE_D = 6.4
SP_THREAD_D = 23.4

FILAMENT = (0.052, 0.055, 0.062)       # matte dark grey PLA, linear
LAYER_H = 0.2                          # print layer height, mm
BEAD_W = 0.42                          # extrusion width on top surfaces, mm

MAT_TOP = 0.003                        # cutting mat thickness
REST = MAT_TOP + CONTACT_LIFT          # z for anything sitting on the mat

THREAD_COLOURS = [
    (0.55, 0.09, 0.10), (0.72, 0.32, 0.06), (0.78, 0.60, 0.12),
    (0.14, 0.32, 0.16), (0.09, 0.21, 0.40), (0.26, 0.13, 0.34),
    (0.66, 0.33, 0.44), (0.74, 0.71, 0.63), (0.07, 0.08, 0.09),
    (0.10, 0.42, 0.40), (0.48, 0.21, 0.10), (0.35, 0.46, 0.18),
    (0.80, 0.76, 0.66), (0.30, 0.10, 0.12), (0.18, 0.26, 0.45),
]


# --------------------------------------------------------------------------
# Scene helpers
# --------------------------------------------------------------------------

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.view_settings.view_transform = "AgX"
    # AgX rolls highlights off beautifully but desaturates hard, and the only
    # colour in frame is the thread. Punchy puts it back.
    scene.view_settings.look = "AgX - Punchy"

    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = "GPU"
    except Exception:
        scene.cycles.device = "CPU"

    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.16, 0.15, 0.14, 1)
    bg.inputs[1].default_value = 0.35
    return scene


def area_light(name, loc, look_at, size, energy, colour=(1, 1, 1)):
    data = bpy.data.lights.new(name, type="AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = size
    data.energy = energy
    data.color = colour
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(look_at) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return obj


def camera(scene, loc, target, lens=85, fstop=None, focus=None):
    data = bpy.data.cameras.new("cam")
    data.lens = lens
    if fstop:
        data.dof.use_dof = True
        data.dof.aperture_fstop = fstop
        data.dof.focus_distance = focus or (Vector(loc) - Vector(target)).length
    obj = bpy.data.objects.new("cam", data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    scene.camera = obj
    return obj


def box(name, size, location, rotation=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    if bevel:
        b = obj.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = 3
        b.limit_method = "ANGLE"
    return obj


def cyl(name, radius, depth, location, rotation=(0, 0, 0), verts=48):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth,
                                        location=location, rotation=rotation,
                                        vertices=verts)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.shade_smooth()
    return obj


def spun(name, profile, segments=64):
    """Revolve a 2D profile about Z, like OpenSCAD's rotate_extrude."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    verts = [bm.verts.new((r * MM, 0, z * MM)) for r, z in profile]
    edges = [bm.edges.new((verts[i], verts[i + 1])) for i in range(len(verts) - 1)]
    bmesh.ops.spin(bm, geom=verts + edges, axis=(0, 0, 1), cent=(0, 0, 0),
                   dvec=(0, 0, 0), angle=math.radians(360), steps=segments,
                   use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    return obj


def drop_to_floor(obj, z=0.0):
    """Rest an object on a height after it has been rotated."""
    bpy.context.view_layer.update()
    lowest = min((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)
    obj.location.z += z - lowest + CONTACT_LIFT


# --------------------------------------------------------------------------
# Materials
#
# Only unambiguously-socketed nodes are used: Math, Color Ramp, Bump, and the
# texture nodes. ShaderNodeMix carries one A/B pair per data type, so binding
# its sockets by name can silently pick the wrong pair.
# --------------------------------------------------------------------------

def _new(nt, kind):
    return nt.nodes.new(kind)


def _bead_lobe(nt, coord_socket, axis, pitch_mm):
    """Height field for a row of squished extrusion beads.

    A bead is not a sine wave. It leaves the nozzle round, gets squashed
    against the layer below, and the exposed face is left as an arc of that
    round bead meeting its neighbours at a cusp. Across one pitch that is

        u = 2*frac(x / pitch) - 1        position within the bead, -1..1
        h = sqrt(1 - u*u)                the arc

    which gives a fat rounded ridge separated from the next by a narrow, deep
    crevice. A sine gives crests and valleys of equal width and is most of
    why procedural "layer lines" look like corduroy instead of plastic.
    """
    sep = _new(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(coord_socket, sep.inputs["Vector"])

    scaled = _new(nt, "ShaderNodeMath")
    scaled.operation = "MULTIPLY"
    scaled.inputs[1].default_value = 1.0 / (pitch_mm * MM)
    nt.links.new(sep.outputs[axis], scaled.inputs[0])

    t = _new(nt, "ShaderNodeMath")
    t.operation = "FRACT"
    nt.links.new(scaled.outputs[0], t.inputs[0])

    u = _new(nt, "ShaderNodeMath")
    u.operation = "MULTIPLY_ADD"
    u.inputs[1].default_value = 2.0
    u.inputs[2].default_value = -1.0
    nt.links.new(t.outputs[0], u.inputs[0])

    u2 = _new(nt, "ShaderNodeMath")
    u2.operation = "POWER"
    u2.inputs[1].default_value = 2.0
    nt.links.new(u.outputs[0], u2.inputs[0])

    inner = _new(nt, "ShaderNodeMath")
    inner.operation = "SUBTRACT"
    inner.inputs[0].default_value = 1.0
    nt.links.new(u2.outputs[0], inner.inputs[1])

    h = _new(nt, "ShaderNodeMath")
    h.operation = "SQRT"
    h.use_clamp = True
    nt.links.new(inner.outputs[0], h.inputs[0])
    return h.outputs[0]


def _layer_phase(nt, coord_socket, axis, pitch_mm):
    """Returns (layer_index, arc_profile) for a row of beads.

    The integer layer index matters as much as the profile: flow character is
    coherent along a whole layer, so per-layer variation has to be keyed to
    it. Driving variation from 3D noise instead gives rough plastic, not
    extrusion.
    """
    sep = _new(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(coord_socket, sep.inputs["Vector"])

    q = _new(nt, "ShaderNodeMath")
    q.operation = "DIVIDE"
    q.inputs[1].default_value = pitch_mm * MM
    nt.links.new(sep.outputs[axis], q.inputs[0])

    layer = _new(nt, "ShaderNodeMath")
    layer.operation = "FLOOR"
    nt.links.new(q.outputs[0], layer.inputs[0])

    phase = _new(nt, "ShaderNodeMath")
    phase.operation = "FRACT"
    nt.links.new(q.outputs[0], phase.inputs[0])

    u = _new(nt, "ShaderNodeMath")
    u.operation = "MULTIPLY_ADD"
    u.inputs[1].default_value = 2.0
    u.inputs[2].default_value = -1.0
    nt.links.new(phase.outputs[0], u.inputs[0])

    u2 = _new(nt, "ShaderNodeMath")
    u2.operation = "POWER"
    u2.inputs[1].default_value = 2.0
    nt.links.new(u.outputs[0], u2.inputs[0])

    inner = _new(nt, "ShaderNodeMath")
    inner.operation = "SUBTRACT"
    inner.inputs[0].default_value = 1.0
    nt.links.new(u2.outputs[0], inner.inputs[1])

    clamped = _new(nt, "ShaderNodeMath")
    clamped.operation = "MAXIMUM"
    clamped.inputs[1].default_value = 0.0
    nt.links.new(inner.outputs[0], clamped.inputs[0])

    prof = _new(nt, "ShaderNodeMath")
    prof.operation = "SQRT"
    nt.links.new(clamped.outputs[0], prof.inputs[0])
    return layer.outputs[0], prof.outputs[0]


def filament_material(name, colour, displace=False):
    """FDM print surface.

    Walls carry stacked layer beads at the layer height. Top faces carry
    extrusion beads at nozzle width, rotated 45 degrees the way a slicer lays
    them. Both use the arc profile above.

    With `displace` the height field also drives real displacement, which is
    the only way the layer stepping reaches the silhouette. A bump map cannot
    move a profile edge, and a dead straight silhouette on a close-up is what
    gives away a render of a "printed" part.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)

    # Rough dielectric over a pigmented body. PLA's visible-light IOR is about
    # 1.45-1.48. Subsurface, sheen and anisotropy all start at zero: real
    # displaced beads already produce directional highlights, so anisotropy on
    # top double counts, and dark pigmented PLA reads more credibly without
    # the waxiness subsurface introduces.
    bsdf.inputs["IOR"].default_value = 1.46
    bsdf.inputs["Metallic"].default_value = 0.0
    for opt, val in (("Subsurface Weight", 0.0), ("Sheen Weight", 0.0),
                     ("Anisotropic", 0.0), ("Coat Weight", 0.0)):
        if opt in bsdf.inputs:
            bsdf.inputs[opt].default_value = val

    co = _new(nt, "ShaderNodeTexCoord")
    geo = _new(nt, "ShaderNodeNewGeometry")

    # Object space, with scale applied at import, IS print space: the model was
    # authored in its print orientation, so object Z is build height and the
    # pattern stays correct when the part is tipped up for a shot.
    nsep = _new(nt, "ShaderNodeSeparateXYZ")
    upness = _new(nt, "ShaderNodeMath")
    upness.operation = "ABSOLUTE"
    up_ramp = _new(nt, "ShaderNodeMapRange")
    up_ramp.inputs[1].default_value = 0.55
    up_ramp.inputs[2].default_value = 0.9
    nt.links.new(geo.outputs["Normal"], nsep.inputs["Vector"])
    nt.links.new(nsep.outputs["Z"], upness.inputs[0])
    nt.links.new(upness.outputs[0], up_ramp.inputs[0])

    layer_idx, wall_prof = _layer_phase(nt, co.outputs["Object"], "Z", LAYER_H)

    # Flow character is coherent along a whole layer, so amplitude is keyed to
    # the integer layer index. Driving it from 3D noise instead gives rough
    # plastic rather than extrusion. +/-12%.
    lay_noise = _new(nt, "ShaderNodeTexWhiteNoise")
    lay_noise.noise_dimensions = "1D"
    nt.links.new(layer_idx, lay_noise.inputs["W"])
    lay_amp = _new(nt, "ShaderNodeMapRange")
    lay_amp.inputs[3].default_value = 0.88
    lay_amp.inputs[4].default_value = 1.12
    nt.links.new(lay_noise.outputs["Value"], lay_amp.inputs[0])

    wall_h = _new(nt, "ShaderNodeMath")
    wall_h.operation = "MULTIPLY"
    nt.links.new(wall_prof, wall_h.inputs[0])
    nt.links.new(lay_amp.outputs[0], wall_h.inputs[1])

    # Top skin is shallower than the walls: 10-35um against 40-55um.
    spin = _new(nt, "ShaderNodeMapping")
    spin.inputs["Rotation"].default_value = (0, 0, math.radians(45))
    nt.links.new(co.outputs["Object"], spin.inputs["Vector"])
    _, top_prof = _layer_phase(nt, spin.outputs["Vector"], "X", BEAD_W)
    top_h = _new(nt, "ShaderNodeMath")
    top_h.operation = "MULTIPLY"
    top_h.inputs[1].default_value = 0.4
    nt.links.new(top_prof, top_h.inputs[0])

    inv = _new(nt, "ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(up_ramp.outputs[0], inv.inputs[1])

    wall_w = _new(nt, "ShaderNodeMath")
    wall_w.operation = "MULTIPLY"
    nt.links.new(wall_h.outputs[0], wall_w.inputs[0])
    nt.links.new(inv.outputs[0], wall_w.inputs[1])

    top_w = _new(nt, "ShaderNodeMath")
    top_w.operation = "MULTIPLY"
    nt.links.new(top_h.outputs[0], top_w.inputs[0])
    nt.links.new(up_ramp.outputs[0], top_w.inputs[1])

    height = _new(nt, "ShaderNodeMath")
    height.operation = "ADD"
    nt.links.new(wall_w.outputs[0], height.inputs[0])
    nt.links.new(top_w.outputs[0], height.inputs[1])

    # ---- three deliberately uncorrelated signals ----
    #
    # Feeding one waveform into displacement, roughness AND base colour is
    # what gives every layer an identical bright crest and black groove. Real
    # prints have related but not identical geometry, micro-roughness and
    # pigment. So: layer envelope drives displacement only, a fine noise
    # drives bump only, a broad noise drives roughness only. Nothing drives
    # base colour, and there is no cavity darkening -- lighting makes the
    # grooves, not a ramp.

    micro = _new(nt, "ShaderNodeTexNoise")
    micro.inputs["Scale"].default_value = 22000.0        # ~45um features
    micro.inputs["Detail"].default_value = 5.0
    nt.links.new(co.outputs["Object"], micro.inputs["Vector"])
    micro_bump = _new(nt, "ShaderNodeBump")
    micro_bump.inputs["Strength"].default_value = 0.35
    micro_bump.inputs["Distance"].default_value = 0.0000025   # 2.5um
    nt.links.new(micro.outputs["Fac"], micro_bump.inputs["Height"])

    broad = _new(nt, "ShaderNodeTexNoise")
    broad.inputs["Scale"].default_value = 140.0          # ~7mm features
    broad.inputs["Detail"].default_value = 2.0
    nt.links.new(co.outputs["Object"], broad.inputs["Vector"])
    rough = _new(nt, "ShaderNodeMapRange")
    rough.inputs[3].default_value = 0.59
    rough.inputs[4].default_value = 0.65
    nt.links.new(broad.outputs["Fac"], rough.inputs[0])
    nt.links.new(rough.outputs[0], bsdf.inputs["Roughness"])

    if displace:
        nt.links.new(micro_bump.outputs["Normal"], bsdf.inputs["Normal"])
        disp = _new(nt, "ShaderNodeDisplacement")
        disp.inputs["Midlevel"].default_value = 0.5
        # Measured PLA side surfaces run about Ra 13um / Rz 56um, so the
        # visible envelope is 40-55um peak to valley -- a quarter of the
        # nominal layer height, not the layer height itself.
        disp.inputs["Scale"].default_value = 0.000045
        nt.links.new(height.outputs[0], disp.inputs["Height"])
        out = nt.nodes["Material Output"]
        nt.links.new(disp.outputs["Displacement"], out.inputs["Displacement"])
        mat.displacement_method = "BOTH"
    else:
        bump = _new(nt, "ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.7
        bump.inputs["Distance"].default_value = 0.000045
        nt.links.new(height.outputs[0], bump.inputs["Height"])
        nt.links.new(micro_bump.outputs["Normal"], bump.inputs["Normal"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def worn_plastic(name, colour, grime=0.55):
    """Spool body: translucent plastic, dust in the corners, scuffed sides.

    Base colour comes from a ramp driven by ambient occlusion, so the dirt
    collects where a cloth never reaches -- the flange roots and the bore.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Transmission Weight"].default_value = 0.5
    b.inputs["IOR"].default_value = 1.48

    ao = _new(nt, "ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.004
    ao.only_local = True

    ramp = _new(nt, "ShaderNodeValToRGB")
    dirty = tuple(c * grime for c in colour)
    ramp.color_ramp.elements[0].position = 0.25
    ramp.color_ramp.elements[0].color = (*dirty, 1)
    ramp.color_ramp.elements[1].position = 0.85
    ramp.color_ramp.elements[1].color = (*colour, 1)
    nt.links.new(ao.outputs["AO"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])

    co = _new(nt, "ShaderNodeTexCoord")
    scuff = _new(nt, "ShaderNodeTexNoise")
    scuff.inputs["Scale"].default_value = 260.0
    scuff.inputs["Detail"].default_value = 7.0
    nt.links.new(co.outputs["Object"], scuff.inputs["Vector"])

    rough = _new(nt, "ShaderNodeMapRange")
    rough.inputs[3].default_value = 0.18
    rough.inputs[4].default_value = 0.62
    nt.links.new(scuff.outputs["Fac"], rough.inputs[0])
    nt.links.new(rough.outputs[0], b.inputs["Roughness"])

    bump = _new(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.00006
    nt.links.new(scuff.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


def thread_material(name, colour):
    """Wound thread: fine helical banding, sheen, loose fibre fuzz."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    if "Sheen Weight" in b.inputs:
        # Sheen is white retroreflection: crank it and every dyed thread
        # washes out to pastel, which is what a heavy value did here.
        b.inputs["Sheen Weight"].default_value = 0.3
        b.inputs["Sheen Roughness"].default_value = 0.35

    co = _new(nt, "ShaderNodeTexCoord")

    ao = _new(nt, "ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.005
    ao.only_local = True
    ramp = _new(nt, "ShaderNodeValToRGB")
    # Only a mild dirt falloff. Crushing the shadowed side of a wound spool
    # desaturates the one thing carrying colour in the whole frame.
    ramp.color_ramp.elements[0].position = 0.15
    ramp.color_ramp.elements[0].color = (*[c * 0.68 for c in colour], 1)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (*colour, 1)
    nt.links.new(ao.outputs["AO"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])

    wind = _new(nt, "ShaderNodeTexWave")
    wind.wave_type = "BANDS"
    wind.bands_direction = "Z"
    wind.inputs["Scale"].default_value = 2200.0
    wind.inputs["Distortion"].default_value = 3.0
    nt.links.new(co.outputs["Object"], wind.inputs["Vector"])

    fuzz = _new(nt, "ShaderNodeTexNoise")
    fuzz.inputs["Scale"].default_value = 2600.0
    fuzz.inputs["Detail"].default_value = 9.0
    nt.links.new(co.outputs["Object"], fuzz.inputs["Vector"])

    a = _new(nt, "ShaderNodeMath")
    a.operation = "MULTIPLY"
    a.inputs[1].default_value = 0.6
    nt.links.new(wind.outputs["Fac"], a.inputs[0])
    c = _new(nt, "ShaderNodeMath")
    c.operation = "MULTIPLY"
    c.inputs[1].default_value = 0.4
    nt.links.new(fuzz.outputs["Fac"], c.inputs[0])
    h = _new(nt, "ShaderNodeMath")
    h.operation = "ADD"
    nt.links.new(a.outputs[0], h.inputs[0])
    nt.links.new(c.outputs[0], h.inputs[1])

    bump = _new(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.00003
    nt.links.new(h.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

    b.inputs["Roughness"].default_value = 0.62
    return mat


def wood_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.42

    co = _new(nt, "ShaderNodeTexCoord")
    stretch = _new(nt, "ShaderNodeMapping")
    stretch.inputs["Scale"].default_value = (1.0, 0.06, 1.0)
    nt.links.new(co.outputs["Object"], stretch.inputs["Vector"])

    grain = _new(nt, "ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 14.0
    grain.inputs["Detail"].default_value = 9.0
    nt.links.new(stretch.outputs["Vector"], grain.inputs["Vector"])

    ramp = _new(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.32
    ramp.color_ramp.elements[0].color = (0.105, 0.055, 0.028, 1)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (0.24, 0.135, 0.070, 1)
    nt.links.new(grain.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])

    bump = _new(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.18
    bump.inputs["Distance"].default_value = 0.0004
    nt.links.new(grain.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


def cutting_mat_material(name):
    """Self healing mat: dark green, faint grid, low sheen."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.68

    co = _new(nt, "ShaderNodeTexCoord")
    gx = _new(nt, "ShaderNodeTexWave")
    gx.wave_type = "BANDS"
    gx.bands_direction = "X"
    gx.wave_profile = "SAW"
    gx.inputs["Scale"].default_value = 20.0
    nt.links.new(co.outputs["Object"], gx.inputs["Vector"])
    gy = _new(nt, "ShaderNodeTexWave")
    gy.wave_type = "BANDS"
    gy.bands_direction = "Y"
    gy.wave_profile = "SAW"
    gy.inputs["Scale"].default_value = 20.0
    nt.links.new(co.outputs["Object"], gy.inputs["Vector"])

    lines = _new(nt, "ShaderNodeMath")
    lines.operation = "MAXIMUM"
    nt.links.new(gx.outputs["Fac"], lines.inputs[0])
    nt.links.new(gy.outputs["Fac"], lines.inputs[1])

    ramp = _new(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.90
    ramp.color_ramp.elements[0].color = (0.020, 0.043, 0.030, 1)
    ramp.color_ramp.elements[1].position = 0.985
    ramp.color_ramp.elements[1].color = (0.075, 0.115, 0.085, 1)
    nt.links.new(lines.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return mat


def flat_material(name, colour, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*colour, 1)
    b.inputs["Roughness"].default_value = roughness
    return mat


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def make_spool(index, location, rotation=None):
    fr, cr, br = SP_FLANGE_D / 2, SP_CORE_D / 2, SP_BORE_D / 2
    ft = SP_FLANGE_T
    body = spun("spool_body_%d" % index, [
        (br, 0), (fr, 0), (fr, ft), (cr, ft),
        (cr, SP_H - ft), (fr, SP_H - ft), (fr, SP_H), (br, SP_H), (br, 0),
    ])
    body.data.materials.append(worn_plastic(
        "spool_plastic_%d" % index, (0.80, 0.79, 0.74)))

    tr = SP_THREAD_D / 2
    thread = spun("spool_thread_%d" % index, [
        (cr, ft + 0.2), (tr, ft + 0.7), (tr, SP_H - ft - 0.7), (cr, SP_H - ft - 0.2),
    ])
    colour = THREAD_COLOURS[(index * 7) % len(THREAD_COLOURS)]
    thread.data.materials.append(thread_material("thread_%d" % index, colour))

    for o in (body, thread):
        o.location = location
        o.rotation_euler = rotation or (0, 0, math.radians((index * 53) % 360))
    return body, thread


def peg_positions():
    col_spacing = SPOOL_SPACING * math.sqrt(3) / 2
    span_x = (PITCH * GRID_X - GAP) - 2 * WALL - SPOOL_SPACING
    span_y = (PITCH * GRID_Y - GAP) - 2 * WALL - SPOOL_SPACING
    pts = []
    for j in range(int(span_x / col_spacing) + 1):
        off = SPOOL_SPACING / 2 if j % 2 else 0
        for i in range(int((span_y - off) / SPOOL_SPACING) + 1):
            pts.append((j * col_spacing, off + i * SPOOL_SPACING))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ox = (min(xs) + max(xs)) / 2
    oy = (min(ys) + max(ys)) / 2
    return [(x - ox, y - oy) for x, y in pts]


def import_bin(name="bin", z=REST, displace=False):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=STL, global_scale=MM)
    obj = (set(bpy.data.objects) - before).pop()
    obj.name = name

    # global_scale sets object.scale and leaves the mesh in millimetres, but
    # object-space texture coordinates read mesh-local values. Without this
    # the shader sees a part 53 units tall instead of 0.053, so every pitch
    # derived from a real dimension comes out 1000x too fine and aliases into
    # noise. Apply the scale so local space is metres like everything else.
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    obj.location.z = z          # never coplanar with what it rests on

    bev = obj.modifiers.new("bevel", "BEVEL")
    # 0.05-0.15mm catches a believable highlight on a CAD-sharp STL edge
    # without making the part look injection moulded.
    bev.width = 0.00010
    bev.segments = 2
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(35)
    bev.harden_normals = True

    if displace:
        # Adaptive subdivision dices to camera, so the layer relief only gets
        # real geometry where it is actually visible. Without this the mesh
        # would need billions of faces to resolve 0.2mm over 125mm.
        scene = bpy.context.scene
        scene.cycles.feature_set = "EXPERIMENTAL"
        # 1px dicing over the whole part ran out of memory: the bin is 125mm
        # of wall plus thirty pegs, and all of it gets diced, not just the
        # 45mm the camera is looking at. Coarser dice, hard subdivision cap,
        # and aggressive offscreen falloff keep it inside memory while the
        # visible wall still resolves well under a layer.
        scene.cycles.dicing_rate = 2.5
        scene.cycles.max_subdivisions = 6
        scene.cycles.offscreen_dicing_scale = 16.0
        sub = obj.modifiers.new("subd", "SUBSURF")
        sub.subdivision_type = "SIMPLE"
        obj.cycles.use_adaptive_subdivision = True

    obj.data.materials.append(
        filament_material("pla_" + name, FILAMENT, displace=displace))
    return obj


def load_spools(z_base):
    made = []
    for i, (x, y) in enumerate(peg_positions()):
        made += list(make_spool(i, (x * MM, y * MM, z_base)))
    return made


# --------------------------------------------------------------------------
# The craft room
# --------------------------------------------------------------------------

def craft_room(scene, props=True):
    """Workbench, cutting mat, and a background that reads as a sewing room.

    The background is deliberately coarse: at the working apertures it is
    metres behind the subject and never resolves, so it only has to carry
    colour and silhouette.
    """
    table = box("table", (3.0, 2.4, 0.04), (0, 0.35, -0.02))
    table.data.materials.append(wood_material("oak"))

    mat = box("cutting_mat", (0.62, 0.46, MAT_TOP), (0, 0, MAT_TOP / 2),
              bevel=0.0015)
    mat.data.materials.append(cutting_mat_material("mat"))

    wall = box("wall", (4.0, 0.06, 2.6), (0, 1.15, 1.0))
    wall.data.materials.append(flat_material("wall", (0.30, 0.27, 0.24), 0.85))

    if props:
        # Folded fabric, stacked at the back of the bench.
        bolts = [
            ((0.30, 0.16, 0.055), (-0.44, 0.60, 0.028), (0.20, 0.10, 0.13)),
            ((0.29, 0.15, 0.050), (-0.42, 0.60, 0.081), (0.42, 0.30, 0.22)),
            ((0.28, 0.15, 0.048), (-0.46, 0.60, 0.130), (0.12, 0.16, 0.20)),
            ((0.26, 0.14, 0.052), (0.46, 0.66, 0.026), (0.36, 0.14, 0.16)),
            ((0.25, 0.14, 0.046), (0.44, 0.66, 0.075), (0.55, 0.42, 0.28)),
        ]
        for i, (size, loc, col) in enumerate(bolts):
            b = box("bolt_%d" % i, size, loc, rotation=(0, 0, math.radians(4 * i)),
                    bevel=0.006)
            b.data.materials.append(flat_material("fabric_%d" % i, col, 0.9))

        jar = cyl("jar", 0.045, 0.11, (0.30, 0.40, 0.055))
        jar.data.materials.append(flat_material("jar", (0.5, 0.5, 0.52), 0.15))

        # A few spools loose on the bench, well behind the subject.
        for i, (x, y) in enumerate([(-0.24, 0.30), (-0.20, 0.36), (0.16, 0.34)]):
            make_spool(200 + i, (x, y, REST))

    # Window light: big, warm, low, from the left.
    area_light("window", (-1.5, -0.55, 1.05), (0, 0.02, 0.05),
               (1.5, 1.9), 150, (1.0, 0.94, 0.84))
    # Cool bounce from the room.
    area_light("bounce", (1.5, -0.75, 0.55), (0, 0, 0.04),
               (1.8, 1.4), 22, (0.82, 0.88, 1.0))
    # Soft top to keep the interior of the bin readable.
    area_light("top", (-0.15, -0.15, 1.5), (0, 0, 0.05),
               (1.2, 1.2), 40, (1.0, 0.97, 0.92))


# --------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------

def shot_hero(loaded):
    scene = reset_scene()
    craft_room(scene)
    import_bin()
    if loaded:
        load_spools(REST + (BASE_H + FLOOR_T) * MM)
        # Beside the bin, not in front of it: closer to the lens than the
        # subject means both bigger in frame and outside the focal plane.
        make_spool(41, (0.106, -0.012, REST + SP_FLANGE_D / 2 * MM),
                   rotation=(math.radians(90), 0, math.radians(18)))
        make_spool(44, (0.132, 0.030, REST))
        make_spool(47, (0.088, -0.055, REST))
    camera(scene, (0.34, -0.40, 0.21), (0.010, -0.012, 0.026), lens=85, fstop=12)
    return "hero_loaded" if loaded else "hero_empty"


def shot_stacked():
    scene = reset_scene()
    craft_room(scene)
    import_bin("bin_lower")
    import_bin("bin_upper", z=REST + STACK_PITCH * MM)
    # Load the upper bin: the lower one's contents are hidden by the bin on it.
    load_spools(REST + STACK_PITCH * MM + (BASE_H + FLOOR_T) * MM)
    camera(scene, (0.42, -0.48, 0.30), (0, 0, 0.052), lens=80, fstop=13)
    return "stacked"


def shot_topdown(loaded):
    scene = reset_scene()
    craft_room(scene, props=False)
    import_bin()
    if loaded:
        load_spools(REST + (BASE_H + FLOOR_T) * MM)
    area_light("overhead", (-0.30, -0.30, 1.0), (0, 0, 0.03), (2.0, 2.0), 90)
    # A few degrees off vertical: straight down, a spool is only its top
    # flange and the wound colour never shows.
    camera(scene, (0.035, -0.145, 0.60), (0, 0, 0.012), lens=70)
    return "topdown_loaded" if loaded else "topdown_empty"


def shot_macro():
    """Tipped up so the gridfinity feet face the camera."""
    scene = reset_scene()
    craft_room(scene, props=False)
    b = import_bin()
    # Negative X: the underside normal is -Z, and a positive rotation swings
    # it away from the camera, showing the open top instead of the feet.
    b.rotation_euler = (math.radians(-76), 0, math.radians(-22))
    drop_to_floor(b, MAT_TOP)
    area_light("rake", (-0.55, -0.65, 0.36), (0, -0.02, 0.08),
               (0.9, 0.7), 16, (1.0, 0.95, 0.88))
    camera(scene, (0.17, -0.74, 0.17), (0, 0, 0.085), lens=80, fstop=11)
    return "macro_base_lip"


def shot_material():
    """Tight on a wall corner and the rim: the shot for judging the filament.

    Framed at about 45mm across so a 0.2mm layer is roughly 9 pixels, and lit
    across the layers rather than along them. Raking light is the whole game
    for reading extrusion relief; light it head on and even a correct surface
    goes flat.
    """
    scene = reset_scene()
    craft_room(scene, props=False)
    import_bin(displace=True)

    # Square on to the front wall. On a receding corner every horizontal line
    # is slanted by perspective, so a wrong bead direction is unfalsifiable;
    # face on, layer lines must read dead horizontal or the shader is wrong.
    # From steeply above, skimming down the face. Layer lines run horizontally,
    # so a light from the side travels along the grooves and shadows nothing;
    # the relief only appears when the light crosses them.
    # Broad key, roughly 3x the object's apparent size, about 45 degrees off
    # the camera axis and 30 above. A small hard grazing source resolves every
    # groove as a black trench, which is the corduroy failure; a big soft one
    # reveals the envelope through moving highlight gradients instead.
    area_light("key", (-0.26, -0.30, 0.21), (0, -0.080, 0.032),
               (0.26, 0.20), 3.2, (1.0, 0.96, 0.90))
    area_light("fill", (0.36, -0.20, 0.09), (0, -0.080, 0.040),
               (0.5, 0.4), 0.7, (0.88, 0.92, 1.0))
    # No depth of field: at 100mm and 0.22m this is macro range, where even
    # f/16 is millimetres deep and the surface never resolves.
    # Wide enough to read as an object -- rim, wall and a corner -- rather
    # than a texture swatch, but still about 75mm across so a 0.2mm layer
    # spans several pixels.
    camera(scene, (0.055, -0.245, 0.079), (0.0, -0.080, 0.034), lens=85)
    return "material_detail"


SHOTS = {
    "material_detail": shot_material,
    "hero_empty": lambda: shot_hero(False),
    "hero_loaded": lambda: shot_hero(True),
    "stacked": shot_stacked,
    "topdown_empty": lambda: shot_topdown(False),
    "topdown_loaded": lambda: shot_topdown(True),
    "macro_base_lip": shot_macro,
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    wanted = argv if argv else list(SHOTS)
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(STL):
        raise SystemExit("missing %s -- run `make bin` first" % STL)
    for key in wanted:
        if key not in SHOTS:
            raise SystemExit("unknown shot %r; have %s" % (key, ", ".join(SHOTS)))
        name = SHOTS[key]()
        path = os.path.join(OUT, name + ".png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("RENDERED %s" % path)


main()
