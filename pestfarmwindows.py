import minescript as m
from minescript import EventQueue, EventType, entities
from minescript_plus import Util
from java import JavaClass
import math, threading, time, re
import random

# -------------------
# GLOBAL STATE
# -------------------

STATE = {
    "running": False,
    "restart_detected": False,
    "vacuum_only": False,
    "limbo_detected": False
}

running = False
vacuum_only = False
restart_detected = False
limbo_detected = False
state_lock = threading.Lock()

ylevel = 67.875 # use this if u are using a single layer farm, otherwise change the ylevel in farming waypoints to the correct ylevel for your farm
amountofpests = 4  # number of pests to trigger pest clearing

# here is your yaw and pitch for the farm, currently set for my melon farm but change to your likings.
TARGET_YAW = 90.0
TARGET_PITCH = -58.5

FLY_HEIGHT = 78.0 # the height of where the player will fly up to when going to kill pests

FARMING_WAYPOINTS = [ 
    (143.3, ylevel, 238.7), (143.3, ylevel, -238.7),
    (140.3, ylevel, -238.7), (140.3, ylevel, 238.7),
    (137.3, ylevel, 238.7), (137.3, ylevel, -238.7),
    (134.3, ylevel, -238.7), (134.3, ylevel, 238.7),
    (131.3, ylevel, 238.7), (131.3, ylevel, -238.7),
    (128.3, ylevel, -238.7), (128.3, ylevel, 238.7),
    (125.3, ylevel, 238.7), (125.3, ylevel, -238.7),
    (122.3, ylevel, -238.7), (122.3, ylevel, 238.7),
    (119.3, ylevel, 238.7), (119.3, ylevel, -238.7),
    (116.3, ylevel, -238.7), (116.3, ylevel, 238.7),
    (113.3, ylevel, 238.7), (113.3, ylevel, -238.7),
    (110.3, ylevel, -238.7), (110.3, ylevel, 238.7)#just change these if u wanna use a diff farm
]

# -------------------
# UTILITIES
# -------------------
def strip_color_codes(text):
    return re.sub(r'§[0-9a-fk-or]', '', text)

def get_pest_info():
    """Return pest count and affected plots from tablist."""
    try:
        mc = JavaClass("net.minecraft.client.Minecraft").getInstance()
        connection = mc.getConnection()

        pest_count = 0
        pest_plots = []

        for player in connection.getOnlinePlayers():
            display = player.getTabListDisplayName()
            if not display:
                continue
            text = display.getString()

            if "Alive" in text:
                match = re.search(r"Alive:\s*(\d+)", text)
                if match: pest_count = int(match.group(1))
            elif "Plots" in text:
                match = re.search(r"Plots:\s*(.*)", text)
                if match: pest_plots = [p.strip() for p in match.group(1).split(",") if p.strip()]

        return pest_count, pest_plots
    except Exception as e:
        m.echo(f"[Pest Detection] Error reading tablist: {e}")
        return 0, []

# -------------------
# LIMBO & RESTART HANDLING
# -------------------
def handle_limbo():
    global limbo_detected, running
    m.echo("[Script] Limbo detected! Going to lobby and returning...")
    temp_running = running
    running = False
    time.sleep(0.3)

    for key in [m.player_press_forward, m.player_press_left, m.player_press_right,
                m.player_press_use, m.player_press_attack, m.player_press_jump, m.player_press_sneak]:
        key(False)

    time.sleep(5)
    m.execute("/lobby"); time.sleep(5)
    m.execute("/skyblock"); time.sleep(5)
    m.execute("/warp garden"); time.sleep(5); m.player_press_jump(True); time.sleep(0.2); m.player_press_jump(False)
    stop_fly()
    m.player_press_attack(True); time.sleep(0.5)

    limbo_detected = False
    if temp_running:
        running = True
        threading.Thread(target=main_loop, daemon=True).start()

def check_for_limbo_message(message):
    global limbo_detected
    clean_message = strip_color_codes(message).lower()
    if "you were spawned in limbo" in clean_message or "/limbo for more information" in clean_message:
        if running and not limbo_detected:
            limbo_detected = True
            threading.Thread(target=handle_limbo, daemon=True).start()
            return True
    return False

def handle_restart():
    global restart_detected, running
    m.echo("[Script] Server restart detected! Going to hub and waiting 20 seconds...")
    temp_running = running
    running = False
    time.sleep(0.3)

    for key in [m.player_press_forward, m.player_press_left, m.player_press_right,
                m.player_press_use, m.player_press_attack, m.player_press_jump, m.player_press_sneak]:
        key(False)

    m.execute("/hub")
    time.sleep(20)
    m.execute("/warp garden")
    time.sleep(6.7)
    running = True
    threading.Thread(target=main_loop, daemon=True).start()
    return True

def check_for_restart_message(message):
    global restart_detected
    clean_message = strip_color_codes(message).lower()
    if re.search(r'\[important\].*this server will.*reboot', clean_message):
        if running and not restart_detected:
            restart_detected = True
            threading.Thread(target=handle_restart, daemon=True).start()
            return True
    return False

# -------------------
# FLYING & MOVEMENT
# -------------------
def fly():
    m.player_press_jump(True); time.sleep(0.1)
    m.player_press_jump(False); time.sleep(0.1)
    m.player_press_jump(True); time.sleep(0.1)
    m.player_press_jump(False); time.sleep(0.1)

def stop_fly():
    m.player_press_sneak(True); time.sleep(5)
    m.player_press_sneak(False); time.sleep(0.05)

def fly_to_height(target_height, tolerance=0.5, check_interval=0.05):
    """Ascend smoothly to target height without spamming fly()."""
    global running

    # get current Y
    y = m.player_position()[1]

    # only tap fly once if we’re below target
    if y < target_height - tolerance:
        fly()  # enter flying mode once
        m.player_press_jump(True)
    else:
        m.player_press_jump(False)
        return

    # keep ascending until we reach height
    while running:
        y = m.player_position()[1]
        if y >= target_height - tolerance:
            m.player_press_jump(False)
            break
        time.sleep(check_interval)

    m.player_press_jump(False)

def set_orientation():
    m.player_set_orientation(TARGET_YAW, TARGET_PITCH); time.sleep(0.1)

def move_to_waypoint(target_pos, prev_pos=None):
    global running
    m.player_press_attack(True)
    while running:
        pos = m.player_position()
        if abs(pos[0] - target_pos[0]) < 0.01 and abs(pos[2] - target_pos[2]) < 0.01:
            m.player_press_forward(False); m.player_press_left(False); m.player_press_right(False)
            return True
        dx = dz = 0
        if prev_pos: dx = target_pos[0] - prev_pos[0]; dz = target_pos[2] - prev_pos[2]
        m.player_press_forward(abs(dx) > abs(dz)); m.player_press_left(dz > 0); m.player_press_right(dz < 0)
        time.sleep(0.05)
    m.player_press_forward(False); m.player_press_left(False); m.player_press_right(False)
    return False

def move_to_plot_center(target_x, target_z, tolerance=1.5):
    global running
    while running:
        pos = m.player_position()
        dx, dz = target_x - pos[0], target_z - pos[2]
        if math.sqrt(dx**2 + dz**2) <= tolerance:
            m.player_press_forward(False)
            return True
        yaw = -math.degrees(math.atan2(dx, dz))
        m.player_set_orientation(yaw, 0)
        m.player_press_forward(True)
        time.sleep(0.02)

# -------------------
# FARMING
# -------------------

def farm_cycle():
    global running
    m.echo("[Farming] Starting crop farming cycle...")
    m.execute("/warp garden"); time.sleep(1); m.player_press_sneak(True); time.sleep(1); m.player_press_sneak(False)
    set_orientation(); m.player_inventory_select_slot(0); time.sleep(0.5)
    prev = None
    for i, wp in enumerate(FARMING_WAYPOINTS):
        if not running: break
        pests, _ = get_pest_info()
        if pests >= amountofpests:
            m.echo(f"[Farming] {pests} pests detected! Stopping farm cycle.")
            m.player_press_forward(False); m.player_press_left(False); m.player_press_right(False)
            m.player_press_attack(False)
            return False
        if i % 2 == 0: m.echo(f"[Farming] Waypoint {i+1}/{len(FARMING_WAYPOINTS)}")
        if not move_to_waypoint(wp, prev): break
        prev = wp
    m.player_press_forward(False); m.player_press_left(False); m.player_press_right(False)
    time.sleep(1)
    return True

# -------------------
# PEST VACUUM
# -------------------
GARDEN_MIN_X, GARDEN_MAX_X = -239, 239
GARDEN_MIN_Z, GARDEN_MAX_Z = -239, 239
PLOT_SIZE = (GARDEN_MAX_X - GARDEN_MIN_X) / 5
HALF = PLOT_SIZE / 2
layout = [
    [21, 13,  9, 14, 22],
    [15,  5,  1,  6, 16],
    [10,  2, 25,  3, 11],
    [17,  7,  4,  8, 18],
    [23, 19, 12, 20, 24]
]
PLOT_CENTERS = {}
for r_idx, row in enumerate(layout):
    for c_idx, plot in enumerate(row):
        PLOT_CENTERS[plot] = (GARDEN_MIN_X + c_idx*PLOT_SIZE + HALF, GARDEN_MIN_Z + r_idx*PLOT_SIZE + HALF)

def find_all_silverfish():
    return [e for e in entities(max_distance=100) if e and e.position and (e.health == 600 or e.name == "Silverfish")]

def approach_and_vacuum_single_silverfish(sf, steps=100):
    global running
    if not sf or not sf.position: return False
    stuck_time = None
    last_reachable = True
    last_check = time.time()

    while running:
        current_sfs = find_all_silverfish()
        if sf not in current_sfs: return True

        p, s = m.player_position(), sf.position
        dx, dy, dz = s[0]-p[0], s[1]-p[1], s[2]-p[2]
        dist = math.sqrt(dx**2 + dy**2 + dz**2)

        cur_yaw, cur_pitch = m.player_orientation()
        tgt_yaw = -math.degrees(math.atan2(dx, dz))
        tgt_pitch = -math.degrees(math.atan2(dy, math.sqrt(dx**2 + dz**2)))
        yaw_diff = ((tgt_yaw - cur_yaw + 180) % 360) - 180
        pitch_diff = tgt_pitch - cur_pitch

        for i in range(1, steps+1):
            if not running: return False
            t = i/steps
            m.player_set_orientation(cur_yaw + yaw_diff*t, cur_pitch + pitch_diff*t)
            time.sleep(0.002)

        if dist > 5: m.player_press_forward(True)
        else: m.player_press_forward(False)

        horiz_dist = math.sqrt(dx**2 + dz**2)
        above = horiz_dist < 1.5 and dy < -1.0
        can_reach = dist <= 5

        if above and not can_reach:
            if not last_reachable:
                if stuck_time is None: stuck_time = time.time()
                elif time.time() - stuck_time > 15.0:
                    m.echo("[Vacuum] Silverfish unreachable for 15s, skipping...")
                    return False
            last_reachable = False
        else: stuck_time = None; last_reachable = True

        if above and not can_reach: m.player_press_sneak(True); m.player_press_jump(False)
        elif p[1] < s[1]-2: m.player_press_jump(True); m.player_press_sneak(False)
        else: m.player_press_jump(False); m.player_press_sneak(False)

        m.player_press_use(True); time.sleep(0.05)

    return False

def approach_and_vacuum_silverfish_queue():
    global running
    m.player_inventory_select_slot(2); time.sleep(0.05)
    while running:
        sfs = find_all_silverfish()
        if not sfs: break
        p = m.player_position()
        closest = min(sfs, key=lambda e: Util.get_distance(p, e.position))
        if not approach_and_vacuum_single_silverfish(closest):
            m.echo("[Vacuum] Skipping unreachable silverfish...")
            continue
    m.player_press_forward(False); m.player_press_use(False)
    m.player_press_jump(False); m.player_press_sneak(False)

def vacuum_plot(plot_number):
    global running
    rand1 = random.randint(1, 2)
    rand2 = random.randint(0, 2)
    rand3 = random.randint(2, 4)
    try: plot_number = int(plot_number)
    except ValueError: m.echo(f"[Pest] Invalid plot {plot_number}, skipping"); return
    if plot_number == 25: m.echo("[Pest] Barn plot skipped"); return

    m.echo(f"[Pest] Teleporting to plot {plot_number}...")
    time.sleep(rand1)
    m.execute(f"/plottp {plot_number}")
    time.sleep(rand2)

    # Hold sneak for 3 seconds after teleport
    m.player_press_sneak(True)
    time.sleep(rand3)
    m.player_press_sneak(False)
    time.sleep(0.1)

    fly_to_height(FLY_HEIGHT)
    time.sleep(0.2)

    if plot_number in PLOT_CENTERS:
        tx, tz = PLOT_CENTERS[plot_number]
        m.echo(f"[Pest] Moving to center X={tx:.2f}, Z={tz:.2f}")
        move_to_plot_center(tx, tz)
        time.sleep(0.1)

    approach_and_vacuum_silverfish_queue()


def pest_cycle():
    global running
    m.echo("[Pest] Checking for pests...")
    _, pest_plots = get_pest_info()
    if not pest_plots: m.echo("[Pest] No pests, continuing farming"); return True

    m.echo(f"[Pest] Found pests in plots: {pest_plots}")
    for plot in pest_plots:
        if not running: break
        vacuum_plot(plot)

    # Hold sneak for 4 seconds after clearing
    m.echo("[Pest] All pests cleared, holding sneak for 4 seconds...")
    start = time.time()
    while running and time.time() - start < 4:
        m.player_press_sneak(True); time.sleep(0.05)
    m.player_press_sneak(False)
    m.echo("[Pest] Sneak complete, resuming farming...")
    return True

# -------------------
# MAIN LOOP & EVENTS
# -------------------
def main_loop():
    global running, vacuum_only
    mode = "VACUUM ONLY" if vacuum_only else "FULL CYCLE"
    m.echo(f"[Script] Started in {mode} mode. Press F6/F8 to stop.")

    while running:
        if vacuum_only:
            pest_cycle(); time.sleep(1); continue
        farm_continues = True
        while running and farm_continues: farm_continues = farm_cycle()
        m.echo("[Script] Pest clearing triggered...")
        pest_cycle()
        m.echo("[Script] Pest clearing complete, restarting farm cycle...")
        time.sleep(1)

def toggle_script(vacuum_mode=False):
    global running, vacuum_only
    with state_lock:
        if running: running = False; m.echo("[Script] Stopping...")
        else: running = True; vacuum_only = vacuum_mode; threading.Thread(target=main_loop, daemon=True).start()

def on_key_event(event):
    if event.action == 1:
        if event.key == 295: toggle_script(False)
        elif event.key == 297: toggle_script(True)

def on_chat_event(event):
    check_for_restart_message(event.message)
    check_for_limbo_message(event.message)

# -------------------
# START
# -------------------
if __name__ == "__main__":
    m.echo("[Script] Garden Farmer loaded")
    m.echo("[Script] Press F6 for full cycle, F8 for vacuum only")
    m.echo("[Script] Restart detection: ENABLED, Limbo detection: ENABLED, Pest detection: ENABLED (5+ pests)")

    with EventQueue() as q:
        q.register_key_listener()
        q.register_chat_listener()
        while True:
            e = q.get()
            if e.type == EventType.KEY: on_key_event(e)
            elif e.type == EventType.CHAT: on_chat_event(e)