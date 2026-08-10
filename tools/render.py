"""Studio renders of the spool holder, for a model listing.

    /Applications/Blender.app/Contents/MacOS/Blender -b --python tools/render.py

Everything is built in real world units -- the bin is 125.5mm across and the
lights are centimetres wide -- so the falloff, the depth of field and the
shadow softness come out of physical numbers rather than being dialled in by
eye. Scenes assembled at 1 unit = 1 metre for the same reason.

The spools are generated here rather than modelled: a revolved profile at the
real dimensions the peg spacing implies, so what you see loaded into the bin
is what actually fits.
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

MM = 0.001              # model is in mm, scenes are in metres

RES = (2000, 1500)
SAMPLES = int(os.environ.get("RENDER_SAMPLES", "320"))

# Bin geometry, needed to place spools and stack copies.
PITCH, GAP = 42.0, 0.5
GRID_X, GRID_Y, GRID_Z = 3, 4, 7
SPOOL_SPACING = 24.68
WALL = 1.6
BASE_H, FLOOR_T = 4.75, 1.25
PEG_HEIGHT = 38.0
UNIT_Z = 7.0
STACK_PITCH = UNIT_Z * GRID_Z          # 49.0, verified against the mesh

# Spool, sized off the spacing: the flange is what sets the 24.68 constraint.
SP_H = 40.0
SP_FLANGE_D = 24.0
SP_FLANGE_T = 1.5
SP_CORE_D = 13.0
SP_BORE_D = 6.4
SP_THREAD_D = 23.4     # nearly flush with the flange, so the colour reads

FILAMENT = (0.055, 0.058, 0.065)       # matte dark grey PLA, linear
LAYER_H = 0.2                          # for the micro relief

THREAD_COLOURS = [
    (0.72, 0.13, 0.14), (0.86, 0.44, 0.09), (0.90, 0.72, 0.16),
    (0.20, 0.42, 0.22), (0.13, 0.30, 0.52), (0.35, 0.18, 0.45),
    (0.78, 0.42, 0.55), (0.85, 0.83, 0.76), (0.10, 0.11, 0.13),
    (0.15, 0.55, 0.52), (0.60, 0.28, 0.13), (0.45, 0.58, 0.24),
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
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"     # filmic highlight rolloff
    scene.view_settings.look = "AgX - Medium High Contrast"

    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = "GPU"
    except Exception:
        scene.cycles.device = "CPU"
    return scene


def world_backdrop(scene, strength=0.35):
    """Dim neutral environment. The area lights do the real work."""
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.055, 0.065, 1)
    bg.inputs[1].default_value = strength


def area_light(name, loc, look_at, size, energy, colour=(1, 1, 1)):
    data = bpy.data.lights.new(name, type="AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = size
    data.energy = energy
    data.color = colour
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    direction = Vector(look_at) - Vector(loc)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def sweep(width=4.0, depth=3.0, height=2.0, radius=0.6, back=0.45):
    """Seamless backdrop: a floor that curves up into a wall.

    `back` is how far behind the origin the wall starts. The subject sits at
    the origin, so a wall at y=0 puts the camera nose to nose with it and the
    frame comes back as flat grey.
    """
    mesh = bpy.data.meshes.new("sweep")
    obj = bpy.data.objects.new("sweep", mesh)
    bpy.context.collection.objects.link(obj)

    # Floor, a quarter round fillet, then wall. Written as an explicit arc
    # about its centre so the tangents actually match at both ends; eyeballed
    # profiles leave a crease that catches light and reads as a seam.
    bm = bmesh.new()
    steps = 24
    profile = [(-depth, 0.0)]
    cy, cz = back - radius, radius
    for i in range(steps + 1):
        a = math.radians(-90 + 90 * i / steps)
        profile.append((cy + radius * math.cos(a), cz + radius * math.sin(a)))
    profile.append((back, height))
    verts_prev = None
    for (y, z) in profile:
        row = [bm.verts.new((-width / 2, y, z)), bm.verts.new((width / 2, y, z))]
        if verts_prev:
            bm.faces.new([verts_prev[0], verts_prev[1], row[1], row[0]])
        verts_prev = row
    bm.to_mesh(mesh)
    bm.free()

    mat = bpy.data.materials.new("backdrop")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.20, 0.21, 0.23, 1)
    bsdf.inputs["Roughness"].default_value = 0.85
    obj.data.materials.append(mat)
    obj.data.shade_smooth()
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


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------

def filament_material(name, colour, roughness=0.62):
    """Matte PLA with layer lines.

    The relief is a wave texture running up object Z at the real layer pitch.
    Bump rather than displacement: at 0.2mm on a 125mm part, real geometry
    would cost a great deal and look identical at these framings.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    # A trace of translucency; PLA is not a pure opaque dielectric.
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.02
        bsdf.inputs["Subsurface Radius"].default_value = (0.6, 0.5, 0.45)

    tex_co = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "Z"
    wave.wave_profile = "SIN"
    # One band per layer: scale is in Blender units, the object is in metres.
    wave.inputs["Scale"].default_value = 1.0 / (LAYER_H * MM * 2)
    wave.inputs["Distortion"].default_value = 0.0

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 900.0
    noise.inputs["Detail"].default_value = 6.0

    # Math nodes rather than a Mix: ShaderNodeMix carries one A/B pair per
    # data type, so looking sockets up by name can quietly bind the wrong one.
    m_wave = nt.nodes.new("ShaderNodeMath")
    m_wave.operation = "MULTIPLY"
    m_wave.inputs[1].default_value = 0.8
    m_noise = nt.nodes.new("ShaderNodeMath")
    m_noise.operation = "MULTIPLY"
    m_noise.inputs[1].default_value = 0.2
    mix = nt.nodes.new("ShaderNodeMath")
    mix.operation = "ADD"

    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.00012

    nt.links.new(tex_co.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(tex_co.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(tex_co.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], m_wave.inputs[0])
    nt.links.new(noise.outputs["Fac"], m_noise.inputs[0])
    nt.links.new(m_wave.outputs[0], mix.inputs[0])
    nt.links.new(m_noise.outputs[0], mix.inputs[1])
    nt.links.new(mix.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def plastic_material(name, colour, roughness=0.35, translucent=False):
    """Spool body. Real thread spools are frosted translucent plastic, not
    white -- render them opaque and a loaded bin becomes a field of blank
    discs with the thread colour hidden underneath."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*colour, 1)
    b.inputs["Roughness"].default_value = roughness
    if translucent:
        # Frosted, not glassy. Smooth high transmission reads as chrome under
        # a hard key, which is the opposite of a cheap plastic spool.
        b.inputs["Transmission Weight"].default_value = 0.55
        b.inputs["IOR"].default_value = 1.48
        b.inputs["Roughness"].default_value = 0.42
    return mat


def thread_material(name, colour):
    """Wound thread: fine bands plus a sheen, so it does not read as plastic."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*colour, 1)
    b.inputs["Roughness"].default_value = 0.55
    if "Sheen Weight" in b.inputs:
        b.inputs["Sheen Weight"].default_value = 0.6
        b.inputs["Sheen Roughness"].default_value = 0.3

    co = nt.nodes.new("ShaderNodeTexCoord")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "Z"
    wave.inputs["Scale"].default_value = 2500.0
    wave.inputs["Distortion"].default_value = 2.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.00002
    nt.links.new(co.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

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


def make_spool(index, location):
    """Body plus thread mass, at the dimensions the peg spacing implies."""
    fr, cr, br = SP_FLANGE_D / 2, SP_CORE_D / 2, SP_BORE_D / 2
    ft = SP_FLANGE_T
    body_profile = [
        (br, 0), (fr, 0), (fr, ft), (cr, ft),
        (cr, SP_H - ft), (fr, SP_H - ft), (fr, SP_H), (br, SP_H), (br, 0),
    ]
    body = spun("spool_body_%d" % index, body_profile)
    body.data.materials.append(plastic_material(
        "spool_plastic_%d" % index, (0.92, 0.91, 0.88), translucent=True))

    tr = SP_THREAD_D / 2
    thread_profile = [
        (cr, ft + 0.2), (tr, ft + 0.6), (tr, SP_H - ft - 0.6),
        (cr, SP_H - ft - 0.2),
    ]
    thread = spun("spool_thread_%d" % index, thread_profile)
    colour = THREAD_COLOURS[index % len(THREAD_COLOURS)]
    thread.data.materials.append(thread_material("thread_%d" % index, colour))

    for o in (body, thread):
        o.location = location
        o.rotation_euler = (0, 0, (index * 37) % 360 * math.pi / 180)
    return body, thread


def peg_positions():
    """Same lattice the model generates: hex packed, columns along Y."""
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


def import_bin(name="bin"):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=STL, global_scale=MM)
    obj = (set(bpy.data.objects) - before).pop()
    obj.name = name

    # Printed edges are never perfectly sharp; a small bevel catches light
    # along every corner and is most of what sells the material.
    bev = obj.modifiers.new("bevel", "BEVEL")
    bev.width = 0.00018
    bev.segments = 2
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(35)
    bev.harden_normals = True
    # Flat shading: the bin is all flats and chamfers, and the bevel modifier
    # supplies the only rounding that should catch light. Smoothing it would
    # blur the crisp 45 degree base profile into something that reads as
    # moulded rather than printed.
    obj.data.materials.append(filament_material("pla_" + name, FILAMENT))
    return obj


def load_spools(bin_obj, z_offset=0.0, limit=None):
    """Drop a spool onto every peg, seated on the bin floor."""
    floor_z = (BASE_H + FLOOR_T) * MM + z_offset
    made = []
    for i, (x, y) in enumerate(peg_positions()):
        if limit is not None and i >= limit:
            break
        made += list(make_spool(i, (x * MM, y * MM, floor_z)))
    return made


# --------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------

def three_point(scene, key_energy=70, size=(1.6, 1.2)):
    """Softbox energies are in watts and the falloff is physical, so these are
    much smaller numbers than they look. The first pass used 900W and blew a
    0.055 albedo to near white."""
    area_light("key", (-1.1, -1.4, 1.5), (0, 0, 0.05), size, key_energy,
               (1.0, 0.97, 0.93))
    area_light("fill", (1.6, -0.9, 0.6), (0, 0, 0.05), (1.8, 1.4), 20,
               (0.90, 0.94, 1.0))
    area_light("rim", (0.7, 1.5, 1.1), (0, 0, 0.06), (1.2, 0.9), 32,
               (0.95, 0.97, 1.0))


def loose_spools(start=40):
    """A few spools outside the bin: one on its side showing the wound thread,
    two upright. Loaded from above, every spool reads as a blank disc, so the
    story of what the bin is for has to be told beside it."""
    # Kept beside the bin rather than in front of it. Closer to the lens than
    # the subject means both bigger in frame and outside the focal plane.
    body, thread = make_spool(start, (0.100, -0.018, SP_FLANGE_D / 2 * MM))
    for o in (body, thread):
        o.rotation_euler = (math.radians(90), 0, math.radians(24))
    make_spool(start + 3, (0.128, 0.020, 0.0))
    make_spool(start + 6, (0.092, -0.058, 0.0))


def shot_hero(loaded):
    scene = reset_scene()
    world_backdrop(scene)
    sweep()
    b = import_bin()
    if loaded:
        load_spools(b)
        loose_spools()
    three_point(scene)
    camera(scene, (0.36, -0.42, 0.22), (0.012, -0.010, 0.026), lens=85, fstop=11)
    return "hero_loaded" if loaded else "hero_empty"


def shot_stacked():
    scene = reset_scene()
    world_backdrop(scene)
    sweep()
    import_bin("bin_lower")
    upper = import_bin("bin_upper")
    # Exactly the verified stack pitch, so the render shows the real seat.
    upper.location = (0, 0, STACK_PITCH * MM)
    # Load the upper bin, not the lower one: the lower bin's contents are
    # hidden by the bin sitting on it, so filling it only costs render time.
    load_spools(upper, z_offset=STACK_PITCH * MM)
    three_point(scene)
    camera(scene, (0.44, -0.50, 0.30), (0, 0, 0.050), lens=80, fstop=14)
    return "stacked"


def shot_topdown(loaded):
    scene = reset_scene()
    world_backdrop(scene, 0.5)
    sweep()
    b = import_bin()
    if loaded:
        load_spools(b)
    area_light("top", (-0.35, -0.35, 0.9), (0, 0, 0.03), (2.2, 2.2), 45)
    area_light("side", (0.6, 0.2, 0.35), (0, 0, 0.03), (1.2, 1.2), 12)
    # A few degrees off vertical rather than dead overhead. Straight down, a
    # spool is only its top flange and the wound colour never shows.
    camera(scene, (0.035, -0.145, 0.60), (0, 0, 0.012), lens=70)
    return "topdown_loaded" if loaded else "topdown_empty"


def drop_to_floor(obj):
    """Rest an object on z=0 after it has been rotated."""
    bpy.context.view_layer.update()
    lowest = min((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)
    obj.location.z -= lowest


def shot_macro():
    """Tipped up onto its back so the gridfinity feet face the camera.

    A close crop of the wall shows the layer lines but says nothing about
    what the part is. The feet are the proof it drops into a baseplate, and
    the profile that took the most measuring to get right.
    """
    scene = reset_scene()
    world_backdrop(scene, 0.3)
    sweep()
    b = import_bin()
    # Negative X: the underside normal is -Z, and a positive rotation swings
    # it away from the camera, showing the open top instead of the feet.
    b.rotation_euler = (math.radians(-76), 0, math.radians(-22))
    drop_to_floor(b)
    # Raking light across the feet: the 45 degree chamfers only read if the
    # key is low enough to throw a shadow down each groove.
    area_light("key", (-0.50, -0.60, 0.34), (0, -0.02, 0.08),
               (0.9, 0.7), 9, (1.0, 0.96, 0.92))
    area_light("rim", (0.52, -0.16, 0.28), (0, -0.02, 0.08),
               (0.6, 0.5), 3.5, (0.9, 0.95, 1.0))
    # Far enough back to hold the whole base. The first attempt sat 130mm away
    # on a 110mm lens at f/3.2 and returned a wall of out-of-focus grey.
    # Tipped up the part stands 167mm tall, so the lens needs roughly 0.75m
    # to hold all of it: vertical coverage is (24/lens) * distance.
    camera(scene, (0.17, -0.74, 0.17), (0, 0, 0.085), lens=80, fstop=11)
    return "macro_base_lip"


SHOTS = {
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
