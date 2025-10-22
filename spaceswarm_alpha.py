# spaceswarm_alpha.py
import pygame
import random
import math
import time

# === Параметры сцены ===
WIDTH, HEIGHT = 800, 600
NUM_SATELLITES = 30
SAT_RADIUS = 5

# === Топливо и пороги ===
F_TOTAL = 100           # Полный запас топлива
T_LOW = 30              # Порог низкого топлива (для участия в триплете)
T_CRITICAL = 15         # Критический порог (weak)
F_MAX_SHARE = F_TOTAL / 3  # Макс. передача топлива
ICE_CONSUMPTION = 0.1
SPEED = 1

# === Цвета ===
WHITE = (255, 255, 255)
GREY = (100, 100, 100)
BLUE = (100, 100, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
DARK = (30, 30, 30)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Swarm + Alpha AI")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 18)

# === Глобальные параметры формирования (Alpha может менять) ===
BOND_RADIUS = 200            # радиус поиска ближайших для формирования триплета
TRIPLET_INTERVAL = 2000      # минимальный интервал (ms) между попытками формирования триплетов

# === Хуки / колбеки (Alpha подписывается на события) ===
class EventBus:
    def __init__(self):
        self._hooks = {}

    def on(self, name, fn):
        if name not in self._hooks:
            self._hooks[name] = []
        self._hooks[name].append(fn)

    def emit(self, name, *args, **kwargs):
        for fn in self._hooks.get(name, []):
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

event_bus = EventBus()

# === Класс спутника ===
class Satellite:
    def __init__(self):
        self.x = random.uniform(0, WIDTH)
        self.y = random.uniform(0, HEIGHT)
        self.dx = random.uniform(-1, 1)
        self.dy = random.uniform(-1, 1)
        self.fuel = F_TOTAL
        self.status = "free"      # free, builder, beacon, returning, rescue, weak, dead
        self.role = None          # commander / reserver / None
        self.target = None        # target satellite (for rescue) или None
        self.beacon_pair = None   # [commander, reserver] for builder
        self.last_triplet_at = 0  # timestamp

    def move(self):
        # Beacon фиксирован: не двигается (role==commander/reserver => status='beacon')
        if self.status == "beacon":
            return

        # Builder moves toward center between its beacons
        if self.status == "builder" and self.beacon_pair:
            commander, reserver = self.beacon_pair
            tx = (commander.x + reserver.x) / 2
            ty = (commander.y + reserver.y) / 2
            self.move_to(tx, ty)
        elif self.status == "rescue" and self.target:
            # move towards target
            self.move_to(self.target.x, self.target.y)
        elif self.status in ["returning", "weak"]:
            # go to base (center)
            self.move_to(WIDTH / 2, HEIGHT / 2)
        else:
            # free or other: roam
            self.x += self.dx * SPEED
            self.y += self.dy * SPEED

        # bound
        if self.x < 0 or self.x > WIDTH:
            self.dx *= -1
            self.x = max(0, min(self.x, WIDTH))
        if self.y < 0 or self.y > HEIGHT:
            self.dy *= -1
            self.y = max(0, min(self.y, HEIGHT))

        # fuel consumption
        if self.status != "beacon":  # beacon is stationary and doesn't consume (or consumes very little)
            self.fuel -= ICE_CONSUMPTION
        else:
            # small passive drain for beacons
            self.fuel -= ICE_CONSUMPTION * 0.02

        # transitions
        if self.fuel <= 0 and self.status != "dead":
            self.status = "dead"
            self.dx = self.dy = 0
        elif self.status == "free" and self.fuel < T_CRITICAL:
            self.status = "weak"

    def move_to(self, tx, ty):
        dx = tx - self.x
        dy = ty - self.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        self.dx = dx / dist
        self.dy = dy / dist
        # step
        self.x += self.dx * SPEED
        self.y += self.dy * SPEED

    def draw(self):
        # choose color
        if self.status == "free":
            color = WHITE
        elif self.status == "builder":
            color = BLUE
        elif self.status == "returning":
            color = GREEN
        elif self.status == "dead":
            color = RED
        elif self.status == "rescue":
            color = YELLOW
        elif self.status == "weak":
            color = GREY
        elif self.role == "commander":
            color = CYAN
        elif self.role == "reserver":
            color = (0, 200, 200)
        elif self.status == "beacon":
            color = (0, 180, 180)
        else:
            color = DARK

        pygame.draw.circle(screen, color, (int(self.x), int(self.y)), SAT_RADIUS)
        fuel_text = font.render(f"{int(self.fuel)}", True, WHITE)
        screen.blit(fuel_text, (self.x + SAT_RADIUS + 2, self.y - SAT_RADIUS - 2))

# === Swarm + operations ===
satellites = [Satellite() for _ in range(NUM_SATELLITES)]
last_triplet_try = 0

def find_dead():
    return [s for s in satellites if s.status == "dead"]

def find_free():
    return [s for s in satellites if s.status == "free" and s.fuel >= T_LOW]

def find_beacons():
    return [s for s in satellites if s.status == "beacon" and s.role in ("commander","reserver")]

def find_weak():
    return [s for s in satellites if s.status == "weak"]

def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)

def form_triplet(bond_radius=BOND_RADIUS):
    """
    Попытка сформировать триплет в радиусе bond_radius.
    Alpha контролирует bond_radius и TRIPLET_INTERVAL.
    Возвращает сформированный triplet list или None.
    """
    free = find_free()
    if len(free) < 3:
        return None

    # pick random seed and find 2 nearest within radius
    s1 = random.choice(free)
    neighbors = [s for s in free if s is not s1 and distance(s1, s) <= bond_radius]
    if len(neighbors) < 2:
        return None
    neighbors.sort(key=lambda s: distance(s1, s))
    s2, s3 = neighbors[0], neighbors[1]
    triplet = [s1, s2, s3]

    # roles: builder is s1, others become beacons (stationary)
    s1.status = "builder"
    s2.status = "beacon"
    s3.status = "beacon"

    # assign commander/reserver by fuel levels
    if s2.fuel < s3.fuel:
        s2.role = "commander"
        s3.role = "reserver"
    else:
        s2.role = "reserver"
        s3.role = "commander"

    # fix beacon velocities (stay)
    s2.dx = s2.dy = 0
    s3.dx = s3.dy = 0

    # link builder to beacons
    s1.beacon_pair = [s2, s3]

    # cost for formation
    for s in triplet:
        s.fuel -= T_LOW * 0.2

    # set last_triplet_at
    ts = pygame.time.get_ticks()
    for s in triplet:
        s.last_triplet_at = ts

    event_bus.emit("triplet_created", triplet)
    return triplet

def refuel_builder(builder):
    """Попытка резервера передать топливо билдиру."""
    if not builder.beacon_pair:
        return False
    commander, reserver = builder.beacon_pair
    if reserver.fuel > F_TOTAL * 0.33:
        # передать
        fuel_transfer = min(F_MAX_SHARE, reserver.fuel * 0.5)
        # don't starve reserver below threshold
        fuel_transfer = min(fuel_transfer, reserver.fuel - T_CRITICAL)
        if fuel_transfer <= 0:
            return False
        reserver.fuel -= fuel_transfer
        builder.fuel = min(builder.fuel + fuel_transfer, F_TOTAL)
        event_bus.emit("fuel_transferred", reserver, builder, fuel_transfer)
        # re-evaluate roles
        if commander.fuel < reserver.fuel:
            commander.role, reserver.role = reserver.role, commander.role
        return True
    else:
        # not enough fuel
        return False

# === Alpha AI ===
class AlphaAI:
    def __init__(self, satellites, event_bus):
        self.sat = satellites
        self.bus = event_bus
        self.last_regulate = 0
        self.reg_interval = 1000  # ms
        self.bond_radius = BOND_RADIUS
        self.triplet_interval = TRIPLET_INTERVAL
        self.instability_threshold = 0.25  # fraction weak+dead triggers restructure
        self.min_free_for_triplet = 3
        # subscribe to events
        self.bus.on("triplet_created", self.on_triplet_created)
        self.bus.on("fuel_transferred", self.on_fuel_transferred)

    def telemetry(self):
        total = sum(s.fuel for s in self.sat)
        avg_fuel = total / len(self.sat)
        free_count = len([s for s in self.sat if s.status == "free"])
        builder_count = len([s for s in self.sat if s.status == "builder"])
        beacon_count = len([s for s in self.sat if s.status == "beacon"])
        dead_count = len([s for s in self.sat if s.status == "dead"])
        weak_count = len([s for s in self.sat if s.status == "weak"])
        instability = (weak_count + dead_count) / max(1, len(self.sat))
        return {
            "avg_fuel": avg_fuel,
            "free_count": free_count,
            "builder_count": builder_count,
            "beacon_count": beacon_count,
            "dead_count": dead_count,
            "weak_count": weak_count,
            "instability": instability
        }

    def regulate(self):
        now = pygame.time.get_ticks()
        if now - self.last_regulate < self.reg_interval:
            return
        self.last_regulate = now

        tm = self.telemetry()
        # Simple rules:
        # if many weak/dead => increase bond radius to gather more units
        if tm["instability"] > self.instability_threshold:
            self.bond_radius = min(WIDTH, self.bond_radius + 30)
            self.triplet_interval = max(500, self.triplet_interval - 200)  # try form more frequently
            # also trigger restructure to free beacons
            if tm["builder_count"] > 0:
                self.trigger_restructure()
        else:
            # stabilize: slowly decrease bond radius back to default, reduce formation rate
            self.bond_radius = max(100, self.bond_radius - 10)
            self.triplet_interval = min(4000, self.triplet_interval + 100)

        # if too few free units, lower requirement for T_LOW to allow more join
        if tm["free_count"] < 5:
            # decrease T_LOW effectively by signaling more permissive formation
            pass  # we can implement adaptively later

        # prioritize rescues if dead present
        if tm["dead_count"] > 0:
            self.prioritize_rescue()

        # debug print
        # print("[Alpha] telemetry:", tm, "bond_radius:", self.bond_radius, "triplet_interval:", self.triplet_interval)

    def on_triplet_created(self, triplet):
        # quick reaction: when triplet created, we may mark nearby free units to avoid interference
        # for now, no-op, but hook exists
        pass

    def on_fuel_transferred(self, reserver, builder, amount):
        # Alpha can reward reserver or mark statistics
        # no-op now
        pass

    def trigger_restructure(self):
        """Force some builders to disband into beacons to create stability."""
        builders = [s for s in self.sat if s.status == "builder"]
        if not builders:
            return
        # pick some builder groups to split
        for b in random.sample(builders, min(2, len(builders))):
            pair = b.beacon_pair
            if pair and len(pair) == 2:
                commander, reserver = pair
                # make them beacons (already likely), ensure their roles set
                commander.status = "beacon"
                reserver.status = "beacon"
                commander.role = "commander"
                reserver.role = "reserver"
                # set builder to returning
                b.status = "returning"
                b.beacon_pair = None
                # small fuel penalty/regain
                b.fuel = max(0, b.fuel - 5)

    def prioritize_rescue(self):
        """Assign nearest free sattelites to rescue dead ones."""
        dead = find_dead()
        if not dead:
            return
        free = [s for s in self.sat if s.status == "free" and s.fuel > T_LOW]
        for victim in dead:
            if not free:
                break
            rescuer = min(free, key=lambda s: math.hypot(s.x - victim.x, s.y - victim.y))
            rescuer.status = "rescue"
            rescuer.target = victim
            free.remove(rescuer)

# === Инициализация Alpha ===
alpha = AlphaAI(satellites, event_bus)

# === Main loop ===
running = True
clock = pygame.time.Clock()
last_triplet_try = 0

while running:
    dt = clock.tick(30)
    now = pygame.time.get_ticks()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            x, y = event.pos
            # click to kill a sat for testing
            for s in satellites:
                if math.hypot(s.x - x, s.y - y) < SAT_RADIUS + 2:
                    s.status = "dead"
                    s.fuel = 0

    # move & basic behaviors
    dead = find_dead()
    free = find_free()
    beacons = find_beacons()
    weak = find_weak()

    for s in satellites:
        s.move()

        # when returning to base
        if s.status == "returning" and math.hypot(s.x - WIDTH/2, s.y - HEIGHT/2) < 10:
            s.fuel = F_TOTAL
            s.status = "free"
            s.dx = random.uniform(-1, 1)
            s.dy = random.uniform(-1, 1)
            s.role = None
            s.beacon_pair = None

        # rescue arrival
        if s.status == "rescue" and s.target and math.hypot(s.x - s.target.x, s.y - s.target.y) < 10:
            if s.fuel >= 20:
                amount = min(20, s.fuel // 2)
                s.target.fuel = min(s.target.fuel + amount, F_TOTAL)
                s.fuel -= amount
                s.target.status = "free"
                s.target.dx = random.uniform(-1, 1)
                s.target.dy = random.uniform(-1, 1)
                s.status = "returning"
                s.target = None

        # builder low fuel -> ask reserver
        if s.status == "builder" and s.fuel < T_LOW:
            if not refuel_builder(s):
                # failed to refuel -> return to base
                s.status = "returning"
                s.beacon_pair = None

        # free satellites with enough fuel rescue dead
        if s.status == "free" and s.fuel >= T_LOW and dead:
            victim = min(dead, key=lambda d: math.hypot(s.x - d.x, s.y - d.y))
            s.status = "rescue"
            s.target = victim

    # Alpha regulation
    alpha.regulate()

    # Triplet formation controlled by Alpha.triplet_interval and bond_radius
    if now - last_triplet_try > alpha.triplet_interval:
        trip = form_triplet(alpha.bond_radius)
        last_triplet_try = now
        # if trip is formed, trip handled by event hook already

    # free satellites move to nearest beacons to join
    beacons = find_beacons()
    free = find_free()
    for s in free:
        if beacons:
            nearest = min(beacons, key=lambda b: math.hypot(s.x - b.x, s.y - b.y))
            # only move to beacons within some reasonable range (alpha.bond_radius)
            if math.hypot(s.x - nearest.x, s.y - nearest.y) < alpha.bond_radius:
                s.move_to(nearest.x, nearest.y)

    # weak satellites prefer reserver beacons or go to base
    weak = find_weak()
    for s in weak:
        if beacons:
            # prefer reserver with fuel
            eligible = [b for b in beacons if b.role == "reserver" and b.fuel > F_TOTAL * 0.33]
            if eligible:
                nearest = min(eligible, key=lambda b: math.hypot(s.x - b.x, s.y - b.y))
                if math.hypot(s.x - nearest.x, s.y - nearest.y) < 12:
                    transfer = min(F_MAX_SHARE, nearest.fuel - T_CRITICAL)
                    if transfer > 0:
                        nearest.fuel -= transfer
                        s.fuel = min(s.fuel + transfer, F_TOTAL)
                        s.status = "free"
                        continue
            # otherwise go to base
            s.move_to(WIDTH / 2, HEIGHT / 2)

    # drawing
    screen.fill((0, 0, 0))

    # draw target figure (Alpha might direct to form a circle) - optional visualization
    # pygame.draw.circle(screen, (50,50,50), (WIDTH//2, HEIGHT//2), 120, 1)

    for s in satellites:
        s.draw()

    # top-left telemetry
    tm = alpha.telemetry()
    info_lines = [
        f"Avg fuel: {tm['avg_fuel']:.1f}",
        f"Free: {tm['free_count']}  Builders: {tm['builder_count']}  Beacons: {tm['beacon_count']}",
        f"Weak: {tm['weak_count']}  Dead: {tm['dead_count']}",
        f"Bond radius: {alpha.bond_radius:.0f}  Triplet interval: {alpha.triplet_interval} ms"
    ]
    for i, line in enumerate(info_lines):
        txt = font.render(line, True, WHITE)
        screen.blit(txt, (8, 8 + i * 18))

    pygame.display.flip()

pygame.quit()
