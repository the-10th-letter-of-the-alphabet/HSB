# Full Minescript Bot - Fishing + OPP Detection + Movement + Camera + Telemetry
import minescript as m
from minescript import EventQueue, EventType
try:
    from minescript_plus import Gui, Util
    m.echo("DEBUG: minescript_plus imported successfully")
except ImportError as e:
    m.echo(f"DEBUG: minescript_plus FAILED to import: {e}")
    # Fallback mock if missing
    class Gui:
        @staticmethod
        def set_actionbar(msg): pass
        @staticmethod
        def set_subtitle(msg): pass
        @staticmethod
        def set_title(msg): pass
        @staticmethod
        def set_title_times(a,b,c): pass
    class Util:
        @staticmethod
        def play_sound(sound=None, sound_source=None, volume=1.0, pitch=1.0): pass

import threading
import time
import random
import math
import os
import datetime

# Global bobber tracking for player detection
latest_bobber_pos = None
bobber_id = None  # Track the specific bobber entity ID

# Chat Safety
# Add keywords here (lowercase) that should trigger an immediate stop
CHAT_ALERT_KEYWORDS = [
    "admin",
    "are you there",
    "macro"
    # "myusername", # <--- Add your username here
]
from collections import deque

# ----------------------------
# GLOBAL STATE
# ----------------------------
running = False
stop_event = threading.Event()
CHAT_ENABLED = True  # Default to ON
state_lock = threading.Lock()

fish_caught = 0
opps_killed = 0
line_out = False

# Orientation thresholds
YAW_THRESHOLD = 5
PITCH_THRESHOLD = 5
CROUCH_DELTA = 10

# Movement config
MAX_HORIZ_DIST = 0.5
MOVE_PROB_FORWARD = 0.6
MOVE_PROB_BACKWARD = 0.1
MOVE_PROB_STRAFE = 0.3
# Jittery movement (short durations)
MOVE_DURATION_MIN = 0.05
MOVE_DURATION_MAX = 0.2
# Longer pauses
PAUSE_PROB = 0.7
PAUSE_MIN = 3.0
PAUSE_MAX = 8.0

# Camera jitter
JITTER_DEG = 0.5
LERP_STEPS_MIN = 3
LERP_STEPS_MAX = 6
LERP_STEP_MIN = 0.03
LERP_STEP_MAX = 0.07

# Telemetry
TELEMETRY_BUFFER_MAX = 100
TELEMETRY_DUMP_INTERVAL = 10.0
TELEMETRY_YAW_PITCH_THRESH = 0.5
TELEMETRY_POS_THRESH = 0.01

# Fuzzy OPP detection keywords
FUZZY_OPP_KEYWORDS = [
    # Standard
    "sea walker", "sea guardian", "sea witch", "sea archer", "rider of the deep", 
    "catfish", "carrot king", "sea leech", "guardian defender", "sea protector", 
    "hydra", "emperor", 
    # Winter
    "agarimoo", "yeti", "reindrake", "nutcracker", 
    # Spooky
    "grim reaper", "phantom fisher", "werewolf", "scarecrow", "nightmare", 
    # Shark
    "nurse shark", "blue shark", "tiger shark", "great white shark",
    # Lava
    "water worm", "poisoned water worm", "abyssal miner", "flaming worm", 
    "lava blaze", "lava pigman", "lord jawbus", "thunder", "plhlegblast", 
    "magma slug", "moogma", "pyroclastic worm", "taurus",
    # Oasis
    "oasis sheep", "oasis wolf", "oasis rabbit",
    # Passive / Misc
    #"squid", "glow squid", "chicken", "cow", "pig", "sheep", "mooshroom"
]

# ----------------------------
# INITIAL ORIENTATION (Placeholder, set on F6)
# ----------------------------
start_yaw = 0.0
start_pitch = 0.0

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def lerp(a, b, t):
    return a + (b - a) * t

def lerp_angle(a, b, t):
    # Shortest path interpolation for angles
    diff = (b - a + 180) % 360 - 180
    return a + diff * t

def ease_in_out(t):
    # Simple smoothstep or sine ease could work, smoothstep is faster
    return t * t * (3 - 2 * t)

def safe_echo(msg, force=False):
    """
    Echoes to chat if CHAT_ENABLED is True or if force is True.
    """
    if CHAT_ENABLED or force:
        try:
            m.echo(msg)
        except Exception:
            pass

def pos_to_tuple(pos):
    # Normalizes MineScript position formats
    if isinstance(pos, (list, tuple)):
        return pos[0], pos[1], pos[2]
    return pos.x, pos.y, pos.z

def select_rod_slot():
    try:
        m.player_inventory_select_slot(3)
    except Exception:
        pass

def useItem():
    try:
        m.player_press_use(True)
        m.player_press_use(False)
    except Exception:
        pass

def cast_rod():
    global line_out
    with state_lock:
        try:
            select_rod_slot()
            useItem()
            # Random sleep for human-like feeling
            time.sleep(random.uniform(0.08, 0.15))
            line_out = True
            safe_echo("cast rod")
            # Immediately locate bobber after casting
            find_bobber()
        except Exception as e:
            safe_echo(f"cast_rod_error: {e}", force=True)

def reel_rod():
    global line_out
    with state_lock:
        try:
            select_rod_slot()
            useItem()
            time.sleep(random.uniform(0.08, 0.15))
            line_out = False
            safe_echo("reel rod")
        except Exception as e:
            safe_echo(f"reel_rod_error: {e}", force=True)

def killFish():
    try:
        m.player_inventory_select_slot(0)
        useItem()
    except Exception as e:
        safe_echo(f"killFish_error: {e}")

# ----------------------------

def find_bobber():
    """Locate the bobber entity after casting and store its position and ID."""
    global latest_bobber_pos, bobber_id
    try:
        nearby = m.entities(max_distance=15)
        candidates = []
        for e in nearby:
            name = e.name.lower()
            # Exclude player
            try:
                if name == m.player_name().lower():
                    continue
            except Exception:
                pass
            if "bobber" in name or "hook" in name or getattr(e, "type", "").endswith("fishing_bobber") or "unknown" in name:
                candidates.append(e)
        if candidates:
            # Choose closest to player
            try:
                player_pos = m.player_position()
                # Ensure we have x,y,z values
                if isinstance(player_pos, (list, tuple)):
                    px, py, pz = player_pos[0], player_pos[1], player_pos[2]
                else:
                    px, py, pz = player_pos.x, player_pos.y, player_pos.z
                def dist_sq(ent):
                    pos = ent.position
                    if isinstance(pos, (list, tuple)):
                        ex, ey, ez = pos[0], pos[1], pos[2]
                    else:
                        ex, ey, ez = pos.x, pos.y, pos.z
                    return (ex - px) ** 2 + (ey - py) ** 2 + (ez - pz) ** 2
                candidates.sort(key=dist_sq)
            except Exception:
                pass
            bob = candidates[0]
            pos = bob.position
            if isinstance(pos, (list, tuple)):
                latest_bobber_pos = (pos[0], pos[1], pos[2])
            else:
                latest_bobber_pos = (pos.x, pos.y, pos.z)
            bobber_id = getattr(bob, "id", None)
            safe_echo(f"[Bobber] Detected ID {bobber_id}", force=True)
        else:
            safe_echo("[Bobber] No bobber entity found", force=True)
    except Exception as e:
        safe_echo(f"[Bobber] find error: {e}", force=True)
# ----------------------------
# MICRO CAMERA ADJUSTMENT
# ----------------------------
def micro_camera_adjustment():
    try:
        cur_yaw, cur_pitch = m.player_orientation()
    except Exception:
        return

    # Anchor to original start_yaw/start_pitch to preventing drift
    # Max deviation: +/- JITTER_DEG (very subtle)
    target_yaw = start_yaw + random.uniform(-JITTER_DEG, JITTER_DEG)
    target_pitch = start_pitch + random.uniform(-JITTER_DEG, JITTER_DEG)
    
    # Normalize
    target_yaw = target_yaw % 360
    target_pitch = max(min(target_pitch, 90), -90)

    # Duration: 0.1s - 0.2s for quick human-like twitch
    steps = random.randint(3, 6)
    
    for i in range(steps):
        if not running: break
        # Normalized time 0.0 to 1.0
        t_raw = (i + 1) / steps
        # Easing for "slerp-like" feel
        t = ease_in_out(t_raw)
        
        interp_yaw = lerp_angle(cur_yaw, target_yaw, t)
        interp_pitch = lerp(cur_pitch, target_pitch, t)
        
        try:
            m.player_set_orientation(interp_yaw, interp_pitch)
        except Exception:
            break
        time.sleep(random.uniform(0.02, 0.04))

# ----------------------------
# OPP DETECTION / KILL
# ----------------------------
def is_fuzzy_opp_nearby(max_distance=8, center_pos=None):
    """
    Detects mobs near the player or near a bobber.
    Returns the closest fuzzy OPP (from FUZZY_OPP_KEYWORDS) or None.
    """
    try:
        my_name = m.player_name().lower()
    except:
        my_name = ""

    ents = m.entities(max_distance=max_distance)
    candidates = []

    for e in ents:
        name = e.name.lower()

        # Ignore self
        if name == my_name:
            continue

        # --- Distance to bobber check ---
        if center_pos:
            try:
                ex, ey, ez = pos_to_tuple(e.position)
                bx, by, bz = center_pos

                dist_sq = (ex - bx)**2 + (ey - by)**2 + (ez - bz)**2

                # Hard radius lock (3.5 blocks)
                if dist_sq > (3.5 * 3.5):
                    continue

                # Optional debug:
                # safe_echo(f"[Debug] {e.name} dist={(dist_sq**0.5):.2f}", force=True)

            except Exception as err:
                safe_echo(f"[Debug] Position error {e.name}: {err}", force=True)
                continue

        # --- Fuzzy name match ---
        for key in FUZZY_OPP_KEYWORDS:
            if key in name:
                candidates.append(e)
                break

    if not candidates:
        return None

    # Prefer closest to bobber if available
    if center_pos:
        bx, by, bz = center_pos
        candidates.sort(
            key=lambda e: (
                (pos_to_tuple(e.position)[0] - bx)**2 +
                (pos_to_tuple(e.position)[1] - by)**2 +
                (pos_to_tuple(e.position)[2] - bz)**2
            )
        )

    return candidates[0]


def wait_for_opp_spawn(timeout=0.8, check_interval=0.05, bobber_pos=None):
    """
    Polls rapidly for an OPP to appear after reeling in.
    Returns the entity if found, w/ None otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Check specifically near bobber if we know where it was
        # Explicitly pass large max_distance to ensure we cover the bobber
        opp = is_fuzzy_opp_nearby(max_distance=5, center_pos=bobber_pos)
        if opp:
            return opp
        time.sleep(check_interval)
    return None

def handle_hooked_entity():
    global opps_killed, line_out

    bobber_pos = None

    # Ensure line is in before any action
    with state_lock:
        if line_out:
            # Try to grab bobber position BEFORE reeling
            try:
                # We need to find OUR bobber. Usually closest "fishing_bobber" or "unknown" type near hook event
                # This is a best-effort heuristics
                nearby = m.entities(max_distance=20)
                for e in nearby:
                    # heuristic: bobber entity
                    if "bobber" in e.name.lower() or getattr(e, "type", "").endswith("fishing_bobber") or "unknown" in e.name.lower():
                         # We assume the closest bobber is ours (or the one that just bit)
                         # Actually m.entities sorted by dist? Not guaranteed but likely.
                         # Just take the first valid one we see as a proxy
                         p = e.position
                         bobber_pos = (p.x, p.y, p.z)
                         break
            except:
                pass
            
            # Fallback to continuous tracking if instantaneous check failed
            if not bobber_pos and latest_bobber_pos:
                safe_echo("[Targeting] Using cached bobber position")
                bobber_pos = latest_bobber_pos

            useItem()
            line_out = False
            safe_echo("[Hooked] Reel rod in")

    # Polling for spawn instead of single sleep
    # This catches the mob instant it spawns (0.0s - 0.8s window)
    # Pass bobber_pos to narrow search
    target_opp = wait_for_opp_spawn(bobber_pos=bobber_pos)

    if target_opp:
        attack_entity(target_opp)
        return True
    else:
        safe_echo("[Catch] Catch/Nothing found")
        return False

def attack_entity(target_opp):
    global opps_killed
    # OPP detected → Engaging dynamic kill loop with HEALTH CHECK
    safe_echo(f"[OPP] Aggressive entity detected: {target_opp.name} (ID: {target_opp.id})", force=True)
    
    kill_attempts = 0
    MAX_ATTEMPTS = 10
    
    # Track by UUID if available, otherwise ID
    target_uuid = getattr(target_opp, "uuid", None)
    target_id = target_opp.id
    
    # Wait for entity to fully render/spawn
    time.sleep(random.uniform(0.6, 0.8))

    # First hit
    killFish()
    kill_attempts += 1
    # Slow down hits to avoid "too fast" / anti-cheat issues
    time.sleep(random.uniform(0.45, 0.55)) 

    while kill_attempts < MAX_ATTEMPTS:
        # Re-fetch entities to get updated status
        # Increase radius to 15 to prevent "losing" the mob if it swims away slightly
        current_ents = m.entities(max_distance=15)
        
        still_alive = False
        current_health = -1
        
        for e in current_ents:
            # Match by UUID or ID
            if (target_uuid and getattr(e, "uuid", None) == target_uuid) or e.id == target_id:
                # Found the entity
                current_health = getattr(e, "health", 0)
                # Debug log to track exactly what we are hitting
                safe_echo(f"[Debug] Attack: Found {e.name} ID:{e.id} HP:{current_health}")
                if current_health > 0:
                    still_alive = True
                break
        
        if not still_alive:
            safe_echo(f"[OPP] Entity dead/gone (Health: {current_health}). Stopping.")
            break
            
        # If still alive, hit again
        killFish()
        kill_attempts += 1
        
        # Smart Delay: If health is low (<=6, ~3 hearts), wait longer to prevent overkill
        if 0 < current_health <= 6:
            sleep_time = 0.7 # Extra long pause to confirm death
        else:
            sleep_time = random.uniform(0.35, 0.45) # Slower 2-3 CPS
            
        # safe_echo(f"[Debug] HP: {current_health} -> Waiting {sleep_time:.2f}s")
        time.sleep(sleep_time)
            
    if kill_attempts >= MAX_ATTEMPTS:
         safe_echo(f"[OPP] Max attempts reached ({MAX_ATTEMPTS}). Giving up.")
    else:
         opps_killed += 1
         safe_echo(f"[OPP] Eliminated threat #{opps_killed}", force=True)

# ----------------------------
# HEALTH MONITOR
# ----------------------------
def health_monitor():
    last_health = 20.0
    try:
        last_health = m.player_health()
    except:
        pass

    while running:
        try:
            curr_health = m.player_health()
        except:
            time.sleep(0.5)
            continue
            
        # Trigger if health drops below 18 
        if curr_health < 18:
            # Check if we actually took damage or are just low
            # But user said "health < 18", so strictly enforce defense if low
            opp = is_fuzzy_opp_nearby(max_distance=6) # Check slightly wider radius for threats
            if opp:
                safe_echo(f"[Defense] Low health ({curr_health:.1f})! Engaging {opp.name}!", force=True)
                attack_entity(opp)
                # Brief cooldown to avoid spamming if multiple enemies or lag
                time.sleep(0.5)
        
        last_health = curr_health
        time.sleep(0.1)

# ----------------------------
# TELEMETRY
# ----------------------------
telemetry_buffer = deque(maxlen=TELEMETRY_BUFFER_MAX)
telemetry_lock = threading.Lock()

def telemetry_buffer_add(entry: dict):
    with telemetry_lock:
        telemetry_buffer.append(entry)

def telemetry_dump_buffer(prefix="[Telemetry Dump]"):
    # Only for manual dumps now
    with telemetry_lock:
        if not telemetry_buffer:
            safe_echo(prefix + " (no entries)")
            return
        last = telemetry_buffer[-1]
        safe_echo(f"{prefix} entries={len(telemetry_buffer)} last=> "
                  f"Yaw:{last.get('yaw',0):.2f} Pitch:{last.get('pitch',0):.2f} "
                  f"Pos:{last.get('pos',(0,0,0))} Fish:{last.get('fish_caught',0)} Opps:{last.get('opps_killed',0)}")

def telemetry():
    last_yaw, last_pitch = start_yaw, start_pitch
    try:
        last_pos = m.player_position()
    except Exception:
        last_pos = (0.0, 0.0, 0.0)
    
    # Use Subtitle for real-time stats (less intrusive than Action Bar)
    # Initialize title times to stay up (fade_in=0, stay=72000 ticks (1h), fade_out=20)
    try:
        Gui.set_title_times(0, 72000, 20)
        Gui.set_title("") # Clear title so only subtitle shows
    except:
        pass

    while running:
        # HUD Update (Subtitle)
        try:
            Gui.set_subtitle(f"§b[Bot]§r Fish: §a{fish_caught}§r | Opps: §c{opps_killed}§r | Run: {running}")
        except Exception:
            pass

        try:
            yaw, pitch = m.player_orientation()
            pos = m.player_position()
        except Exception:
            time.sleep(0.5)
            continue

        yaw_diff = abs((yaw - last_yaw + 180) % 360 - 180)
        pitch_diff = abs(pitch - last_pitch)
        pos_diff = ((pos[0]-last_pos[0])**2 + (pos[1]-last_pos[1])**2 + (pos[2]-last_pos[2])**2)**0.5

        if yaw_diff>TELEMETRY_YAW_PITCH_THRESH or pitch_diff>TELEMETRY_YAW_PITCH_THRESH or pos_diff>TELEMETRY_POS_THRESH:
            telemetry_buffer_add({
                "ts": time.time(),
                "yaw": yaw, "pitch": pitch,
                "pos": pos,
                "fish_caught": fish_caught,
                "opps_killed": opps_killed
            })
            last_yaw, last_pitch = yaw, pitch
            last_pos = pos

        # HUD updates every 1s
        time.sleep(1.0)

# ----------------------------
# PLAYER SAFETY (Anti-Detection)
# ----------------------------
def get_look_vector(yaw, pitch):
    # MC Yaw: 0=South(+Z), 90=West(-X), 180=North(-Z), 270=East(+X)
    # Pitch: -90=Up, 90=Down
    import math
    yaw_rad = math.radians(yaw)
    pitch_rad = math.radians(pitch)
    
    # Calculate vector components
    # x = -sin(yaw) * cos(pitch)
    # y = -sin(pitch)
    # z = cos(yaw) * cos(pitch)
    
    x = -math.sin(yaw_rad) * math.cos(pitch_rad)
    y = -math.sin(pitch_rad)
    z = math.cos(yaw_rad) * math.cos(pitch_rad)
    return (x, y, z)

def get_dot_product(v1, v2):
    return v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]

def normalize(v):
    mag = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    if mag == 0: return (0,0,0)
    return (v[0]/mag, v[1]/mag, v[2]/mag)

def player_watchdog():
    # Monitors for other players nearby or in crosshairs
    # Triggers failsafe if detected
    safe_echo("[Safety] Player Watchdog active", force=True)
    
    while running:
        try:
            my_name = m.player_name()
            my_pos = m.player_position()
            my_yaw, my_pitch = m.player_orientation()
        except:
            time.sleep(1)
            continue
            
        try:
            # Get all players (assuming type='player' or filter by logic)
            # Minescript entities doesn't always strictly guarantee type strings, 
            # but usually 'player' or 'other_player'
            # We will iterate all entities and check for players (ignoring self)
            ents = m.entities(max_distance=50) # Scan decent range
            
            for e in ents:
                # Basic heuristic for player: 
                # 1. Not me
                # 2. Type contains 'player' OR has UUID (mobs have UUIDs too but usually 'player' type is distinct)
                if e.name == my_name: continue
                
                is_player = False
                etype = getattr(e, "type", "").lower()
                if "player" in etype and "bobber" not in etype:
                    is_player = True
                
                # If just check names? Some servers disguise bots. 
                # For safety, if it looks like a player (humanoid), treat as risk.
                
                if is_player:
                    epos = e.position
                    # Vector to entity
                    vec_to_player = (epos.x - my_pos.x, epos.y - my_pos.y, epos.z - my_pos.z)
                    dist = math.sqrt(vec_to_player[0]**2 + vec_to_player[1]**2 + vec_to_player[2]**2)
                    
                    # 1. Proximity to ME (< 0.5)
                    if dist < 0.5:
                        safe_echo(f"[Safety] Player {e.name} too close to ME ({dist:.2f}m)! STOPPING.", force=True)
                        failsafe()
                        return

                    # 2. Proximity to BOBBER (< 0.5)
                    if latest_bobber_pos:
                        bx, by, bz = latest_bobber_pos
                        dist_bobber = math.sqrt((epos.x - bx)**2 + (epos.y - by)**2 + (epos.z - bz)**2)
                        if dist_bobber < 0.5:
                            safe_echo(f"[Safety] Player {e.name} near BOBBER ({dist_bobber:.2f}m)! STOPPING.", force=True)
                            failsafe()
                            return
                            
                    # 3. Crosshair Check
                    # If I am looking right at them (within ~5 degrees?)
                    # Dot product 1.0 = exact match
                    # cos(5 deg) ~= 0.996
                    # cos(10 deg) ~= 0.985
                    norm_vec = normalize(vec_to_player)
                    look_vec = get_look_vector(my_yaw, my_pitch)
                    dot = get_dot_product(norm_vec, look_vec)
                    
                    if dot > 0.995: # Very tight cone (approx 5-6 degrees total)
                         safe_echo(f"[Safety] Player {e.name} in CROSSHAIRS! STOPPING.", force=True)
                         failsafe()
                         return
                         
        except Exception as e:
            # safe_echo(f"[Watchdog Error] {e}")
            pass
            
        time.sleep(0.5)

# ----------------------------
# FAILSAFE
# ----------------------------
def play_alarm():
    # Play a distinct sound using system audio (macOS)
    try:
        safe_echo("[Debug] Playing System Alarm", force=True)
        # "Glass" is a sharp standard macOS sound
        os.system("afplay /System/Library/Sounds/Glass.aiff &")
        time.sleep(0.2)
        os.system("afplay /System/Library/Sounds/Glass.aiff &")
        time.sleep(0.2)
        os.system("afplay /System/Library/Sounds/Glass.aiff &")
    except Exception as e:
        safe_echo(f"[Debug] System Alarm Failed: {e}", force=True)

def player_watchdog():
    # Monitors for other players nearby or in crosshairs
    safe_echo("[Safety] Player Watchdog active", force=True)
    
    while running:
        if stop_event.is_set(): break
        
        try:
            my_name = m.player_name()
            my_pos = m.player_position()
            my_yaw, my_pitch = m.player_orientation()
        except:
            time.sleep(1)
            continue
            
        try:
            ents = m.entities(max_distance=50)
            
            # DEBUG: Uncomment to see what entities are around
            # player_names = [e.name for e in ents if "player" in getattr(e,"type","").lower()]
            # if player_names: safe_echo(f"[Debug] Players found: {player_names}")

            for e in ents:
                # Ignore self
                if e.name == my_name: continue
                
                # Broaden "Player" detection:
                # 1. Type contains "player" (standard)
                # 2. Type is "unknown" (common for remote players on some servers)
                # 3. Name is not in exclusion list (mobs usually have standard names, players have custom)
                # For safety, let's stick to "player" in type OR specific visual checks if needed.
                
                etype = getattr(e, "type", "").lower()
                is_player = "player" in etype and "bobber" not in etype
                
                if is_player:
                    epos = e.position
                    dist = math.sqrt((epos.x - my_pos.x)**2 + (epos.y - my_pos.y)**2 + (epos.z - my_pos.z)**2)
                    
                    # 1. Proximity to ME (< 1.5 blocks - increased from 0.5 for reliability)
                    if dist < 1.5:
                        safe_echo(f"[Safety] Player {e.name} too close to ME ({dist:.2f}m)! STOPPING.", force=True)
                        failsafe()
                        return

                    # 2. Proximity to BOBBER (< 1.5 blocks - increased from 0.5)
                    if latest_bobber_pos:
                        bx, by, bz = latest_bobber_pos
                        dist_bobber = math.sqrt((epos.x - bx)**2 + (epos.y - by)**2 + (epos.z - bz)**2)
                        if dist_bobber < 1.5:
                            safe_echo(f"[Safety] Player {e.name} near BOBBER ({dist_bobber:.2f}m)! STOPPING.", force=True)
                            failsafe()
                            return
                            
                    # 3. Crosshair Check
                    vec_to_player = (epos.x - my_pos.x, epos.y - my_pos.y, epos.z - my_pos.z)
                    norm_vec = normalize(vec_to_player)
                    look_vec = get_look_vector(my_yaw, my_pitch)
                    dot = get_dot_product(norm_vec, look_vec)
                    
                    if dot > 0.99: # Relaxed slightly (approx 8 degrees)
                         safe_echo(f"[Safety] Looking at Player {e.name}! STOPPING.", force=True)
                         failsafe()
                         return
                         
        except Exception as e:
            pass
            
        time.sleep(0.5)

def failsafe():
    global running
    
    # Atomic check: if already stopped, don't spam
    if not running:
        return
        
    with state_lock:
        if not running: # Double check inside lock
            return
        running = False # Set flag IMMEDIATELY inside lock
        stop_event.set()

    safe_echo("Failsafe triggered → stopping fishing", force=True)
    telemetry_dump_buffer(prefix="[Failsafe Dump]")
    
    # Run alarm in separate thread to not block shutdown
    threading.Thread(target=play_alarm, daemon=True).start()
    # Do not reel. INSTANT STOP.
    # User requested no "jerking" of controls.

def orientation_check():
    prev_yaw, prev_pitch = start_yaw, start_pitch
    first_loop = True
    while running:
        if stop_event.is_set(): break
        
        try:
            yaw, pitch = m.player_orientation()
        except Exception:
            time.sleep(0.05)
            continue

        yaw_diff = abs((yaw - prev_yaw + 180) % 360 - 180)
        pitch_diff = abs(pitch - prev_pitch)
        if abs(pitch_diff) == CROUCH_DELTA:
            pitch_diff = 0

        if not first_loop:
            if yaw_diff > YAW_THRESHOLD or pitch_diff > PITCH_THRESHOLD:
                safe_echo(f"Orientation fail: ΔYaw:{yaw_diff:.2f} ΔPitch:{pitch_diff:.2f}")
                failsafe()
                break
        first_loop = False
        prev_yaw, prev_pitch = yaw, pitch
        time.sleep(0.05)

# ----------------------------
# RANDOM MOVEMENT
# ----------------------------
def random_movement():
    try:
        m.player_press_sneak(True)
    except Exception:
        pass
    try:
        orig_x, orig_y, orig_z = m.player_position()
    except Exception:
        orig_x, orig_y, orig_z = 0.0,0.0,0.0
    center_x = round(orig_x)
    center_z = round(orig_z)

    while running:
        try:
            x, y, z = m.player_position()
        except Exception:
            time.sleep(0.2)
            continue

        dx = x - center_x
        dz = z - center_z
        horiz_dist = (dx*dx + dz*dz)**0.5

        # Randomized movement with constraint
        want_forward = random.random()<MOVE_PROB_FORWARD and horiz_dist<MAX_HORIZ_DIST
        want_backward = random.random()<MOVE_PROB_BACKWARD
        want_left = random.random()<MOVE_PROB_STRAFE
        want_right = random.random()<MOVE_PROB_STRAFE

        if horiz_dist>=MAX_HORIZ_DIST:
            want_forward=False
            want_backward=False
            to_center_x = center_x - x
            to_center_z = center_z - z
            if abs(to_center_x) > abs(to_center_z):
                want_forward = to_center_x>0
                want_backward = to_center_x<0
            else:
                want_right = to_center_z>0
                want_left = to_center_z<0

        try:
            m.player_press_forward(bool(want_forward))
            m.player_press_backward(bool(want_backward))
            m.player_press_left(bool(want_left))
            m.player_press_right(bool(want_right))
        except Exception:
            pass

        time.sleep(random.uniform(MOVE_DURATION_MIN,MOVE_DURATION_MAX))

        # stop movement
        try:
            m.player_press_forward(False)
            m.player_press_backward(False)
            m.player_press_left(False)
            m.player_press_right(False)
        except Exception:
            pass

        if random.random()<PAUSE_PROB:
            time.sleep(random.uniform(PAUSE_MIN,PAUSE_MAX))

        if random.random()<0.80:
            micro_camera_adjustment()
            


# ----------------------------
# FISHING MONITOR (with guaranteed recast)
# ----------------------------

def monitorEntity():
    global running, fish_caught, line_out, latest_bobber_pos
    running = True
    stop_event.clear()

    try:
        m.player_press_sneak(True)
    except Exception:
        pass
    time.sleep(random.uniform(0.08,0.15))

    last_cast_time = 0

    # Initial rod cast
    if not line_out:
        cast_rod()
        last_cast_time = time.time()
    safe_echo("initial cast done", force=True)

    MAX_CAST_WAIT = 15.0

    while running and not stop_event.is_set():
        # Handle hooked entities
        try:
            hooked_entities = m.entities(name="!!!", max_distance=20)
        except Exception:
            hooked_entities = []

        for e in hooked_entities:
            handled = handle_hooked_entity()
            if not handled:
                fish_caught += 1
            # Reset cast time if we reeled in (handled usually reels in)
            # Actually handle_hooked_entity sets line_out=False. 
            # The next loop iteration will see line_out=False and recast.

        # **Guaranteed recast if rod is missing**
        if not line_out:
            # safe_echo("Rod missing → recasting automatically") # Too spammy
            cast_rod()
            last_cast_time = time.time()
            
        # **Bobber Watchdog**: If line is out but no bobber entity found, reset
        # Only check if it's been >2.0s since cast to allow bobber to spawn
        time_since_cast = time.time() - last_cast_time
        
        # 1. Stuck Bobber Timeout
        if line_out and time_since_cast > MAX_CAST_WAIT:
             safe_echo("[Watchdog] Cast timed out (stuck?). Resetting.", force=True)
             # Explicitly reel in to clear the stuck bobber
             reel_rod()
             # reel_rod sets line_out=False
             # We pause briefly to let the reel animation finish
             time.sleep(0.5)
             # Next loop iteration will see line_out=False and trigger cast_rod()
        
        # 2. Despawned Bobber Check
        elif line_out and (time_since_cast > 2.0):
            # Check for bobber entity nearby
            try:
                # Look for entities with 'bobber' in name or type 'fishing_bobber' implies checking type
                # minescript entities() returns objects with .name and .type usually
                nearby = m.entities(max_distance=15)
                bobber_found = False
                for e in nearby:
                    # Check name or type if available (using safe getattr)
                    if "bobber" in e.name.lower() or "hook" in e.name.lower():
                        bobber_found = True
                        try:
                            p = e.position
                            latest_bobber_pos = (p.x, p.y, p.z)
                        except:
                            pass
                        break
                    if getattr(e, "type", "").endswith("fishing_bobber"):
                        bobber_found = True
                        try:
                            p = e.position
                            latest_bobber_pos = (p.x, p.y, p.z)
                        except:
                            pass
                        break
                
                # DEBUG: If we can't find it, what IS there?
                if not bobber_found and time.time() % 5.0 < 0.2:
                    names = [f"{x.name}/{getattr(x,'type','?')}" for x in nearby if "player" not in x.name.lower()]
                    safe_echo(f"[Debug] Bobber Missing. Nearby: {names}", force=True)
                    
                if not bobber_found:
                    # Double check with a small delay to avoid flicker
                    time.sleep(0.2)
                    nearby2 = m.entities(max_distance=20)
                    for e in nearby2:
                         if "bobber" in e.name.lower() or "hook" in e.name.lower() or getattr(e, "type", "").endswith("fishing_bobber"):
                            bobber_found = True
                            break
                            
                    if not bobber_found:
                        safe_echo("[Watchdog] Bobber entity lost! Forcing reset.", force=True)
                        line_out = False
                        # Loop will recast next iteration
            except Exception:
                pass

        time.sleep(0.2)

    try:
        m.player_press_sneak(False)
    except Exception:
        pass
    running = False
    stop_event.set()
    safe_echo("Fishing stopped", force=True)

# ----------------------------
# MAIN EVENT LOOP
# ----------------------------
with EventQueue() as event_queue:
    event_queue.register_key_listener()
    event_queue.register_chat_listener()
    safe_echo("Press F6 to start fishing, F7 to stop fishing.", force=True)

    while True:
        event = event_queue.get()
        if event.type==EventType.KEY:
            if event.key==295 and event.action==1: # F6 start
                if not running:
                    # Capture initial orientation NOW
                    try:
                        start_yaw, start_pitch = m.player_orientation()
                        safe_echo(f"Anchored at Yaw:{start_yaw:.1f} Pitch:{start_pitch:.1f}", force=True)
                    except Exception:
                        start_yaw, start_pitch = 0.0, 0.0
                        safe_echo("Failed to capture orientation (using 0,0)", force=True)
                        
                    safe_echo("Starting bot threads...", force=True)
                    threading.Thread(target=monitorEntity, daemon=True).start()
                    threading.Thread(target=orientation_check, daemon=True).start()
                    threading.Thread(target=telemetry, daemon=True).start()
                    #threading.Thread(target=random_movement, daemon=True).start()
                    #threading.Thread(target=health_monitor, daemon=True).start()
                    threading.Thread(target=player_watchdog, daemon=True).start()
                else:
                    safe_echo("Already running", force=True)
            elif event.key==296 and event.action==1: # F7 stop
                if running:
                    safe_echo("Stop requested → shutting down", force=True)
                    stop_event.set()
                    running=False
                else:
                    safe_echo("Not running", force=True)
        elif event.type==EventType.CHAT:
            msg = event.message.lower()
            
            # Only check safety if bot is running
            if running:
                # Ignore my own messages
                my_name = m.player_name()
                # Check if message starts with my name (e.g. "<MyName> msg" or "[Rank] MyName: msg")
                # Using simple string check on lower case msg
                if my_name and my_name.lower() in msg.split(":")[0]:
                    pass # It's me talking
                else:
                    # Safety Check
                    for kw in CHAT_ALERT_KEYWORDS:
                        if kw in msg:
                            safe_echo(f"[Safety] Chat alert detected keyword '{kw}'! STOPPING.", force=True)
                            failsafe()
                            break
            
            if "dump telemetry" in msg:
                telemetry_dump_buffer(prefix="[Manual Dump]")
            if "status" in msg:
                safe_echo(f"Status: running={running}, fish={fish_caught}, opps={opps_killed}", force=True)
            if "toggle chat" in msg:
                CHAT_ENABLED = not CHAT_ENABLED
                safe_echo(f"Chat telemetry {'enabled' if CHAT_ENABLED else 'disabled'}", force=True)
