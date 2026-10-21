"""
Tapered Optical Nanofiber + Photon Animation
=============================================

Builds (entirely from Python) a scene with:
  1. A glass optical fiber that is thick (diameter D1) at both ends, tapers
     down through a sigmoid profile to a thin waist (diameter D2), stays at
     D2 for a central section, then tapers back up to D1.
  2. A small black sphere resting on the top surface of the thin (waist)
     section.
  3. A translucent red "photon" (a prolate spheroid / rugby-ball shape) that
     starts on-axis at the centre of the fiber and travels left, out through
     the taper and the thick end. In the thin section it is wider than the
     glass and pokes out of the surface (representing the evanescent field);
     in the thick section it is fully contained inside the glass.
  4. A camera that starts side-on (perpendicular to the fiber axis), holds
     still, then orbits around the fiber once the photon starts moving.

HOW TO RUN
----------
Option A - headless, build the scene and (optionally) render it:
    blender --background --python nanofiber_animation.py

Option B - interactively, to look around and tweak:
    1. Open Blender.
    2. Switch to the "Scripting" tab.
    3. Open this file (Text > Open).
    4. Set DO_RENDER = False (below) if you just want to inspect the scene.
    5. Click "Run Script".
    6. Look through the camera (View > Cameras > Active Camera, or Numpad 0)
       or scrub the timeline to preview the animation.

Every time this script runs it wipes the current scene and rebuilds it from
scratch from the parameters below, so it is safe to re-run after editing a
number.

TWEAKING
--------
Everything you are likely to want to change lives in the PARAMETERS section
right below this docstring. The geometry/materials/lighting/camera/render
code after that reads those parameters - you should not need to touch it to
get a different look, only to change how things are built.

RENDER QUALITY / SPEED
-----------------------
RENDER_ENGINE, RENDER_SAMPLES, RESOLUTION_X/Y, RESOLUTION_PERCENT and
QUICK_PREVIEW control render quality vs. render time. This scene was
developed/tested on a laptop CPU (no GPU render devices were available in
Cycles on the machine this was written on) - the defaults below are chosen
to look reasonably photo-real while still rendering in a modest amount of
time on a CPU. If you have a Cycles-supported GPU, the script will try to
enable it automatically. See configure_render() near the bottom.
"""

import bpy
import glob
import math
import os
import subprocess

# ============================================================
# PARAMETERS - tweak these, then re-run the script
# ============================================================

# ---- Fiber geometry (arbitrary Blender units - pick whatever scale you like,
#      the whole scene is dimensionless, only the ratios matter) ----
D1 = 2.0            # thick (untapered) diameter at the two ends
D2 = 0.4             # thin (waist) diameter of the central constant section
L1 = 16.0            # combined length of the two thick end sections
                     #   (each end is L1/2 long, per the spec)
L2 = 16.0             # length of the central constant-diameter (D2) section
S = 1.2              # sigmoid taper length/sharpness. Larger S = longer,
                     #   more gradual taper; smaller S = an abrupt step.
                     #   Rule of thumb: keep S well under L1/2 and L2/2 or
                     #   the flat sections won't fully reach D1 / D2.

FIBER_LENGTH_SEGMENTS = 240   # samples along the fiber axis (smoothness of the taper profile)
FIBER_ROUND_SEGMENTS = 24     # sides of the circular cross-section (smoothness of the tube)

FIBER_HALF_LENGTH = (L1 + L2) / 2.0   # derived: half of the total fiber length

# ---- Black sphere sitting on top of the thin/waist section ----
SPHERE_RADIUS = 0.35
# Position along the fiber axis. This is independent of PHOTON_X_OFFSET below
# (the "emitter" sphere and the photon's start position can be moved separately) -
# if they end up overlapping at frame 1, move either one, not necessarily this one.
SPHERE_X = 0.0# L2 * 0.25

# ---- Photon: translucent red prolate spheroid ("rugby ball") ----
# Diameter should be > D2 (so it pokes out of the thin waist) and < D1
# (so it is fully hidden once inside the thick end sections).
PHOTON_DIAMETER = 0.7        # cross-section diameter, constant throughout the animation
PHOTON_LENGTH = 1.6          # length along the fiber axis
PHOTON_SEGMENTS = 32         # UV sphere resolution (u)
PHOTON_RINGS = 16            # UV sphere resolution (v)

# Where the photon starts/rests, as an offset along the fiber axis from the
# fiber's centre (x=0). This is independent of SPHERE_X (the emitter sphere) -
# move one without affecting the other.
PHOTON_X_OFFSET = 0.0
# How far past the fiber's physical tip (at x = +/-FIBER_HALF_LENGTH) the
# photon's centre travels. For the WHOLE photon to visibly clear the glass
# (not just its centre), this needs to be bigger than PHOTON_LENGTH/2 - the
# gap between the photon's trailing edge and the tip at the end of the
# animation is (PHOTON_EXIT_MARGIN - PHOTON_LENGTH/2). Increase this for a
# more obvious exit; reduce it (even below PHOTON_LENGTH/2, or to 0) to have
# it stop still partly - or fully - inside the fiber.
PHOTON_EXIT_MARGIN = 1.5
PHOTON_END_X = -(FIBER_HALF_LENGTH + PHOTON_EXIT_MARGIN)  # moves toward -X ("left")

# ---- Animation timing (frames, at the render fps set below) ----
FPS = 24
FRAME_START = 1
FRAME_HOLD = 24              # photon (and, after a short delay, the camera) hold still until this frame
# Frame at which the photon first becomes visible (pops into existence - e.g.
# to represent it being emitted partway through, rather than always being
# there). Leave equal to FRAME_START for it to be visible for the whole
# animation (the default); must be <= FRAME_HOLD to appear before it starts
# moving.
PHOTON_APPEAR_FRAME = FRAME_START
CAMERA_START_DELAY = 15      # extra frames after FRAME_HOLD before the camera starts rotating
FRAME_END = 168

# ---- Camera ----
# Distance/lens are chosen so the WHOLE fiber (including both thick ends,
# where the photon ends up) stays in frame throughout the orbit.
CAMERA_DISTANCE = 20.0              # initial distance from the fiber axis
CAMERA_HEIGHT = 3.0                 # initial height above the fiber axis
CAMERA_TARGET_Z = 0.4               # height of the point the camera looks at (roughly fiber+sphere centre)
CAMERA_ORBIT_DEGREES = -70.0        # how far the camera swings around the fiber after it starts moving
CAMERA_DOLLY_IN = 3.0              # optional slow push-in over the same period (0 = pure orbit, no dolly)
CAMERA_LENS_MM = 24.0               # wide-ish lens so the full fiber length fits in frame

# ---- Lighting ----
KEY_LIGHT_ENERGY = 2500.0
FILL_LIGHT_ENERGY = 700.0
RIM_LIGHT_ENERGY = 1800.0
ADD_GROUND_PLANE = False   # a clean floor-less background reads better for this kind of physics illustration
GROUND_Z_OFFSET = 5.0    # how far below the fiber axis the ground plane sits (if ADD_GROUND_PLANE is True)

# World background: a physically-based sky (built into Blender, no external
# HDRI file needed) gives the glass some graduated colour/brightness to
# reflect and refract, which reads far more "glass-like" than a flat colour.
# Set USE_SKY_WORLD = False to fall back to a plain flat colour instead.
USE_SKY_WORLD = True
SKY_STRENGTH = 0.35           # turned down from the sun's literal brightness for a moodier look
SKY_SUN_ELEVATION_DEG = 25.0
SKY_SUN_ROTATION_DEG = 110.0
SKY_TURBIDITY = 2.0
SKY_GROUND_ALBEDO = 0.3
WORLD_BACKGROUND_COLOR = (0.04, 0.05, 0.07)   # used only if USE_SKY_WORLD is False
WORLD_BACKGROUND_STRENGTH = 1.2               # used only if USE_SKY_WORLD is False

# Cycles has no denoiser available in this environment (see USE_DENOISING
# above), so a smooth glass rod under small bright lights can produce
# "fireflies" (a few very bright noisy pixels). Clamping indirect/direct
# light contributions keeps these under control; 0 = no clamping.
FIREFLY_CLAMP_DIRECT = 4.0
FIREFLY_CLAMP_INDIRECT = 4.0

# ---- Render / output ----
RENDER_ENGINE = 'CYCLES'     # 'CYCLES' (photo-real glass/transmission) or 'BLENDER_EEVEE' (much faster, cruder glass)
RENDER_SAMPLES = 32 # default is 128         # Cycles samples per pixel. Lower = faster/noisier, higher = slower/cleaner.
RESOLUTION_X = 960 # 480 # default is 960
RESOLUTION_Y = 540 # 270 # default is 540
RESOLUTION_PERCENT = 100 # 100
# NOTE: on some Blender packages (e.g. Debian/Ubuntu's "dfsg" build, which
# this was developed against) the OpenImageDenoise denoiser is missing/
# broken and Cycles silently renders a solid black frame when
# use_denoising=True. If your renders come out black, this is almost
# certainly why - leave this False, or test carefully before enabling it.
USE_DENOISING = False
FRAME_STEP = 1 # Default = 1               # render every Nth frame (raise to speed up rough previews)

QUICK_PREVIEW = False   # True => render only a single, smaller/faster test frame (ignores animation range)
DO_RENDER = True        # True => actually render (can take a while); False => just build + save the .blend
SAVE_BLEND = True        # True => save a .blend file next to this script so you can open it in the GUI
OUTPUT_SUBDIR = "renders"

# After rendering the PNG frames, stitch them into an actual video file with
# ffmpeg (must be installed and on PATH; this machine has it at /usr/bin/ffmpeg).
# If ffmpeg isn't available, the PNG frames are still written fine - you'll
# just see a warning and can stitch them yourself later.
CREATE_VIDEO = True
VIDEO_FILENAME = "nanofiber_animation.mp4"
VIDEO_CRF = 18     # x264 quality: lower = better/larger, 18 is visually near-lossless, 23 is the x264 default
# Video frame rate: None = auto (FPS / FRAME_STEP, so the video's real-time
# duration matches the animation even when FRAME_STEP skips frames to save
# render time). Set an explicit number instead if you want a different pace.
VIDEO_FPS = None

# Some Blender packages (notably Debian/Ubuntu's "dfsg" repackaging) ship
# without the OpenColorIO colour-management data Blender normally uses to
# turn Cycles' linear render result into an 8-bit sRGB image. On those
# installs, saving straight to PNG/JPEG from Cycles silently produces a
# solid black image (the render itself is fine - only the colour-managed
# export step is broken; Eevee is unaffected because it uses a different
# code path). When True, Cycles renders are written as linear EXR first
# (unaffected by the bug) and then converted to PNG ourselves with a tiny
# built-in sRGB encoder (pure Python, no add-ons/libraries required), which
# works correctly regardless of whether Blender's own colour management is
# set up. If you know your Blender install's colour management works fine,
# you can set this to False to just let Blender save PNGs directly.
MANUAL_SRGB_PNG_WORKAROUND = True

# ============================================================
# Helpers
# ============================================================

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.path.abspath(os.getcwd())


def get_output_dir():
    out_dir = os.path.join(SCRIPT_DIR, OUTPUT_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def get_exr_staging_dir():
    # Only used when MANUAL_SRGB_PNG_WORKAROUND is active: Cycles renders
    # land here first as linear EXR, then get converted into get_output_dir().
    out_dir = os.path.join(get_output_dir(), "exr_linear")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


# ---- Minimal, dependency-free linear-EXR -> sRGB-PNG conversion ----------
# Used only as a workaround for Blender installs with broken/missing colour
# management (see MANUAL_SRGB_PNG_WORKAROUND above). Uses only Python's
# standard library (struct/zlib), so it works inside any Blender's bundled
# Python with no extra installs.

_SRGB_LUT_SIZE = 4096


def _build_srgb_lut():
    lut = []
    for i in range(_SRGB_LUT_SIZE):
        c = i / (_SRGB_LUT_SIZE - 1)
        if c <= 0.0031308:
            s = 12.92 * c
        else:
            s = 1.055 * (c ** (1.0 / 2.4)) - 0.055
        lut.append(max(0, min(255, round(s * 255))))
    return lut


_SRGB_LUT = _build_srgb_lut()


def _linear_to_srgb_byte(c):
    if c <= 0.0:
        return 0
    if c >= 1.0:
        return 255
    return _SRGB_LUT[int(c * (_SRGB_LUT_SIZE - 1))]


def _write_png(path, width, height, rgb_bytes):
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # no per-row filter
        raw.extend(rgb_bytes[y * stride:(y + 1) * stride])
    compressed = zlib.compress(bytes(raw), 6)
    with open(path, 'wb') as f:
        f.write(sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', compressed) + chunk(b'IEND', b''))


def convert_linear_image_to_srgb_png(image, png_path):
    """image: a bpy.types.Image with float linear RGBA pixels (e.g. loaded
    from an EXR render). Writes an 8-bit sRGB PNG to png_path."""
    width, height = image.size
    pixels = list(image.pixels[:])  # bottom-to-top row order, RGBA floats
    lut = _SRGB_LUT
    scale = _SRGB_LUT_SIZE - 1
    out = bytearray(width * height * 3)
    row_stride = width * 3
    for y in range(height):
        src_row = (height - 1 - y) * width * 4  # flip vertical: PNG is top-to-bottom
        dst_row = y * row_stride
        for x in range(width):
            sp = src_row + x * 4
            dp = dst_row + x * 3
            for c in range(3):
                v = pixels[sp + c]
                if v <= 0.0:
                    b = 0
                elif v >= 1.0:
                    b = 255
                else:
                    b = lut[int(v * scale)]
                out[dp + c] = b
    _write_png(png_path, width, height, out)


def convert_rendered_exrs_to_png(exr_dir, out_dir):
    exr_paths = sorted(glob.glob(os.path.join(exr_dir, "frame_*.exr")))
    if not exr_paths:
        print("No EXR frames found in", exr_dir, "- nothing to convert.")
        return
    print("Converting %d linear EXR frame(s) to sRGB PNG..." % len(exr_paths))
    for exr_path in exr_paths:
        base = os.path.splitext(os.path.basename(exr_path))[0]
        png_path = os.path.join(out_dir, base + ".png")
        img = bpy.data.images.load(exr_path)
        try:
            convert_linear_image_to_srgb_png(img, png_path)
        finally:
            bpy.data.images.remove(img)
    print("Wrote %d PNG frame(s) to %s" % (len(exr_paths), out_dir))


def stitch_frames_to_video(png_dir, video_path, fps):
    # -pattern_type glob (rather than a %04d pattern) copes correctly with
    # gaps in the frame numbers, e.g. from FRAME_STEP > 1.
    pattern = os.path.join(png_dir, "frame_*.png")
    n_frames = len(glob.glob(pattern))
    if n_frames < 2:
        print("Fewer than 2 PNG frames in", png_dir, "- skipping video creation.")
        return None

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-pattern_type", "glob", "-i", pattern,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", str(VIDEO_CRF),
        video_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print("ffmpeg was not found on PATH - PNG frames are in", png_dir,
              "but no video was created. Install ffmpeg, or stitch them "
              "yourself with:\n  " + " ".join(cmd))
        return None
    except subprocess.CalledProcessError as e:
        print("ffmpeg failed while creating the video:\n", e.stderr)
        return None

    print("Wrote video (%d frames @ %s fps) to %s" % (n_frames, fps, video_path))
    return video_path


def sigmoid(t):
    # numerically safe logistic function
    if t >= 0:
        z = math.exp(-t)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(t)
        return z / (1.0 + z)


def diameter_at(x):
    """Fiber diameter at axial position x.

    A single symmetric logistic profile: D2 in the centre, smoothly
    transitioning up to D1 on both sides once |x| passes L2/2. The taper
    "sharpness" is controlled by S (bigger S = more gradual).
    """
    return D2 + (D1 - D2) * sigmoid((abs(x) - L2 / 2.0) / S)


# Robust Principled BSDF input lookup: input names changed across Blender
# versions (e.g. "Transmission" -> "Transmission Weight" in Blender 4.x), so
# try a list of known aliases and use whichever exists on this Blender build.
def set_principled(node, value, *names):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return True
    return False


def make_glass_material(name, color, transmission=1.0, roughness=0.03, ior=1.45):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    set_principled(bsdf, (*color, 1.0), "Base Color")
    set_principled(bsdf, transmission, "Transmission", "Transmission Weight")
    set_principled(bsdf, roughness, "Roughness")
    set_principled(bsdf, ior, "IOR")
    set_principled(bsdf, 1.0, "Alpha")
    try:
        bsdf.distribution = 'MULTI_GGX'
    except Exception:
        pass
    return mat


def make_photon_material(name, color, transmission=0.85, roughness=0.12, ior=1.3,
                          emission_color=None, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    set_principled(bsdf, (*color, 1.0), "Base Color")
    set_principled(bsdf, transmission, "Transmission", "Transmission Weight")
    set_principled(bsdf, roughness, "Roughness")
    set_principled(bsdf, ior, "IOR")
    set_principled(bsdf, 1.0, "Alpha")
    if emission_color is not None:
        set_principled(bsdf, (*emission_color, 1.0), "Emission Color", "Emission")
        set_principled(bsdf, emission_strength, "Emission Strength")
    return mat


def make_diffuse_material(name, color, roughness=0.4, specular=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    set_principled(bsdf, (*color, 1.0), "Base Color")
    set_principled(bsdf, roughness, "Roughness")
    set_principled(bsdf, specular, "Specular", "Specular IOR Level")
    return mat


def add_keyframe(obj, path, index, frame, value):
    setattr_via_path(obj, path, index, value)
    obj.keyframe_insert(data_path=path, index=index, frame=frame)


def setattr_via_path(obj, path, index, value):
    if path == "location":
        obj.location[index] = value
    elif path == "rotation_euler":
        obj.rotation_euler[index] = value
    else:
        raise ValueError("unsupported path: %s" % path)


def style_fcurve(obj, path, index, interpolation='SINE', easing='EASE_IN_OUT'):
    if not obj.animation_data or not obj.animation_data.action:
        return
    for fcu in obj.animation_data.action.fcurves:
        if fcu.data_path == path and fcu.array_index == index:
            for kp in fcu.keyframe_points:
                kp.interpolation = interpolation
                kp.easing = easing


# ============================================================
# Scene clearing (safe to re-run in the same Blender session)
# ============================================================

def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                       bpy.data.lights, bpy.data.cameras, bpy.data.worlds,
                       bpy.data.actions):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


# ============================================================
# Fiber
# ============================================================

def build_fiber():
    curve_data = bpy.data.curves.new('FiberProfile', type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 1  # we already sample densely ourselves

    spline = curve_data.splines.new('POLY')
    n = FIBER_LENGTH_SEGMENTS
    spline.points.add(n - 1)

    x0 = -FIBER_HALF_LENGTH
    x1 = FIBER_HALF_LENGTH
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        radius = diameter_at(x) / 2.0
        spline.points[i].co = (x, 0.0, 0.0, 1.0)
        spline.points[i].radius = radius

    curve_data.bevel_depth = 1.0
    curve_data.bevel_resolution = max(0, FIBER_ROUND_SEGMENTS // 4 - 1)
    curve_data.use_fill_caps = True

    curve_obj = bpy.data.objects.new('FiberCurve', curve_data)
    bpy.context.collection.objects.link(curve_obj)

    # Convert to a mesh so it shades/behaves like an ordinary solid object.
    bpy.ops.object.select_all(action='DESELECT')
    curve_obj.select_set(True)
    bpy.context.view_layer.objects.active = curve_obj
    bpy.ops.object.convert(target='MESH')
    fiber_obj = bpy.context.view_layer.objects.active
    fiber_obj.name = 'Fiber'

    bpy.ops.object.shade_smooth()
    try:
        fiber_obj.data.use_auto_smooth = True
        fiber_obj.data.auto_smooth_angle = math.radians(35)
    except Exception:
        pass

    glass_mat = make_glass_material('Fiber_Glass', color=(0.85, 0.92, 0.95), roughness=0.06)
    fiber_obj.data.materials.append(glass_mat)

    return fiber_obj


# ============================================================
# Black sphere
# ============================================================

def build_sphere():
    local_radius = diameter_at(SPHERE_X) / 2.0
    z = local_radius + SPHERE_RADIUS
    bpy.ops.mesh.primitive_uv_sphere_add(radius=SPHERE_RADIUS, location=(SPHERE_X, 0.0, z),
                                          segments=32, ring_count=16)
    sphere_obj = bpy.context.active_object
    sphere_obj.name = 'BlackSphere'
    bpy.ops.object.shade_smooth()

    mat = make_diffuse_material('Sphere_Black', color=(0.01, 0.01, 0.012), roughness=0.35)
    sphere_obj.data.materials.append(mat)
    return sphere_obj


# ============================================================
# Photon
# ============================================================

def build_photon():
    radius = PHOTON_DIAMETER / 2.0
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(PHOTON_X_OFFSET, 0.0, 0.0),
                                          segments=PHOTON_SEGMENTS, ring_count=PHOTON_RINGS)
    photon_obj = bpy.context.active_object
    photon_obj.name = 'Photon'

    # Stretch along the fiber axis (X) to make the "rugby ball" shape, then
    # bake the scale in so later keyframes only need to touch location.
    stretch = (PHOTON_LENGTH / 2.0) / radius
    photon_obj.scale.x = stretch
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    bpy.ops.object.shade_smooth()

    mat = make_photon_material('Photon_Red', color=(0.85, 0.03, 0.03),
                                emission_color=(1.0, 0.08, 0.05), emission_strength=0.5)
    photon_obj.data.materials.append(mat)
    return photon_obj


def animate_photon(photon_obj):
    add_keyframe(photon_obj, 'location', 0, FRAME_START, PHOTON_X_OFFSET)
    add_keyframe(photon_obj, 'location', 0, FRAME_HOLD, PHOTON_X_OFFSET)
    add_keyframe(photon_obj, 'location', 0, FRAME_END, PHOTON_END_X)
    style_fcurve(photon_obj, 'location', 0)

    animate_appearance(photon_obj, PHOTON_APPEAR_FRAME)


def animate_appearance(obj, appear_frame):
    """Keyframes hide_render/hide_viewport so obj is hidden before
    appear_frame and visible from appear_frame onward (a hard pop-in, not a
    fade). No-op if appear_frame <= FRAME_START (visible the whole time)."""
    if appear_frame <= FRAME_START:
        return
    for prop in ('hide_render', 'hide_viewport'):
        setattr(obj, prop, True)
        obj.keyframe_insert(data_path=prop, frame=FRAME_START)
        setattr(obj, prop, False)
        obj.keyframe_insert(data_path=prop, frame=appear_frame)
        # CONSTANT: visibility should snap, not ease/fade between the two states.
        style_fcurve(obj, prop, 0, interpolation='CONSTANT', easing='EASE_IN_OUT')


# ============================================================
# World / lighting
# ============================================================

def build_world():
    world = bpy.data.worlds.new('World')
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get('Background')
    if not bg:
        return world

    if USE_SKY_WORLD:
        sky = nt.nodes.new('ShaderNodeTexSky')
        try:
            sky.sky_type = 'NISHITA'
        except Exception:
            pass
        try:
            sky.sun_elevation = math.radians(SKY_SUN_ELEVATION_DEG)
            sky.sun_rotation = math.radians(SKY_SUN_ROTATION_DEG)
            sky.turbidity = SKY_TURBIDITY
            sky.ground_albedo = SKY_GROUND_ALBEDO
        except Exception as e:
            print("Sky texture parameters partially unsupported:", e)
        nt.links.new(sky.outputs['Color'], bg.inputs['Color'])
        bg.inputs['Strength'].default_value = SKY_STRENGTH
    else:
        bg.inputs['Color'].default_value = (*WORLD_BACKGROUND_COLOR, 1.0)
        bg.inputs['Strength'].default_value = WORLD_BACKGROUND_STRENGTH
    return world


def add_area_light(name, location, energy, size, target_empty):
    light_data = bpy.data.lights.new(name, type='AREA')
    light_data.energy = energy
    light_data.size = size
    light_obj = bpy.data.objects.new(name, light_data)
    light_obj.location = location
    bpy.context.collection.objects.link(light_obj)
    con = light_obj.constraints.new('TRACK_TO')
    con.target = target_empty
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    return light_obj


def build_lighting(target_empty):
    add_area_light('KeyLight', (5.0, -7.0, 6.5), KEY_LIGHT_ENERGY, 3.0, target_empty)
    add_area_light('FillLight', (-6.0, -3.5, 3.0), FILL_LIGHT_ENERGY, 5.0, target_empty)
    add_area_light('RimLight', (0.0, 7.0, 4.5), RIM_LIGHT_ENERGY, 2.5, target_empty)


def build_ground():
    if not ADD_GROUND_PLANE:
        return None
    z = -GROUND_Z_OFFSET
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, z))
    ground = bpy.context.active_object
    ground.name = 'Ground'
    mat = make_diffuse_material('Ground_Diffuse', color=(0.06, 0.06, 0.07), roughness=0.6)
    ground.data.materials.append(mat)
    return ground


# ============================================================
# Camera
# ============================================================

def build_camera():
    target = bpy.data.objects.new('FiberCenterTarget', None)
    target.location = (0.0, 0.0, CAMERA_TARGET_Z)
    target.empty_display_size = 0.2
    bpy.context.collection.objects.link(target)

    rig = bpy.data.objects.new('CameraRig', None)
    rig.location = (0.0, 0.0, 0.0)
    rig.empty_display_size = 0.5
    bpy.context.collection.objects.link(rig)

    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens = CAMERA_LENS_MM
    cam_obj = bpy.data.objects.new('Camera', cam_data)
    # Positioned side-on: looking along +Y, perpendicular to the fiber's X axis.
    cam_obj.location = (0.0, -CAMERA_DISTANCE, CAMERA_HEIGHT)
    bpy.context.collection.objects.link(cam_obj)

    cam_obj.parent = rig  # rig is at the identity transform right now, so no parent-inverse correction needed

    con = cam_obj.constraints.new('TRACK_TO')
    con.target = target
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'

    bpy.context.scene.camera = cam_obj
    return cam_obj, rig, target


def animate_camera(cam_obj, rig):
    rotate_start = FRAME_HOLD + CAMERA_START_DELAY

    add_keyframe(rig, 'rotation_euler', 2, FRAME_START, 0.0)
    add_keyframe(rig, 'rotation_euler', 2, rotate_start, 0.0)
    add_keyframe(rig, 'rotation_euler', 2, FRAME_END, math.radians(CAMERA_ORBIT_DEGREES))
    style_fcurve(rig, 'rotation_euler', 2)

    if CAMERA_DOLLY_IN != 0.0:
        end_distance = max(0.5, CAMERA_DISTANCE - CAMERA_DOLLY_IN)
        add_keyframe(cam_obj, 'location', 1, FRAME_START, -CAMERA_DISTANCE)
        add_keyframe(cam_obj, 'location', 1, rotate_start, -CAMERA_DISTANCE)
        add_keyframe(cam_obj, 'location', 1, FRAME_END, -end_distance)
        style_fcurve(cam_obj, 'location', 1)


# ============================================================
# Render settings
# ============================================================

def configure_render():
    scene = bpy.context.scene
    scene.render.engine = RENDER_ENGINE
    scene.render.fps = FPS
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    scene.frame_step = FRAME_STEP
    scene.render.resolution_x = RESOLUTION_X
    scene.render.resolution_y = RESOLUTION_Y
    scene.render.resolution_percentage = RESOLUTION_PERCENT

    use_workaround = (RENDER_ENGINE == 'CYCLES') and MANUAL_SRGB_PNG_WORKAROUND
    if use_workaround:
        # Render linear, undamaged-by-broken-colour-management EXRs; they get
        # converted to the real output PNGs afterwards (see main()).
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '16'
        scene.render.filepath = os.path.join(get_exr_staging_dir(), "frame_" + "#" * 4)
    else:
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = os.path.join(get_output_dir(), "frame_" + "#" * 4)

    if RENDER_ENGINE == 'CYCLES':
        cyc = scene.cycles
        cyc.samples = RENDER_SAMPLES
        cyc.use_denoising = USE_DENOISING
        try:
            cyc.denoiser = 'OPENIMAGEDENOISE'
        except Exception:
            pass
        # Cheap-but-effective speed tricks for a simple glass-rod scene:
        cyc.caustics_reflective = False
        cyc.caustics_refractive = False
        cyc.max_bounces = 8
        cyc.transmission_bounces = 12
        cyc.glossy_bounces = 4
        cyc.transparent_max_bounces = 8
        cyc.sample_clamp_direct = FIREFLY_CLAMP_DIRECT
        cyc.sample_clamp_indirect = FIREFLY_CLAMP_INDIRECT

        try:
            prefs = bpy.context.preferences.addons['cycles'].preferences
            prefs.get_devices()
            gpu_types = [e.identifier for e in prefs.bl_rna.properties['compute_device_type'].enum_items
                         if e.identifier != 'NONE']
            if gpu_types:
                prefs.compute_device_type = gpu_types[0]
                for d in prefs.devices:
                    d.use = True
                cyc.device = 'GPU'
            else:
                cyc.device = 'CPU'
        except Exception as e:
            print("Cycles device auto-setup skipped:", e)

    if QUICK_PREVIEW:
        scene.render.resolution_percentage = min(RESOLUTION_PERCENT, 50)
        if RENDER_ENGINE == 'CYCLES':
            scene.cycles.samples = min(RENDER_SAMPLES, 24)
        scene.frame_start = FRAME_START
        scene.frame_end = FRAME_START


# ============================================================
# Main
# ============================================================

def main():
    if PHOTON_DIAMETER <= D2:
        print("WARNING: PHOTON_DIAMETER (%.3f) <= D2 (%.3f) - the photon will "
              "never poke out of the fiber in the thin section." % (PHOTON_DIAMETER, D2))
    if PHOTON_DIAMETER >= D1:
        print("WARNING: PHOTON_DIAMETER (%.3f) >= D1 (%.3f) - the photon will "
              "not be fully hidden in the thick section." % (PHOTON_DIAMETER, D1))

    clear_scene()

    build_fiber()
    build_sphere()
    photon_obj = build_photon()
    animate_photon(photon_obj)

    build_world()
    build_ground()

    cam_obj, rig, target = build_camera()
    build_lighting(target)
    animate_camera(cam_obj, rig)

    bpy.context.scene.frame_set(FRAME_START)

    configure_render()

    if SAVE_BLEND:
        blend_path = os.path.join(SCRIPT_DIR, "nanofiber_scene.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print("Saved scene to", blend_path)

    use_workaround = (RENDER_ENGINE == 'CYCLES') and MANUAL_SRGB_PNG_WORKAROUND

    if DO_RENDER:
        # animation=True renders every frame in [frame_start, frame_end] using
        # the output settings above; with QUICK_PREVIEW those are both
        # FRAME_START, so this also correctly handles the single-frame case.
        bpy.ops.render.render(animation=True)
        if use_workaround:
            convert_rendered_exrs_to_png(get_exr_staging_dir(), get_output_dir())
        if QUICK_PREVIEW:
            print("Quick preview render written to", get_output_dir())
        else:
            print("Animation frames written to", get_output_dir())
            if CREATE_VIDEO:
                fps = VIDEO_FPS if VIDEO_FPS is not None else max(1, round(FPS / FRAME_STEP))
                stitch_frames_to_video(get_output_dir(),
                                        os.path.join(get_output_dir(), VIDEO_FILENAME),
                                        fps)
    else:
        print("DO_RENDER is False - scene was built (and saved) but not rendered. "
              "Set DO_RENDER = True (and re-run) to render.")


if __name__ == "__main__":
    main()
