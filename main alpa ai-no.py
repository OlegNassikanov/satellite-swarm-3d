from vpython import *
import random, math

# === ПАРАМЕТРЫ ===
NUM_SATELLITES = 30
F_TOTAL = 100
T_LOW = 30
T_CRITICAL = 15
F_MAX_SHARE = F_TOTAL / 3
ICE_CONSUMPTION = 0.1
SPEED = 0.2
BOND_RADIUS = 15
BASE_POS = vector(0, 0, 0)

# === СЦЕНА ===
scene = canvas(title="Swarm 3D Simulation with Alpha-AI (Fixed)",
               width=1000, height=700, background=color.black)
scene.camera.pos = vector(0, 0, 60)
scene.camera.axis = vector(0, 0, -60)

# Визуализация базы
base_marker = sphere(pos=BASE_POS, radius=1.5, color=color.green, opacity=0.3)

# === ЦВЕТА ===
COLORS = {
    "free": color.white,
    "builder": color.blue,
    "beacon": color.cyan,
    "commander": vector(0, 1, 1),
    "reserver": vector(0, 0.8, 0.8),
    "returning": color.green,
    "dead": color.red,
    "rescue": color.yellow,
    "weak": vector(0.5, 0.5, 0.5)
}

# === КЛАСС СПУТНИКА ===
class Satellite:
    def __init__(self):
        self.pos = vector(random.uniform(-20, 20),
                          random.uniform(-20, 20),
                          random.uniform(-20, 20))
        self.vel = vector(random.uniform(-1, 1),
                          random.uniform(-1, 1),
                          random.uniform(-1, 1))
        self.sphere = sphere(pos=self.pos, radius=0.8,
                             color=color.white, make_trail=False)
        self.label = label(pos=self.pos, text='100', 
                          height=10, color=color.white, opacity=0)
        self.fuel = F_TOTAL
        self.status = "free"
        self.role = None
        self.target = None
        self.beacon_pair = None

    def move(self):
        # Beacon'ы не двигаются (ИСПРАВЛЕНО!)
        if self.status == "beacon":
            self.sphere.pos = self.pos
            self.update_label()
            # Минимальный расход для beacon'ов
            self.fuel -= ICE_CONSUMPTION * 0.02
            return

        # Builder двигается к центру между beacon'ами (ИСПРАВЛЕНО!)
        if self.status == "builder" and self.beacon_pair:
            commander, reserver = self.beacon_pair
            target = (commander.pos + reserver.pos) / 2
            self.move_to(target)
        elif self.status == "rescue" and self.target:
            # Движение к цели для спасения
            self.move_to(self.target.pos)
        elif self.status in ["returning", "weak"]:
            # Возврат на базу
            self.move_to(BASE_POS)
        elif self.status == "free":
            # Свободное перемещение
            self.pos += norm(self.vel) * SPEED
            self.sphere.pos = self.pos

        # --- отражение от границ ---
        for axis in ['x', 'y', 'z']:
            val = getattr(self.pos, axis)
            if abs(val) > 25:
                setattr(self.vel, axis, -getattr(self.vel, axis))

        # --- расход топлива (ИСПРАВЛЕНО - разный для разных статусов) ---
        if self.status != "beacon":
            self.fuel -= ICE_CONSUMPTION
        
        # --- проверка состояния ---
        if self.fuel <= 0 and self.status != "dead":
            self.status = "dead"
            self.sphere.color = COLORS["dead"]
            self.vel = vector(0, 0, 0)
        elif self.status == "free" and self.fuel < T_CRITICAL:
            self.status = "weak"
            self.sphere.color = COLORS["weak"]

        # --- возврат на базу (ДОБАВЛЕНО) ---
        if self.status == "returning" and mag(self.pos - BASE_POS) < 2:
            self.fuel = F_TOTAL
            self.status = "free"
            self.vel = vector(random.uniform(-1, 1),
                            random.uniform(-1, 1),
                            random.uniform(-1, 1))
            self.role = None
            self.beacon_pair = None
            self.sphere.color = COLORS["free"]

        # --- спасение (ДОБАВЛЕНО) ---
        if self.status == "rescue" and self.target:
            if mag(self.pos - self.target.pos) < 2:
                if self.fuel >= 20:
                    transfer = min(20, self.fuel // 2)
                    self.target.fuel = min(self.target.fuel + transfer, F_TOTAL)
                    self.fuel -= transfer
                    self.target.status = "free"
                    self.target.vel = vector(random.uniform(-1, 1),
                                            random.uniform(-1, 1),
                                            random.uniform(-1, 1))
                    self.target.sphere.color = COLORS["free"]
                    self.status = "returning"
                    self.target = None
                    self.sphere.color = COLORS["returning"]

        self.update_label()

    def move_to(self, target):
        direction = target - self.pos
        if mag(direction) > 0.1:
            self.vel = norm(direction)
            self.pos += self.vel * SPEED
            self.sphere.pos = self.pos

    def update_label(self):
        self.label.pos = self.pos + vector(0, 1.5, 0)
        self.label.text = f'{int(self.fuel)}'
        # Цвет метки в зависимости от уровня топлива
        if self.fuel < T_CRITICAL:
            self.label.color = color.red
        elif self.fuel < T_LOW:
            self.label.color = color.yellow
        else:
            self.label.color = color.white

# === КЛАСС АЛЬФА-ИИ ===
class AlphaAI:
    def __init__(self, satellites):
        self.sats = satellites
        self.links = []
        self.counter = 0

    def find_dead(self):
        return [s for s in self.sats if s.status == "dead"]

    def find_free(self):
        return [s for s in self.sats if s.status == "free" and s.fuel >= T_LOW]

    def find_weak(self):
        return [s for s in self.sats if s.status == "weak"]

    def regulate(self):
        self.counter += 1
        
        # --- очистка старых связей ---
        for l in self.links:
            l.visible = False
        self.links.clear()

        # --- усреднение движения для free спутников ---
        for s in self.sats:
            if s.status == "free":
                neighbors = [o for o in self.sats 
                           if mag(o.pos - s.pos) < 6 and o != s and o.status == "free"]
                if neighbors:
                    avg_dir = sum([o.vel for o in neighbors], vector(0,0,0)) / len(neighbors)
                    s.vel = norm(s.vel + avg_dir * 0.1)

        # --- регулировка топлива в триплетах (ИСПРАВЛЕНО!) ---
        builders = [s for s in self.sats if s.status == "builder"]
        for b in builders:
            if b.fuel < T_LOW:
                if not self.refuel(b):
                    # Не удалось заправить - возврат на базу
                    b.status = "returning"
                    b.beacon_pair = None
                    b.sphere.color = COLORS["returning"]

        # --- спасение мертвых (ДОБАВЛЕНО) ---
        if self.counter % 30 == 0:  # Каждые 30 кадров
            self.prioritize_rescue()

        # --- помощь слабым (ДОБАВЛЕНО) ---
        weak = self.find_weak()
        for w in weak:
            # Ищем ближайший reserver beacon с топливом
            reservers = [s for s in self.sats 
                        if s.status == "beacon" and s.role == "reserver" 
                        and s.fuel > F_TOTAL * 0.33]
            if reservers:
                nearest = min(reservers, key=lambda r: mag(r.pos - w.pos))
                if mag(w.pos - nearest.pos) < 3:
                    transfer = min(F_MAX_SHARE, nearest.fuel - T_CRITICAL)
                    if transfer > 0:
                        nearest.fuel -= transfer
                        w.fuel = min(w.fuel + transfer, F_TOTAL)
                        w.status = "free"
                        w.sphere.color = COLORS["free"]

        # --- визуализация связей триплета ---
        for s in self.sats:
            if s.beacon_pair:
                c, r = s.beacon_pair
                self.links.append(curve(pos=[s.pos, c.pos], color=color.green, radius=0.05))
                self.links.append(curve(pos=[s.pos, r.pos], color=color.green, radius=0.05))
                self.links.append(curve(pos=[c.pos, r.pos], color=color.cyan, radius=0.05))

    def refuel(self, builder):
        """ИСПРАВЛЕНО: топливо только builder'у, как в 2D"""
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
            
            # Переоценка ролей
            if commander.fuel < reserver.fuel:
                commander.role, reserver.role = reserver.role, commander.role
                commander.sphere.color = COLORS["reserver"]
                reserver.sphere.color = COLORS["commander"]
            
            return True
        else:
            return False

    def prioritize_rescue(self):
        """Назначение спасательных операций (ДОБАВЛЕНО)"""
        dead = self.find_dead()
        if not dead:
            return
        
        free = [s for s in self.sats if s.status == "free" and s.fuel > T_LOW]
        for victim in dead[:min(3, len(dead))]:  # Не более 3 одновременно
            if not free:
                break
            rescuer = min(free, key=lambda s: mag(s.pos - victim.pos))
            rescuer.status = "rescue"
            rescuer.target = victim
            rescuer.sphere.color = COLORS["rescue"]
            free.remove(rescuer)

# === СОЗДАНИЕ ТРИПЛЕТА ===
def form_triplet(sats, bond_radius=BOND_RADIUS):
    free = [s for s in sats if s.status == "free" and s.fuel >= T_LOW]
    if len(free) < 3:
        return None
    
    s1 = random.choice(free)
    neighbors = [s for s in free if s != s1 and mag(s.pos - s1.pos) <= bond_radius]
    if len(neighbors) < 2:
        return None
    
    neighbors.sort(key=lambda s: mag(s.pos - s1.pos))
    triplet = [s1, neighbors[0], neighbors[1]]
    
    # Назначение ролей
    triplet[0].status = "builder"
    triplet[1].status = "beacon"
    triplet[2].status = "beacon"
    
    # Роли по уровню топлива
    if triplet[1].fuel < triplet[2].fuel:
        triplet[1].role = "commander"
        triplet[2].role = "reserver"
    else:
        triplet[1].role = "reserver"
        triplet[2].role = "commander"
    
    # ИСПРАВЛЕНО: обнуляем скорость beacon'ов!
    triplet[1].vel = vector(0, 0, 0)
    triplet[2].vel = vector(0, 0, 0)
    
    # Связь builder'а с beacon'ами
    triplet[0].beacon_pair = [triplet[1], triplet[2]]
    
    # Цена формирования
    for s in triplet:
        s.fuel -= T_LOW * 0.2
    
    # Обновление цветов
    triplet[0].sphere.color = COLORS["builder"]
    triplet[1].sphere.color = COLORS["commander"] if triplet[1].role == "commander" else COLORS["reserver"]
    triplet[2].sphere.color = COLORS["commander"] if triplet[2].role == "commander" else COLORS["reserver"]
    
    return triplet

# === ИНИЦИАЛИЗАЦИЯ ===
satellites = [Satellite() for _ in range(NUM_SATELLITES)]
alpha = AlphaAI(satellites)

# Формируем начальный триплет
form_triplet(satellites)

# === СЧЕТЧИК КАДРОВ ДЛЯ ПЕРИОДИЧЕСКОГО ФОРМИРОВАНИЯ ===
frame_counter = 0
TRIPLET_FORMATION_INTERVAL = 120  # Каждые 2 секунды при 60 fps

# === ГЛАВНЫЙ ЦИКЛ ===
while True:
    rate(60)
    frame_counter += 1
    
    alpha.regulate()
    
    for s in satellites:
        s.move()
    
    # Периодическое формирование новых триплетов
    if frame_counter % TRIPLET_FORMATION_INTERVAL == 0:
        form_triplet(satellites, BOND_RADIUS)