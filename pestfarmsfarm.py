import minescript as m
import minescript
from minescript import EventQueue, EventType, entities
from minescript_plus import Util
from java import JavaClass
import math, threading, time, re
import random
from pynput.keyboard import Controller

# -------------------
# GLOBAL STATE
# -------------------
running = False
macro_check_running = False
backtick_running = False
restart_detected = False
limbo_detected = False
stop_event = threading.Event()
prev_pos = None
last_toggle_time = 0
keyboard = Controller()
loop_counter = 0  # Tracks number of completed farming cycles
row_time = 5.6
switch_row_time = 1.0

# Chat-based detection toggle
# Enabled during farming cycles when requested by user flow

detection_enabled = False

# -------------------
# CONSTANTS
# -------------------
FLY_HEIGHT = 80.0
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

# -------------------
# UTILITIES
# -------------------

def strip_color_codes(text):
    return re.sub(r'ยง[0-9a-fk-or]', '', text)


def angle_difference(current, target):
    """Calculate the shortest angular difference."""
    diff = (target - current + 180) % 360 - 180
    return diff


def calculate_look_angles(player_pos, target_pos):
    """Calculate yaw and pitch to look at target position."""
    dx = target_pos[0] - player_pos[0]
    dy = target_pos[1] - player_pos[1]
    dz = target_pos[2] - player_pos[2]

    yaw = -math.degrees(math.atan2(dx, dz))
    pitch = -math.degrees(math.atan2(dy, math.sqrt(dx**2 + dz**2)))

    return yaw, pitch


def smooth_look_at(target_pos, duration=0.3, steps=30):
    """Smoothly rotate view to look at target position."""
    player_pos = m.player_position()
    current_yaw, current_pitch = m.player_orientation()

    target_yaw, target_pitch = calculate_look_angles(player_pos, target_pos)

    # Calculate angular differences
    yaw_diff = angle_difference(current_yaw, target_yaw)
    pitch_diff = angle_difference(current_pitch, target_pitch)

    # Scale duration based on angular distance (optional)
    angular_distance = math.sqrt(yaw_diff**2 + pitch_diff**2)
    if angular_distance < 10:
        actual_duration = duration * 0.3
        steps = max(10, int(steps * 0.3))
    else:
        actual_duration = duration

    step_delay = actual_duration / steps

    for i in range(steps + 1):
        t = i / steps
        # Smoothstep easing function
        smooth_t = t * t * (3 - 2 * t)

        new_yaw = current_yaw + yaw_diff * smooth_t
        new_pitch = current_pitch + pitch_diff * smooth_t

        m.player_set_orientation(new_yaw, new_pitch)
        time.sleep(step_delay)


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
    global limbo_detected, running, macro_check_running, backtick_running
    m.echo("[Script] Limbo detected! Going to lobby and returning...")
    temp_running = running
    running = False
    macro_check_running = False
    backtick_running = False
    time.sleep(0.3)

    # Stop all inputs
    for key in [m.player_press_forward, m.player_press_left, m.player_press_right,
                m.player_press_use, m.player_press_attack, m.player_press_jump, m.player_press_sneak]:
        key(False)

    time.sleep(5)
    m.execute("/lobby"); time.sleep(5)
    m.execute("/skyblock"); time.sleep(5)
    m.execute("/warp garden"); time.sleep(5)
    m.player_press_jump(True); time.sleep(0.2); m.player_press_jump(False)
    stop_fly()
    m.player_press_attack(True); time.sleep(0.5)

    limbo_detected = False
    if temp_running:
        running = True


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
    global restart_detected, running, macro_check_running, backtick_running
    m.echo("[Script] Server restart detected! Going to hub and waiting 20 seconds...")
    temp_running = running
    running = False
    macro_check_running = False
    backtick_running = False
    time.sleep(0.3)

    # Stop all inputs
    for key in [m.player_press_forward, m.player_press_left, m.player_press_right,
                m.player_press_use, m.player_press_attack, m.player_press_jump, m.player_press_sneak]:
        key(False)

    m.execute("/hub")
    time.sleep(20)
    m.execute("/warp garden")
    time.sleep(6.7)
    restart_detected = False
    if temp_running:
        running = True
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

    y = m.player_position()[1]

    if y < target_height - tolerance:
        fly()
        m.player_press_jump(True)
    else:
        m.player_press_jump(False)
        return

    while running:
        y = m.player_position()[1]
        if y >= target_height - tolerance:
            m.player_press_jump(False)
            break
        time.sleep(check_interval)

    m.player_press_jump(False)


def move_to_plot_center(target_x, target_z, tolerance=1.5):
    global running

    # Smoothly look at the target first
    target_pos = (target_x, m.player_position()[1], target_z)
    smooth_look_at(target_pos, duration=0.5, steps=40)

    while running:
        pos = m.player_position()
        dx, dz = target_x - pos[0], target_z - pos[2]
        if math.sqrt(dx**2 + dz**2) <= tolerance:
            m.player_press_forward(False)
            return True

        # Gentle orientation correction during movement
        yaw = -math.degrees(math.atan2(dx, dz))
        current_yaw, current_pitch = m.player_orientation()
        if abs(angle_difference(current_yaw, yaw)) > 5:
            m.player_set_orientation(yaw, 0)

        m.player_press_forward(True)
        time.sleep(0.02)

# -------------------
# PEST KILLING
# -------------------

def find_all_silverfish():
    return [e for e in entities(max_distance=100) if e and e.position and (e.health == 600 or e.name == "Silverfish")]


def approach_and_vacuum_single_silverfish(sf, steps=100):
    global running
    if not sf or not sf.position: return False
    stuck_time = None
    last_reachable = True
    last_smooth_look = 0

    while running:
        current_sfs = find_all_silverfish()
        if sf not in current_sfs: return True

        p, s = m.player_position(), sf.position
        dx, dy, dz = s[0]-p[0], s[1]-p[1], s[2]-p[2]
        dist = math.sqrt(dx**2 + dy**2 + dz**2)

        # Use smooth look-at every 0.5 seconds instead of continuous jerky rotation
        current_time = time.time()
        if current_time - last_smooth_look > 0.5:
            smooth_look_at(sf.position, duration=0.2, steps=20)
            last_smooth_look = current_time

        if dist > 5: m.player_press_forward(True)
        else: m.player_press_forward(False)

        horiz_dist = math.sqrt(dx**2 + dz**2)
        above = horiz_dist < 1.5 and dy < -1.0
        can_reach = dist <= 5

        if above and not can_reach:
            if not last_reachable:
                if stuck_time is None: stuck_time = time.time()
                elif time.time() - stuck_time > 30.0:
                    m.echo("[Vacuum] Silverfish unreachable for 15s, skipping...")
                    return False
            time.sleep(2)
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

    m.player_press_sneak(True)
    time.sleep(rand3)
    m.player_press_sneak(False)

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
    if not pest_plots:
        m.echo("[Pest] No pests found")
        return

    m.echo(f"[Pest] Found pests in plots: {pest_plots}")
    for plot in pest_plots:
        if not running: break
        vacuum_plot(plot)

    m.echo("[Pest] All pests cleared")

# -------------------
# BACKTICK PRESSER
# -------------------

def backtick_presser():
    """Press backtick key every 20 seconds during farming."""
    global running, backtick_running, keyboard

    while running and backtick_running:
        time.sleep(20)
        if running and backtick_running:
            keyboard.press('`')
            time.sleep(0.05)
            keyboard.release('`')
            m.echo("[Backtick] Pressed ` key")

# -------------------
# MACRO CHECK HELPERS
# -------------------

def macro_check_sequence():
    """Unified macro-check chat + actions sequence for all detectors."""
    # Stop all movement/inputs
    for key in [m.player_press_left, m.player_press_right, m.player_press_forward,
                m.player_press_attack, m.player_press_use, m.player_press_jump, m.player_press_sneak]:
        key(False)
    time.sleep(3)
    minescript.chat("macro check")
    time.sleep(6)
    minescript.chat("Good time anyways ima go sleep now ty admin (its 1 am :sob)")
    time.sleep(3)
    m.execute("/is")
    Util.play_sound()

# -------------------
# MACRO CHECK MONITOR
# -------------------

def macro_check_monitor():
    """Check yaw/pitch, sudden teleport detection, and blocked detection."""
    global running, macro_check_running, prev_pos

    # Targets and thresholds per request
    yaw_target = 90.0
    pitch_target = 0.0
    yaw_pitch_trigger_delta = 1.5  # deg
    teleport_threshold = 15        # blocks

    # Blocked detection variables
    blocked_pos = m.player_position()
    blocked_time = time.time()

    prev_pos = m.player_position()

    while running and macro_check_running:
        yaw0, pitch0 = m.player_orientation()

        # Yaw/Pitch check (> 1.5 deg change)
        if abs(yaw_target - yaw0) > yaw_pitch_trigger_delta or abs(pitch_target - pitch0) > yaw_pitch_trigger_delta:
            m.echo("[MACRO CHECK] Yaw or pitch changed! Stopping script.")
            running = False
            macro_check_running = False
            macro_check_sequence()
            break

        pos = m.player_position()

        # Teleport detection
        dx = abs(pos[0] - prev_pos[0])
        dy = abs(pos[1] - prev_pos[1])
        dz = abs(pos[2] - prev_pos[2])

        if dx > teleport_threshold or dy > teleport_threshold or dz > teleport_threshold:
            m.echo("[MACRO CHECK] Sudden position change detected! Stopping script.")
            running = False
            macro_check_running = False
            macro_check_sequence()
            break

        # Blocked detection - no movement for >15s
        blocked_dx = abs(pos[0] - blocked_pos[0])
        blocked_dy = abs(pos[1] - blocked_pos[1])
        blocked_dz = abs(pos[2] - blocked_pos[2])

        if blocked_dx < 0.1 and blocked_dy < 0.1 and blocked_dz < 0.1:
            if time.time() - blocked_time > 20.0:
                m.echo("[MACRO CHECK] Player blocked (no movement for 15s)! Stopping script.")
                running = False
                macro_check_running = False
                macro_check_sequence()
                break
        else:
            blocked_pos = pos
            blocked_time = time.time()

        prev_pos = pos
        time.sleep(0.05)

# -------------------
# MAIN FARMING LOOP
# -------------------

def main_loop():
    global running, macro_check_running, detection_enabled, loop_counter, backtick_running

    m.echo("[Script] Starting main loop...")

    while running:
        # Increment and display loop counter
        loop_counter += 1
        m.echo(f"[Script] ===== CYCLE #{loop_counter} STARTING =====")

        # Wait 2 seconds
        time.sleep(2)

        # Turn on limbo and restart detection
        detection_enabled = True

        # Wait 5 seconds
        time.sleep(5)

        # Do the pest check (OG script logic)
        pest_cycle()
        if not running:
            break

        # Cleanup after pest check
        m.player_press_forward(False)
        m.player_press_use(False)
        m.player_press_jump(False)
        m.player_press_sneak(False)

        # /warp garden
        m.execute("/warp garden")

        # Wait 2 seconds
        time.sleep(2)

        # Shift twice (after pest killing and warp)
        m.player_press_sneak(True); time.sleep(0.1); m.player_press_sneak(False)
        time.sleep(0.1)
        m.player_press_sneak(True); time.sleep(0.1); m.player_press_sneak(False)

        # Player press attack (keep ON until told to stop)
        m.player_press_attack(True)

        # Change to inventory slot 1
        m.player_inventory_select_slot(0)

        # Wait 3 seconds
        time.sleep(3)

        # Turn on macro check (yaw/pitch, teleport, blocked)
        macro_check_running = True
        monitor_thread = threading.Thread(target=macro_check_monitor, daemon=True)
        monitor_thread.start()

        # Start backtick presser
        backtick_running = True
        backtick_thread = threading.Thread(target=backtick_presser, daemon=True)
        backtick_thread.start()

        # Movement loop: 8 times, left 27s, then forward 40s
        for i in range(8):
            if not running or not macro_check_running:
                break

            # Left
            m.player_press_forward(False)
            m.player_press_left(False)
            m.player_press_right(False)
            m.player_press_jump(False)
            m.player_press_sneak(False)
            m.player_press_attack(True)

            m.player_press_left(True)
            time.sleep(row_time)
            m.player_press_left(False)

            if not running or not macro_check_running:
                break

            m.player_press_forward(True)
            time.sleep(switch_row_time)
            m.player_press_forward(False)

            m.player_press_right(True)
            time.sleep(row_time)
            m.player_press_right(False)

            if not running or not macro_check_running:
                break

            m.player_press_forward(True)
            time.sleep(switch_row_time)
            m.player_press_forward(False)


        # Turn off macro check
        macro_check_running = False

        # Stop backtick presser
        backtick_running = False

        # Player press attack (Turn off)
        m.player_press_attack(False)

        # Turn off restart and limbo detection
        detection_enabled = False

        # Wait 3 seconds
        time.sleep(3)

        # /warp garden
        m.execute("/warp garden")

        # Loop continues
        m.echo(f"[Script] ===== CYCLE #{loop_counter} COMPLETED =====")

    # Clean up
    m.player_press_attack(False)
    m.player_press_forward(False)
    m.player_press_left(False)
    m.player_press_right(False)
    m.player_press_sneak(False)
    macro_check_running = False
    backtick_running = False

# -------------------
# EVENT HANDLING
# -------------------

def toggle_script():
    global running, macro_check_running, backtick_running, last_toggle_time, loop_counter

    # Debounce: prevent toggling within 0.5 seconds
    current_time = time.time()
    if current_time - last_toggle_time < 0.5:
        return
    last_toggle_time = current_time

    if running:
        running = False
        macro_check_running = False
        backtick_running = False
        m.echo(f"[Script] Stopping... (Completed {loop_counter} cycles)")
    else:
        loop_counter = 0  # Reset counter when starting
        running = True
        threading.Thread(target=main_loop, daemon=True).start()


def on_key_event(event):
    if event.action == 1:
        if event.key == 295:  # F6
            toggle_script()


def on_chat_event(event):
    # Check for restart and limbo messages only when enabled
    if detection_enabled:
        check_for_restart_message(event.message)
        check_for_limbo_message(event.message)

# -------------------
# START
# -------------------
if __name__ == "__main__":
    m.echo("[Sugar] Script loaded")
    m.echo("[Sugar] Press F6 to start/stop")

    with EventQueue() as q:
        q.register_key_listener()
        q.register_chat_listener()
        while True:
            e = q.get()
            if e.type == EventType.KEY:
                on_key_event(e)
            elif e.type == EventType.CHAT:
                on_chat_event(e)