# swarm3d_alpha_v04.py
# Swarm 3D v0.4 — Alpha AI + construction of a letter (A implemented)
# Requires: pip install vpython

from vpython import *
import random, math, sys

# === PARAMETERS ===
NUM_SATELLITES = 40
F_TOTAL = 100
T_LOW = 30
T_CRITICAL = 15
F_MAX_SHARE = F_TOTAL / 3
ICE_CONSUMPTION = 0.03
SPEED = 0.4
BOND_RADIUS = 8
BASE_POS = vector(0, 0, 0)
BUILD_SCALE = 1.0  # base unit for building shape; final scale uses BUILD_SCALE * 15 (1:15 relation)

# === SCENE ===
scene = canvas(title="Swarm 3D v0.4 — Alpha AI + Construction",
               width=1000, height=700, background=color.black)
scene.camera.pos = vector(0, 30, 80)
scene.camera.axis = vector(0, -8, -80)

# base marker
base_marker = sphere(pos=BASE_POS, radius=1.2, color=color.green, opacity=0.25)

# colors
COLORS = {
    "free": color.white,
    "builder": color.blue,
    "beacon": color.cyan,
    "commander": vector(0, 1, 1),
    "reserver": vector(0, 0.8, 0.8),
    "returning": color.green,
    "dead": color.red,
    "rescue": color.yellow,
    "weak": vector(0.5, 0.5, 0.5),
    "alpha": vector(0.6, 0.2, 0.8),  # purple-ish
    "target": vector(1, 0.6, 0.2)
}

# prompt for letter (console)
letter = input("Enter an uppercase English letter to build (A for now) [default A]: ").strip().upper()
if not letter:
    letter = "A"

# helper: generate target points in plane z=0 for letter
def generate_letter_points(letter_char, scale=BUILD_SCALE, spacing=2.5):
    """
    Currently supports:
      - 'A' : triangular A with crossbar
    Fallback: rectangle frame.
    Returns list of vector positions (x,y,z)
    scale: base scale factor
    spacing: distance between logical grid points
    """
    pts = []
    s = scale * spacing * 1.0
    # center building around origin
    if letter_char == "A":
        height = 8 * s
        half_width = 3 * s
        # left leg
        for i in range(0, 9):
            t = i / 8.0
            x = -half_width * (1 - t)
            y = -height/2 + t * height
            pts.append(vector(x, y, 0))
        # right leg
        for i in range(0, 9):
            t = i / 8.0
            x = half_width * (1 - t)
            y = -height/2 + t * height
            pts.append(vector(x, y, 0))
        # crossbar near middle (y ~ 0)
        for i in range(-2, 3):
            x = i * s
            y = 0
            pts.append(vector(x, y, 0))
        # optionally fill interior sparsely
        for rx in range(-2,3):
            for ry in range(1,4):
                if random.random() < 0.3:
                    pts.append(vector(rx * s, ry * s - height/2 + 2*s, 0))
    else:
        # fallback: rectangle frame
        w = 8 * s
        h = 10 * s
        # top & bottom, left & right
        steps = 14
        for i in range(steps+1):
            t = i/steps
            pts.append(vector(-w/2 + t*w, -h/2, 0))  # bottom
            pts.append(vector(-w/2 + t*w, h/2, 0))   # top
            pts.append(vector(-w/2, -h/2 + t*h, 0))  # left
            pts.append(vector(w/2, -h/2 + t*h, 0))   # right
    # deduplicate approximately
    uniq = []
    seen = set()
    for p in pts:
        key = (round(p.x,2), round(p.y,2))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq

# generate target points scaled 1:15 relative to satellite (we interpret BUILD_SCALE*15)
# We'll upscale by factor 15 for final construction size:
targets = generate_letter_points(letter, scale=BUILD_SCALE, spacing=1.2)
# apply scale 1:15: satellite size approximate -> assume satellite visual radius ~0.8, so scale factor:
SCALE_1_15 = 15.0
targets = [vector(p.x * SCALE_1_15, p.y * SCALE_1_15, p.z * SCALE_1_15) for p in targets]

# visualize target points
target_spheres = []
for t in targets:
    spt = sphere(pos=t, radius=0.35, color=COLORS["target"], opacity=0.25)
    target_spheres.append({"pos": t, "sphere": spt, "built": False, "builder": None})

# === Satellite class ===
class Satellite:
    def __init__(self, idx):
        self.idx = idx
        self.pos = vector(random.uniform(-40, 40),
                          random.uniform(-5, 30),
                          random.uniform(-40, 40))
        self.vel = vector(random.uniform(-1, 1),
                          random.uniform(-0.3, 0.3),
                          random.uniform(-1, 1))
        self.sphere = sphere(pos=self.pos, radius=0.9, color=COLORS["free"], make_trail=False)
        self.label = label(pos=self.pos + vector(0,1.5,0), text=str(int(F_TOTAL)), height=10, color=color.white, box=False)
        self.fuel = F_TOTAL
        self.status = "free"      # free, builder, beacon, returning, rescue, weak, dead
        self.role = None          # commander/reserver
        self.target = None        # rescue target or assigned target point index
        self.beacon_pair = None   # builder's pair [commander, reserver]
        self.last_action = 0

    def update_label(self):
        self.label.pos = self.sphere.pos + vector(0,1.3,0)
        self.label.text = f"{int(self.fuel)}"

    def move_to(self, tgt_pos):
        dir = tgt_pos - self.pos
        if mag(dir) < 0.5:
            return
        self.vel = norm(dir)
        self.pos += self.vel * SPEED
        self.sphere.pos = self.pos
        self.label.pos = self.pos + vector(0,1.3,0)

    def random_roam(self):
        # small wander
        self.pos += norm(self.vel) * SPEED
        self.sphere.pos = self.pos
        self.label.pos = self.pos + vector(0,1.3,0)

    def step(self):
        # fixed beacons: they don't move (but slowly drain)
        if self.status == "beacon":
            # minimal drain
            self.fuel -= ICE_CONSUMPTION * 0.02
            self.sphere.pos = self.pos
            self.update_label()
            if self.fuel <= 0:
                self.status = "dead"
                self.sphere.color = COLORS["dead"]
            return

        if self.status == "builder":
            # move to center between beacons
            if self.beacon_pair:
                center = (self.beacon_pair[0].pos + self.beacon_pair[1].pos) / 2
                self.move_to(center)
        elif self.status == "rescue" and self.target:
            self.move_to(self.target.pos)
        elif self.status in ["returning", "weak"]:
            self.move_to(BASE_POS)
        elif self.status == "free":
            # roam with gentle noise
            self.random_roam()

        # boundaries bounce
        for axis in ['x','y','z']:
            val = getattr(self.pos, axis)
            if abs(val) > 60:
                setattr(self.vel, axis, -getattr(self.vel, axis))
        # fuel consumption
        if self.status != "beacon":
            self.fuel -= ICE_CONSUMPTION

        # transitions
        if self.fuel <= 0 and self.status != "dead":
            self.status = "dead"
            self.sphere.color = COLORS["dead"]
            self.vel = vector(0,0,0)
            self.label.color = color.red
        elif self.status == "free" and self.fuel < T_CRITICAL:
            self.status = "weak"
            self.sphere.color = COLORS["weak"]
        # update visuals
        if self.status == "free":
            self.sphere.color = COLORS["free"]
        if self.status == "builder":
            self.sphere.color = COLORS["builder"]
        if self.status == "returning":
            self.sphere.color = COLORS["returning"]
        if self.status == "rescue":
            self.sphere.color = COLORS["rescue"]
        self.sphere.pos = self.pos
        self.update_label()

# === Swarm initialization ===
satellites = [Satellite(i) for i in range(NUM_SATELLITES)]

# Alpha AI
class AlphaAI:
    def __init__(self, satellites):
        self.sat = satellites
        self.visual = sphere(pos=BASE_POS + vector(0, -5, 0), radius=1.0, color=COLORS["alpha"], emissive=True, opacity=0.6)
        self.links = []  # curves showing influence
        self.counter = 0
        self.bond_radius = BOND_RADIUS
        self.triplet_interval_frames = 120  # frames between attempts
        self.last_triplet_frame = -999

    def telemetry(self):
        total = sum(s.fuel for s in self.sat)
        avg = total / len(self.sat)
        free = len([s for s in self.sat if s.status == "free"])
        builder = len([s for s in self.sat if s.status == "builder"])
        beacon = len([s for s in self.sat if s.status == "beacon"])
        dead = len([s for s in self.sat if s.status == "dead"])
        weak = len([s for s in self.sat if s.status == "weak"])
        instability = (weak + dead) / max(1, len(self.sat))
        return {"avg": avg, "free": free, "builder": builder, "beacon": beacon, "dead": dead, "weak": weak, "instability": instability}

    def visualize_influence(self):
        # clear old
        for l in self.links:
            l.visible = False
        self.links.clear()
        # draw links from alpha to low-fuel satellites
        for s in self.sat:
            if s.fuel < T_LOW and s.status != "dead":
                self.links.append(curve(pos=[self.visual.pos, s.pos], color=COLORS["alpha"], radius=0.05, opacity=0.3))

    def regulate(self, frame):
        self.counter += 1
        tm = self.telemetry()

        # move alpha visual to swarm center slowly
        center = sum([s.pos for s in self.sat], vector(0,0,0)) / len(self.sat)
        self.visual.pos = self.visual.pos * 0.95 + center * 0.05

        # If instability high, expand bond radius and prompt restructure
        if tm["instability"] > 0.25:
            self.bond_radius = min(80, self.bond_radius + 2)
            # force some builders to disband if present
            if tm["builder"] > 0 and random.random() < 0.2:
                self.force_restructure()
        else:
            self.bond_radius = max(6, self.bond_radius - 0.5)

        # if many dead, trigger prioritized rescues
        if tm["dead"] > 0 and random.random() < 0.5:
            self.prioritize_rescue()

        # visual influence
        self.visualize_influence()

        # occasional gentle pull of free satellites toward unbuilt targets to encourage building
        if frame % 40 == 0:
            self.pull_toward_targets()

        # try forming triplets periodically (Alpha controls interval)
        if frame - self.last_triplet_frame > self.triplet_interval_frames:
            trip = form_triplet(self.bond_radius)
            if trip:
                self.last_triplet_frame = frame
                # optionally mark their last action
                for s in trip:
                    s.last_action = frame

    def force_restructure(self):
        # choose some builders, convert them to returning, convert their beacons to beacons (already)
        builders = [s for s in self.sat if s.status == "builder"]
        if not builders:
            return
        sample = random.sample(builders, min(2, len(builders)))
        for b in sample:
            pair = b.beacon_pair
            if pair:
                commander, reserver = pair
                commander.status = "beacon"
                reserver.status = "beacon"
                commander.role = "commander"
                reserver.role = "reserver"
                commander.sphere.color = COLORS["commander"]
                reserver.sphere.color = COLORS["reserver"]
            b.status = "returning"
            b.beacon_pair = None
            b.sphere.color = COLORS["returning"]

    def prioritize_rescue(self):
        dead = [s for s in self.sat if s.status == "dead"]
        free = [s for s in self.sat if s.status == "free" and s.fuel > T_LOW]
        for victim in dead[:min(3, len(dead))]:
            if not free:
                break
            rescuer = min(free, key=lambda s: mag(s.pos - victim.pos))
            rescuer.status = "rescue"
            rescuer.target = victim
            rescuer.sphere.color = COLORS["rescue"]
            free.remove(rescuer)

    def pull_toward_targets(self):
        # find unbuilt targets, pick some free sats and nudge them toward nearest targets
        unbuilt = [t for t in target_spheres if not t["built"]]
        if not unbuilt:
            return
        free = [s for s in self.sat if s.status == "free"]
        random.shuffle(free)
        for s in free[:min(len(free), len(unbuilt))]:
            nearest = min(unbuilt, key=lambda t: mag(t["pos"] - s.pos))
            # nudging velocity
            dir = norm(nearest["pos"] - s.pos)
            s.vel = s.vel * 0.6 + dir * 0.4

# === Triplet formation ===
def form_triplet(bond_radius=BOND_RADIUS):
    free = [s for s in satellites if s.status == "free" and s.fuel >= T_LOW]
    if len(free) < 3:
        return None
    s1 = random.choice(free)
    neighbors = [s for s in free if s is not s1 and mag(s.pos - s1.pos) <= bond_radius]
    if len(neighbors) < 2:
        return None
    neighbors.sort(key=lambda s: mag(s.pos - s1.pos))
    s2, s3 = neighbors[0], neighbors[1]
    triplet = [s1, s2, s3]
    # assign roles
    s1.status = "builder"
    s2.status = "beacon"
    s3.status = "beacon"
    # role by fuel
    if s2.fuel < s3.fuel:
        s2.role = "commander"
        s3.role = "reserver"
    else:
        s2.role = "reserver"
        s3.role = "commander"
    # beacons fixed
    s2.vel = vector(0,0,0)
    s3.vel = vector(0,0,0)
    s1.beacon_pair = [s2, s3]
    # cost
    for s in triplet:
        s.fuel -= T_LOW * 0.2
    # color update
    s1.sphere.color = COLORS["builder"]
    s2.sphere.color = COLORS[s2.role]
    s3.sphere.color = COLORS[s3.role]
    return triplet

# === Refuel builder from reserver ===
def refuel_builder(builder):
    if not builder.beacon_pair:
        return False
    commander, reserver = builder.beacon_pair
    if reserver.fuel > F_TOTAL * 0.33:
        transfer = min(F_MAX_SHARE, reserver.fuel * 0.5)
        transfer = min(transfer, reserver.fuel - T_CRITICAL)
        if transfer <= 0:
            return False
        reserver.fuel -= transfer
        builder.fuel = min(builder.fuel + transfer, F_TOTAL)
        # reevaluate roles
        if commander.fuel < reserver.fuel:
            commander.role, reserver.role = reserver.role, commander.role
            commander.sphere.color = COLORS[commander.role]
            reserver.sphere.color = COLORS[reserver.role]
        return True
    else:
        return False

# === Building logic: builders occupy nearest unbuilt target ===
def building_step():
    for s in satellites:
        if s.status == "builder" and s.beacon_pair:
            # find nearest unbuilt target
            unbuilt = [t for t in target_spheres if not t["built"]]
            if not unbuilt:
                # nothing to build: builder returns
                s.status = "returning"
                s.beacon_pair = None
                continue
            nearest = min(unbuilt, key=lambda t: mag(t["pos"] - s.pos))
            # move to it
            s.move_to(nearest["pos"])
            # if arrived, mark built
            if mag(s.pos - nearest["pos"]) < 1.0:
                nearest["built"] = True
                nearest["sphere"].color = color.white
                nearest["sphere"].opacity = 0.9
                # occupy by builder briefly
                nearest["builder"] = s
                # small fuel cost for construction
                s.fuel = max(0, s.fuel - 5)
                # After building few points, builder may return or continue
                # simple rule: if builder fuel low -> request refuel
                if s.fuel < T_LOW:
                    if not refuel_builder(s):
                        s.status = "returning"
                        s.beacon_pair = None

# === INIT ===
satellites = [Satellite(i) for i in range(NUM_SATELLITES)]
alpha = AlphaAI(satellites)

# initial triplet
form_triplet(BOND_RADIUS)

# main loop
frame = 0
while True:
    rate(60)
    frame += 1

    # alpha regulate
    alpha.regulate(frame)

    # each sat step
    for s in satellites:
        s.step()

    # building action
    building_step()

    # periodically attempt triplet formation too (Alpha also triggers)
    if frame % 240 == 0:
        form_triplet(alpha.bond_radius)

    # end condition: all targets built
    if all(t["built"] for t in target_spheres):
        msg = f"Construction of '{letter}' completed!"
        print(msg)
        # show floating text
        txt = label(pos=vector(0, max(t["pos"].y for t in target_spheres)+6, 0),
                    text=msg, height=24, color=color.green, box=False)
        break
