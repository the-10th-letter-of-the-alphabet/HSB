import minescript as m
import threading
from minescript import EventQueue, EventType
from minescript_plus import Util
import random

running = False
prev_pos = None
threshold = 5
stop_event = threading.Event()
bot_thread = None
current_pos = None
row_time = 96500

def wait(ms: int):
    step = 50
    elapsed = 0
    while elapsed < ms and running and not stop_event.is_set():
        stop_event.wait(step / 1000.0)
        if not running:
            break
        elapsed += step

def position_updater():

    global current_pos
    while running and not stop_event.is_set():
        current_pos = m.player_position()
        stop_event.wait(0.05)

def monitor():
    """Check yaw/pitch, warp point, and sudden movement every 50ms."""
    global prev_pos, running, current_pos

    prev_pos = m.player_position()
    current_pos = prev_pos

    while running and not stop_event.is_set():
        yaw_target = 0
        pitch_target = -58.50			#constantly checks the set position for Farming
        yaw0, pitch0 = m.player_orientation()

        if abs(yaw_target - yaw0) > 2.0 or abs(pitch_target - pitch0) > 2.0:
            m.echo("Yaw or pitch changed! Stopping script.")
            running = False
            Util.play_sound()
            stop_event.set()
            break

        pos = current_pos
        if pos  is None:
            continue

        pos = m.player_position()
        if abs(pos[0] - 238) < 0.5 and abs(pos[2] + 148) < 0.5:		#Coords X&Z for the sound
            m.echo("Warp point reached! Executing warp...")		#Plays a sound to let you know when end is near
            #m.execute("/warp garden")
            Util.play_sound()
            prev_pos = m.player_position()
            continue


        dx = abs(pos[0] - prev_pos[0])
        dy = abs(pos[1] - prev_pos[1])
        dz = abs(pos[2] - prev_pos[2])
        if dx > threshold or dy > threshold or dz > threshold:
            m.echo("Sudden position change detected! Stopping script.")
            running = False
            Util.play_sound()
            stop_event.set()
            break

        prev_pos = pos
        stop_event.wait(0.05)

def check_blocked():
    """Check every 300ms if the player is stuck and stop the script."""
    global prev_pos, running
    last_pos = m.player_position()
    stop_event.wait(0.5)

    while running and not stop_event.is_set():
        stop_event.wait(0.5)  # 300 ms
        current_pos = m.player_position()
        dx = abs(current_pos[0] - last_pos[0])
        dy = abs(current_pos[1] - last_pos[1])
        dz = abs(current_pos[2] - last_pos[2])

        if dx < 0.01 and dy < 0.01 and dz < 0.01:
            m.echo("Player seems blocked by a block! Stopping script.")
            running = False
            Util.play_sound()
            break
        last_pos = current_pos


def farming():
    global running, prev_pos
    m.echo("Farming started...")
    running = True
    stop_event.clear()
    prev_pos = None

    m.player_set_orientation(yaw=-74.85, pitch= 5.59)		#Pitch and yaw
    m.player_press_attack(True)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    blocked_thread = threading.Thread(target=check_blocked, daemon=True)
    blocked_thread.start()

    direction = True
    while running and not stop_event.is_set():
        if direction:
            m.player_press_left(True)
            wait(random.randint(row_time, row_time + 100))
            m.player_press_left(False)
        else:					#Change the wait() to time it takes to clear one row, is in ms
            m.player_press_right(True)
            wait(random.randint(row_time, row_time + 100))
            m.player_press_right(False)
        direction = not direction

    running = False
    m.player_press_attack(False)
    m.echo("Farming stopped.")

with EventQueue() as event_queue:
    event_queue.register_key_listener()
    m.echo("Press F6 to start farming, F7 to stop farming.")

    while True:
        event = event_queue.get()
        if event.type == EventType.KEY:
            if event.key == 295 and event.action == 1 and not running:
                bot_thread = threading.Thread(target=farming, daemon=True)
                bot_thread.start()
                pos_thread = threading.Thread(target=position_updater, daemon=True)
                pos_thread.start()
            elif event.key == 296 and event.action == 1 and running:
                m.echo("Stop signal received... stopping farming.")
                stop_event.set()
                running = False
