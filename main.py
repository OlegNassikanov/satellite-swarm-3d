# swarm3d_alpha_v06.py
# Swarm 3D v0.6 — Improved Alpha AI + construction
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
BUILD_SCALE = 1.0
ARRIVAL_RADIUS = 2.5

# New parameters for improvements
PRIORITY_WEIGHT = 0.7
DISTANCE_WEIGHT = 0.3
STRATEGY_CHANGE_INTERVAL = 600  # Increased from 300
STATIONED_CHANCE = 0.3
GOAL_REVISION_INTERVAL = 30     # Frames between goal reconsideration
MIN_RESCUE_FUEL = 10           # Minimum fuel for rescue transfer

# === SCENE ===
scene = canvas(title="Swarm 3D v0.6 — Improved Alpha AI + Construction",
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
    "alpha": vector(0.6, 0.2, 0.8),
    "target": vector(1, 0.6, 0.2),
    "stationed": vector(0, 1, 0.5)
}

# prompt for letter
letter = input("Enter an uppercase English letter to build (A for now) [default A]: ").strip().upper()
if not letter:
    letter = "A"

# === Priority calculation strategies ===
BUILD_STRATEGIES = {
    "bottom_up": lambda pos: -pos.y,
    "top_down": lambda pos: pos.y,
    "left_right": lambda pos: pos.x,
    "center_out": lambda pos: -mag(pos),
    "random": lambda pos: random.random()
}

current_strategy = "bottom_up"

def calculate_priority(pos, strategy="bottom_up"):
    """Calculate priority based on strategy"""
    return BUILD_STRATEGIES.get(strategy, BUILD_STRATEGIES["bottom_up"])(pos)

# helper: generate target points
def generate_letter_points(letter_char, scale=BUILD_SCALE, spacing=2.5):
    """Generate points for letter construction"""
    pts = []
    s = scale * spacing * 1.0
    
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
        # crossbar
        for i in range(-2, 3):
            x = i * s
            y = 0
            pts.append(vector(x, y, 0))
        # interior fill
        for rx in [-1, 0, 1]:
            for ry in [1, 2, 3]:
                pts.append(vector(rx * s, ry * s - height/2 + 2*s, 0))
    else:
        # fallback: rectangle
        w = 8 * s
        h = 10 * s
        steps = 14
        for i in range(steps+1):
            t = i/steps
            pts.append(vector(-w/2 + t*w, -h/2, 0))
            pts.append(vector(-w/2 + t*w, h/2, 0))
            pts.append(vector(-w/2, -h/2 + t*h, 0))
            pts.append(vector(w/2, -h/2 + t*h, 0))
    
    # deduplicate
    uniq = []
    seen = set()
    for p in pts:
        key = (round(p.x,2), round(p.y,2))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq

# generate targets with 1:15 scale
SCALE_1_15 = 15.0
targets = generate_letter_points(letter, scale=BUILD_SCALE, spacing=1.2)
targets = [vector(p.x * SCALE_1_15, p.y * SCALE_1_15, p.z * SCALE_1_15) for p in targets]

# Calculate priority range for color normalization
priorities = [calculate_priority(t, current_strategy) for t in targets]
min_priority = min(priorities) if priorities else 0
max_priority = max(priorities) if priorities else 1
priority_range = max_priority - min_priority if max_priority != min_priority else 1

# visualize target points with priority-based colors
target_spheres = []
for i, t in enumerate(targets):
    priority = priorities[i]
    # Normalize priority for color
    norm_priority = (priority - min_priority) / priority_range
    color_gradient = vector(0.3 + norm_priority*0.5, 0.4, 0.9 - norm_priority*0.4)
    
    spt = sphere(pos=t, radius=0.35, color=color_gradient, opacity=0.25)
    target_spheres.append({
        "pos": t, 
        "sphere": spt, 
        "built": False, 
        "builder": None,
        "locked": False,
        "priority": priority,
        "build_progress": 0.0
    })

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
        self.label = label(pos=self.pos + vector(0,1.5,0), text=str(int(F_TOTAL)), 
                          height=10, color=color.white, box=False)
        self.fuel = F_TOTAL
        self.status = "free"
        self.role = None
        self.target = None
        self.beacon_pair = None
        self.last_action = 0
        self.last_goal_revision = 0

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
        self.update_label()

    def random_roam(self):
        self.pos += norm(self.vel) * SPEED
        self.sphere.pos = self.pos
        self.update_label()

    def step(self):
        # stationed satellites don't move (holding position)
        if self.status == "stationed":
            self.fuel -= ICE_CONSUMPTION * 0.01
            self.sphere.pos = self.pos
            self.update_label()
            if self.fuel <= 0:
                self.status = "dead"
                self.sphere.color = COLORS["dead"]
            return
        
        # beacons: fixed, minimal drain
        if self.status == "beacon":
            self.fuel -= ICE_CONSUMPTION * 0.02
            self.sphere.pos = self.pos
            self.update_label()
            if self.fuel <= 0:
                self.status = "dead"
                self.sphere.color = COLORS["dead"]
            return

        if self.status == "builder":
            if self.beacon_pair:
                center = (self.beacon_pair[0].pos + self.beacon_pair[1].pos) / 2
                self.move_to(center)
        elif self.status == "rescue" and self.target:
            self.move_to(self.target.pos)
        elif self.status in ["returning", "weak"]:
            self.move_to(BASE_POS)
        elif self.status == "free":
            self.random_roam()

        # boundaries
        for axis in ['x','y','z']:
            val = getattr(self.pos, axis)
            if abs(val) > 60:
                setattr(self.vel, axis, -getattr(self.vel, axis))
        
        # fuel consumption
        if self.status not in ["beacon", "stationed"]:
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
        
        # returning to base logic
        if self.status == "returning" and mag(self.pos - BASE_POS) < 3:
            self.fuel = F_TOTAL
            self.status = "free"
            self.vel = vector(random.uniform(-1, 1), random.uniform(-0.3, 0.3), random.uniform(-1, 1))
            self.role = None
            self.beacon_pair = None
            self.sphere.color = COLORS["free"]
        
        # improved rescue logic
        if self.status == "rescue" and self.target and mag(self.pos - self.target.pos) < 3:
            if self.fuel >= MIN_RESCUE_FUEL:
                transfer = min(MIN_RESCUE_FUEL, self.fuel // 2, F_TOTAL - self.target.fuel)
                if transfer > 0:
                    self.fuel -= transfer
                    self.target.fuel = min(self.target.fuel + transfer, F_TOTAL)
                    if self.target.fuel > T_CRITICAL:
                        self.target.status = "free"
                        self.target.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                        self.target.sphere.color = COLORS["free"]
                    self.status = "returning"
                    self.target = None
                    self.sphere.color = COLORS["returning"]
        
        # update colors
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

# Improved Alpha AI
class AlphaAI:
    def __init__(self, satellites):
        self.sat = satellites
        self.visual = sphere(pos=BASE_POS + vector(0, -5, 0), radius=1.0, 
                           color=COLORS["alpha"], emissive=True, opacity=0.6)
        self.links = []
        self.counter = 0
        self.bond_radius = BOND_RADIUS
        self.triplet_interval_frames = 120
        self.last_triplet_frame = -999
        self.build_strategy = "bottom_up"
        self.last_strategy_change = 0

    def telemetry(self):
        total = sum(s.fuel for s in self.sat)
        avg = total / len(self.sat)
        free = len([s for s in self.sat if s.status == "free"])
        builder = len([s for s in self.sat if s.status == "builder"])
        beacon = len([s for s in self.sat if s.status == "beacon"])
        stationed = len([s for s in self.sat if s.status == "stationed"])
        dead = len([s for s in self.sat if s.status == "dead"])
        weak = len([s for s in self.sat if s.status == "weak"])
        instability = (weak + dead) / max(1, len(self.sat))
        completion = sum(1 for t in target_spheres if t["built"]) / max(1, len(target_spheres))
        return {
            "avg": avg, "free": free, "builder": builder, "beacon": beacon,
            "stationed": stationed, "dead": dead, "weak": weak, 
            "instability": instability, "completion": completion
        }

    def visualize_influence(self):
        for l in self.links:
            l.visible = False
        self.links.clear()
        for s in self.sat:
            if s.fuel < T_LOW and s.status != "dead":
                self.links.append(curve(pos=[self.visual.pos, s.pos], 
                                      color=COLORS["alpha"], radius=0.05, opacity=0.3))

    def regulate(self, frame):
        global current_strategy
        self.counter += 1
        tm = self.telemetry()

        # move alpha to swarm center
        center = sum([s.pos for s in self.sat], vector(0,0,0)) / len(self.sat)
        self.visual.pos = self.visual.pos * 0.95 + center * 0.05

        # Improved strategy switching with longer intervals
        if frame - self.last_strategy_change > STRATEGY_CHANGE_INTERVAL:
            if tm["completion"] < 0.3:
                self.build_strategy = "bottom_up"
            elif tm["completion"] < 0.6:
                self.build_strategy = "center_out"
            else:
                self.build_strategy = "random"
            
            # recalculate priorities
            for t in target_spheres:
                t["priority"] = calculate_priority(t["pos"], self.build_strategy)
            current_strategy = self.build_strategy
            self.last_strategy_change = frame

        # instability handling
        if tm["instability"] > 0.25:
            self.bond_radius = min(80, self.bond_radius + 2)
            if tm["builder"] > 0 and random.random() < 0.2:
                self.force_restructure()
        else:
            self.bond_radius = max(6, self.bond_radius - 0.5)

        # rescue dead
        if tm["dead"] > 0 and random.random() < 0.5:
            self.prioritize_rescue()

        # check for stuck builders
        if tm["builder"] == 0 and tm["completion"] < 1.0 and tm["free"] >= 3:
            if frame % 100 == 0:
                print(f"[Alpha] No builders at {tm['completion']*100:.1f}% completion. Forming new triplet...")
                form_triplet(self.bond_radius)

        # Reactivate stationed satellites if needed
        if tm["free"] < 5 and tm["stationed"] > 0 and tm["completion"] < 1.0:
            stationed_sats = [s for s in self.sat if s.status == "stationed"]
            for s in stationed_sats[:min(3, len(stationed_sats))]:
                s.status = "free"
                s.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                s.sphere.color = COLORS["free"]
                if frame % 60 == 0:
                    print(f"[Alpha] Reactivated stationed satellite {s.idx}")

        self.visualize_influence()

        # pull free sats toward targets
        if frame % 40 == 0:
            self.pull_toward_targets()

        # periodic triplet formation
        if frame - self.last_triplet_frame > self.triplet_interval_frames:
            trip = form_triplet(self.bond_radius)
            if trip:
                self.last_triplet_frame = frame

    def force_restructure(self):
        builders = [s for s in self.sat if s.status == "builder"]
        if not builders:
            return
        sample = random.sample(builders, min(2, len(builders)))
        for b in sample:
            pair = b.beacon_pair
            if pair:
                commander, reserver = pair
                # Free the beacons instead of keeping them as beacons
                commander.status = "free"
                reserver.status = "free"
                commander.role = None
                reserver.role = None
                commander.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                reserver.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                commander.sphere.color = COLORS["free"]
                reserver.sphere.color = COLORS["free"]
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
        unbuilt = [t for t in target_spheres if not t["built"] and not t["locked"]]
        if not unbuilt:
            return
        free = [s for s in self.sat if s.status == "free"]
        # Sort targets by priority (highest first)
        unbuilt.sort(key=lambda t: t["priority"], reverse=True)
        random.shuffle(free)
        for s in free[:min(len(free), len(unbuilt))]:
            # Assign to highest priority targets first
            target = unbuilt.pop(0)
            dir = norm(target["pos"] - s.pos)
            s.vel = s.vel * 0.6 + dir * 0.4
            if not unbuilt:
                break

# === Improved triplet formation ===
def form_triplet(bond_radius=BOND_RADIUS):
    free = [s for s in satellites if s.status == "free" and s.fuel >= T_LOW]
    if len(free) < 3:
        return None
    
    # Try to form triplets near unbuilt targets
    unbuilt_targets = [t for t in target_spheres if not t["built"]]
    if unbuilt_targets:
        # Pick a random unbuilt target area
        target_area = random.choice(unbuilt_targets)["pos"]
        # Find satellites near target area
        near_target = [s for s in free if mag(s.pos - target_area) < bond_radius * 2]
        if len(near_target) >= 3:
            free = near_target
    
    s1 = random.choice(free)
    neighbors = [s for s in free if s is not s1 and mag(s.pos - s1.pos) <= bond_radius]
    if len(neighbors) < 2:
        return None
    neighbors.sort(key=lambda s: mag(s.pos - s1.pos))
    s2, s3 = neighbors[0], neighbors[1]
    triplet = [s1, s2, s3]
    
    s1.status = "builder"
    s2.status = "beacon"
    s3.status = "beacon"
    
    if s2.fuel < s3.fuel:
        s2.role = "commander"
        s3.role = "reserver"
    else:
        s2.role = "reserver"
        s3.role = "commander"
    
    s2.vel = vector(0,0,0)
    s3.vel = vector(0,0,0)
    s1.beacon_pair = [s2, s3]
    
    for s in triplet:
        s.fuel -= T_LOW * 0.2
    
    s1.sphere.color = COLORS["builder"]
    s2.sphere.color = COLORS[s2.role]
    s3.sphere.color = COLORS[s3.role]
    return triplet

# === Improved refuel ===
def refuel_builder(builder):
    if not builder.beacon_pair:
        return False
    commander, reserver = builder.beacon_pair
    
    # Use the beacon with more fuel for refueling
    donor = commander if commander.fuel > reserver.fuel else reserver
    if donor.fuel > F_TOTAL * 0.33:
        transfer = min(F_MAX_SHARE, donor.fuel * 0.5)
        transfer = min(transfer, donor.fuel - T_CRITICAL)
        if transfer <= 0:
            return False
        donor.fuel -= transfer
        builder.fuel = min(builder.fuel + transfer, F_TOTAL)
        
        # Switch roles if commander has less fuel than reserver
        if commander.fuel < reserver.fuel:
            commander.role, reserver.role = reserver.role, commander.role
            commander.sphere.color = COLORS[commander.role]
            reserver.sphere.color = COLORS[reserver.role]
        return True
    return False

# === Improved collision check ===
def check_collision_path(s, target_dict):
    """Check if another builder is already targeting this point"""
    for other in satellites:
        if (other.status == "builder" and other is not s and 
            other.target == target_dict):
            my_dist = mag(s.pos - target_dict["pos"])
            other_dist = mag(other.pos - target_dict["pos"])
            if other_dist < my_dist:
                return True
    return False

# === Improved building logic ===
def building_step(frame):
    # First, clean up any locked targets that have dead or non-builder owners
    for t in target_spheres:
        if t["locked"] and (t["builder"] is None or t["builder"].status != "builder"):
            t["locked"] = False
            t["builder"] = None
    
    for s in satellites:
        if s.status == "builder" and s.beacon_pair:
            # If builder already has a target and it's still valid, keep it
            if (s.target is not None and not s.target["built"] and 
                s.target["builder"] is s and s.target["locked"] and
                frame - s.last_goal_revision < GOAL_REVISION_INTERVAL):
                # Keep current target
                target_dict = s.target
            else:
                # Find new target
                unbuilt = [t for t in target_spheres 
                          if not t["built"] and not t["locked"]]
                
                if not unbuilt:
                    # No targets left, return to base
                    s.status = "returning"
                    # Free the beacons
                    if s.beacon_pair:
                        for beacon in s.beacon_pair:
                            beacon.status = "free"
                            beacon.role = None
                            beacon.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                            beacon.sphere.color = COLORS["free"]
                    s.beacon_pair = None
                    s.target = None
                    continue
                
                # Improved scoring with configurable weights
                def score(t):
                    dist = mag(t["pos"] - s.pos)
                    return t["priority"] * PRIORITY_WEIGHT - dist * DISTANCE_WEIGHT
                
                # Sort by score (higher is better)
                unbuilt.sort(key=score, reverse=True)
                
                # Find the best available target
                target_dict = None
                for candidate in unbuilt:
                    if not check_collision_path(s, candidate):
                        target_dict = candidate
                        break
                
                if target_dict is None:
                    # All good targets are taken, try next best
                    target_dict = unbuilt[0]
                
                # Lock the target
                target_dict["locked"] = True
                target_dict["builder"] = s
                s.target = target_dict
                s.last_goal_revision = frame
            
            # Move to target
            s.move_to(target_dict["pos"])
            
            # Gradual construction animation
            dist = mag(s.pos - target_dict["pos"])
            if dist < ARRIVAL_RADIUS:
                target_dict["build_progress"] += 0.05
                target_dict["sphere"].opacity = 0.25 + target_dict["build_progress"] * 0.65
                
                if target_dict["build_progress"] >= 1.0:
                    # Construction complete
                    target_dict["built"] = True
                    target_dict["locked"] = False
                    target_dict["builder"] = None
                    target_dict["sphere"].color = color.white
                    target_dict["sphere"].opacity = 0.95
                    s.fuel -= 5
                    s.target = None
                    
                    # Station builder or continue building
                    if random.random() < STATIONED_CHANCE:
                        s.status = "stationed"
                        s.pos = target_dict["pos"]
                        s.vel = vector(0,0,0)
                        s.sphere.color = COLORS["stationed"]
                        # Free the beacons
                        if s.beacon_pair:
                            for beacon in s.beacon_pair:
                                beacon.status = "free"
                                beacon.role = None
                                beacon.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                                beacon.sphere.color = COLORS["free"]
                            s.beacon_pair = None
                    
                    # Refuel check
                    if s.fuel < T_LOW and s.status != "stationed":
                        if not refuel_builder(s):
                            s.status = "returning"
                            # Free the beacons
                            if s.beacon_pair:
                                for beacon in s.beacon_pair:
                                    beacon.status = "free"
                                    beacon.role = None
                                    beacon.vel = vector(random.uniform(-1,1), random.uniform(-0.3,0.3), random.uniform(-1,1))
                                    beacon.sphere.color = COLORS["free"]
                                s.beacon_pair = None

# === INIT ===
satellites = [Satellite(i) for i in range(NUM_SATELLITES)]
alpha = AlphaAI(satellites)

form_triplet(BOND_RADIUS)

# stats label
stats_label = label(pos=vector(0, -40, 0), text="", height=12, color=color.white, box=False)

# main loop
frame = 0
completion_announced = False

print(f"Starting construction of letter '{letter}'...")
print(f"Total target points: {len(target_spheres)}")

while True:
    rate(60)
    frame += 1

    alpha.regulate(frame)

    for s in satellites:
        s.step()

    building_step(frame)

    # periodic triplet formation
    if frame % 240 == 0:
        form_triplet(alpha.bond_radius)

    # stats update
    tm = alpha.telemetry()
    stats_label.text = f"Progress: {tm['completion']*100:.1f}% | Strategy: {alpha.build_strategy} | Builders: {tm['builder']} | Free: {tm['free']} | Stationed: {tm['stationed']} | Dead: {tm['dead']}"
    stats_label.pos = vector(0, -35, 0)

    # completion check
    if tm["completion"] >= 1.0 and not completion_announced:
        msg = f"🎉 Construction of '{letter}' completed! 🎉"
        print(msg)
        print(f"Total frames: {frame} (~{frame/60:.1f} seconds)")
        completion_y = max(t["pos"].y for t in target_spheres) + 8 if target_spheres else 20
        txt = label(pos=vector(0, completion_y, 0),
                   text=msg, height=20, color=color.green, box=True, opacity=0.8)
        completion_announced = True

    # Handle weak satellites seeking help from reservers
    weak = [s for s in satellites if s.status == "weak"]
    for w in weak:
        reservers = [s for s in satellites 
                    if s.status == "beacon" and s.role == "reserver" and s.fuel > F_TOTAL * 0.33]
        if reservers:
            nearest = min(reservers, key=lambda r: mag(r.pos - w.pos))
            if mag(w.pos - nearest.pos) < 3:
                transfer = min(F_MAX_SHARE, nearest.fuel - T_CRITICAL)
                if transfer > 0:
                    nearest.fuel -= transfer
                    w.fuel = min(w.fuel + transfer, F_TOTAL)
                    w.status = "free"
                    w.sphere.color = COLORS["free"]