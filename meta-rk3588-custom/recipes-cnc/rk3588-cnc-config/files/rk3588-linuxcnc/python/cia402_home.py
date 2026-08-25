#!/usr/bin/env python3
# cia402_home.py — HAL userspace component for drive-side hard-stop homing.
#
# Coordinates CiA402 Homing mode on MOONS'/AMP SSDC06-ECX-H using manufacturer
# methods -3/-4 (collision / hard-stop, no home switch required).
#
# Per SSDC EtherCAT User Manual §3.6:
#   Controlword bit4  = Homing operation start  (0x0010)  → start = 0x001F
#   Controlword bit8  = Halt
#   Statusword  bit10 = Target reached
#   Statusword  bit12 = Homing attained
#   Statusword  bit13 = Homing error
#   0x2202            = Hardstop current limit (mA / 10, same as continuous current)
#
# Sequence on rising edge of home-request:
#   1. Write SDO: method, speeds, accel, offset, hardstop current
#   2. Shutdown → Modes of operation = 6 (Homing)
#   3. Switch on → Enable operation (0x000F) with bit4 low
#   4. Rising edge bit4: 0x000F → 0x001F to start homing
#   5. Drive: hard-stop → (if 0x2036=1) reverse by 0x607C → set zero
#   6. Wait for statusword bit12+bit10 (success) or bit13/fault
#   7. Clear bit4, switch back to CSP (opmode=8), assert home-done
#
# HAL pins:
#   home-request       HAL_IN  bit
#   home-done          HAL_OUT bit
#   home-fault         HAL_OUT bit
#   homing-active      HAL_OUT bit
#   home-position      HAL_OUT float   (mm)
#   cia-controlword    HAL_OUT u32
#   cia-statusword     HAL_IN  u32
#   srv-opmode         HAL_OUT s32
#   actual-position    HAL_IN  s32
#   input-scale        HAL_IN  float   (counts/mm)
#   slave-position     HAL_IN  s32
#   homing-method      HAL_IN  s32     (default -4 = leftward hard stop)
#   search-speed-mm-s  HAL_IN  float   (default 5.0 — keep low for collision)
#   hardstop-current   HAL_IN  u32     (0 = auto ~20% of 0x2200 continuous)
#   home-offset-mm     HAL_IN  float   (backoff after hard-stop; method -4 use +mm)

import hal
import time
import subprocess
import sys


class Cia402Home:
    IDLE = 0
    WRITE_PARAMS = 1
    SWITCH_TO_HOMING = 2
    ENABLE_AND_START = 3
    WAIT_HOMING = 4
    READ_POSITION = 5
    SWITCH_TO_CSP = 6
    DONE = 7
    FAULT = 8

    # CiA402 Homing controlword / statusword bits (SSDC manual §3.6.2)
    CW_SHUTDOWN = 0x0006
    CW_SWITCH_ON = 0x0007
    CW_ENABLE = 0x000F
    CW_HOME_START = 0x001F   # enable + Homing operation start (bit4)
    CW_FAULT_RESET = 0x0080

    SW_BIT_READY_TO_SWITCH_ON = 0
    SW_BIT_SWITCHED_ON = 1
    SW_BIT_OP_ENABLED = 2
    SW_BIT_FAULT = 3
    SW_BIT_SWITCH_ON_DISABLED = 6
    SW_BIT_TARGET_REACHED = 10
    SW_BIT_HOMING_ATTAINED = 12
    SW_BIT_HOMING_ERROR = 13

    def __init__(self, h, comp_name="cia402_home"):
        self.h = h
        self.comp_name = comp_name
        self.state = self.IDLE
        self.state_timer = 0
        self.slave_pos = 0
        self.home_position_counts = 0
        self.home_position_mm = 0.0
        self.input_scale = 819.2
        self.homing_method = -4
        self.search_speed = 0
        self.search_zero_speed = 0
        self.homing_accel = 0
        self.home_offset = 0          # counts → 0x607C
        self.move_home_offset = 1     # 0x2036: 1 = move offset after hard-stop
        self.hardstop_current = 0     # units: same as 0x2200 (value 100 = 1.00 A)

    def _enable_controlword(self, statusword):
        """Advance CiA402 state machine toward Operation Enabled (CSP idle)."""
        if statusword & (1 << self.SW_BIT_FAULT):
            return self.CW_FAULT_RESET
        if statusword & (1 << self.SW_BIT_SWITCH_ON_DISABLED):
            return self.CW_SHUTDOWN
        if (statusword & (1 << self.SW_BIT_READY_TO_SWITCH_ON)) and not (
            statusword & (1 << self.SW_BIT_SWITCHED_ON)
        ):
            return self.CW_SWITCH_ON
        if (statusword & (1 << self.SW_BIT_SWITCHED_ON)) and not (
            statusword & (1 << self.SW_BIT_OP_ENABLED)
        ):
            return self.CW_ENABLE
        if statusword & (1 << self.SW_BIT_OP_ENABLED):
            return self.CW_ENABLE
        return self.CW_SHUTDOWN

    def ethercat_download(self, index, subindex, value, dtype):
        cmd = [
            "ethercat", "download",
            "-p", str(self.slave_pos),
            "-t", dtype,
            "--",
            hex(index), str(subindex), str(value),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                print(
                    f"[cia402_home] SDO download 0x{index:04x}:{subindex}={value} "
                    f"failed: {result.stderr.strip()}",
                    file=sys.stderr,
                )
                return False
            return True
        except Exception as e:
            print(f"[cia402_home] SDO download exception: {e}", file=sys.stderr)
            return False

    def ethercat_upload(self, index, subindex, dtype):
        cmd = [
            "ethercat", "upload",
            "-p", str(self.slave_pos),
            "-t", dtype,
            "--",
            hex(index), str(subindex),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return (False, 0)
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return (True, int(parts[1], 0))
            return (False, 0)
        except Exception:
            return (False, 0)

    def _refresh_params_from_pins(self):
        h = self.h
        self.slave_pos = int(h["slave-position"])
        self.input_scale = float(h["input-scale"])
        self.homing_method = int(h["homing-method"])
        speed_mm = float(h["search-speed-mm-s"])
        if speed_mm <= 0:
            speed_mm = 5.0
        # Cap collision speed — hard-stop at high speed damages mechanics.
        if speed_mm > 50.0:
            print(
                f"[cia402_home] WARNING: search-speed-mm-s={speed_mm} too high for "
                f"hard-stop; clamping to 50 mm/s",
                file=sys.stderr,
            )
            speed_mm = 50.0
        self.search_speed = max(1, int(speed_mm * self.input_scale))
        # Zero/backoff speed (0x6099:2) — used after collision reverse move
        self.search_zero_speed = max(1, int(self.search_speed * 0.5))
        # Mild accel for hard-stop (200 mm/s^2)
        self.homing_accel = max(1, int(self.input_scale * 200))
        # Method -4 (left hard-stop): positive offset = reverse toward + direction
        offset_mm = float(h["home-offset-mm"])
        self.home_offset = int(round(offset_mm * self.input_scale))
        # SSDC 0x2036: 0=stay at hard-stop; 1=move home-offset then set zero there
        self.move_home_offset = 1 if self.home_offset != 0 else 0
        pin_hs = int(h["hardstop-current"])
        if pin_hs > 0:
            self.hardstop_current = pin_hs
        else:
            ok, cont = self.ethercat_upload(0x2200, 0, "uint16")
            if ok and cont > 0:
                # Soft collision: ~20% continuous (was 50%, too aggressive)
                self.hardstop_current = max(30, cont // 5)
            else:
                self.hardstop_current = 100  # 1.0 A fallback

    def run(self):
        h = self.h
        prev_home_req = False

        while True:
            home_req = bool(h["home-request"])
            statusword = int(h["cia-statusword"]) & 0xFFFF
            actual_pos = int(h["actual-position"])
            self.input_scale = float(h["input-scale"]) or 819.2

            if self.state == self.IDLE:
                h["cia-controlword"] = self._enable_controlword(statusword)
                h["srv-opmode"] = 8  # CSP
                h["home-done"] = False
                h["home-fault"] = False
                h["homing-active"] = False

                if home_req and not prev_home_req:
                    self._refresh_params_from_pins()
                    print(
                        f"[cia402_home] Homing start: method={self.homing_method}, "
                        f"speed={self.search_speed} counts/s "
                        f"({self.search_speed / self.input_scale:.2f} mm/s), "
                        f"offset={self.home_offset} counts "
                        f"({self.home_offset / self.input_scale:.2f} mm, "
                        f"0x2036={self.move_home_offset}), "
                        f"hardstop_I={self.hardstop_current}",
                        file=sys.stderr,
                    )
                    self.state = self.WRITE_PARAMS
                    self.state_timer = 0
                    h["home-done"] = False
                    h["home-fault"] = False
                    h["homing-active"] = True

            elif self.state == self.WRITE_PARAMS:
                # Keep enabled in CSP while writing SDOs
                h["cia-controlword"] = self.CW_ENABLE
                h["srv-opmode"] = 8
                self.state_timer += 1

                ok = True
                if self.state_timer == 1:
                    ok = self.ethercat_download(0x6098, 0, self.homing_method, "int8")
                elif self.state_timer == 2:
                    ok = self.ethercat_download(0x6099, 1, self.search_speed, "uint32")
                elif self.state_timer == 3:
                    ok = self.ethercat_download(
                        0x6099, 2, self.search_zero_speed, "uint32"
                    )
                elif self.state_timer == 4:
                    ok = self.ethercat_download(0x609a, 0, self.homing_accel, "uint32")
                elif self.state_timer == 5:
                    ok = self.ethercat_download(0x607c, 0, self.home_offset, "int32")
                elif self.state_timer == 6:
                    # ECX-H: move home-offset after hard-stop, then set that as zero
                    ok = self.ethercat_download(
                        0x2036, 0, self.move_home_offset, "uint16"
                    )
                elif self.state_timer == 7:
                    # Hard-stop collision current (SSDC 0x2202)
                    ok = self.ethercat_download(
                        0x2202, 0, self.hardstop_current, "uint16"
                    )
                elif self.state_timer >= 12:
                    print(
                        "[cia402_home] Params written, switching to Homing mode",
                        file=sys.stderr,
                    )
                    self.state = self.SWITCH_TO_HOMING
                    self.state_timer = 0

                if not ok:
                    print("[cia402_home] SDO write failed", file=sys.stderr)
                    self.state = self.FAULT
                    self.state_timer = 0

            elif self.state == self.SWITCH_TO_HOMING:
                # Shutdown → set opmode=6 → wait for Ready to switch on
                self.state_timer += 1
                if self.state_timer <= 50:
                    h["cia-controlword"] = self.CW_SHUTDOWN
                    h["srv-opmode"] = 8
                elif self.state_timer <= 100:
                    h["cia-controlword"] = self.CW_SHUTDOWN
                    h["srv-opmode"] = 6
                else:
                    # Wait until Ready to switch on (bit0) and not Switch on disabled
                    ready = bool(statusword & (1 << self.SW_BIT_READY_TO_SWITCH_ON))
                    sod = bool(statusword & (1 << self.SW_BIT_SWITCH_ON_DISABLED))
                    if ready and not sod:
                        print(
                            f"[cia402_home] Ready for Switch on, "
                            f"statusword=0x{statusword:04x}",
                            file=sys.stderr,
                        )
                        self.state = self.ENABLE_AND_START
                        self.state_timer = 0
                    elif self.state_timer > 2000:
                        print(
                            f"[cia402_home] Timeout waiting Ready to switch on "
                            f"(sw=0x{statusword:04x})",
                            file=sys.stderr,
                        )
                        self.state = self.FAULT
                        self.state_timer = 0
                    else:
                        h["cia-controlword"] = self.CW_SHUTDOWN
                        h["srv-opmode"] = 6

            elif self.state == self.ENABLE_AND_START:
                # Enable with bit4=0, then rising edge on bit4 (0x000F → 0x001F)
                h["srv-opmode"] = 6
                self.state_timer += 1

                if self.state_timer <= 50:
                    h["cia-controlword"] = self.CW_SWITCH_ON
                elif self.state_timer <= 150:
                    h["cia-controlword"] = self.CW_ENABLE  # bit4 clear
                    if not (statusword & (1 << self.SW_BIT_OP_ENABLED)):
                        # Stay until Operation Enabled
                        if self.state_timer > 140:
                            self.state_timer = 100  # keep trying enable
                elif self.state_timer == 151:
                    print(
                        f"[cia402_home] Homing start edge 0x001F, "
                        f"statusword=0x{statusword:04x}",
                        file=sys.stderr,
                    )
                    h["cia-controlword"] = self.CW_HOME_START
                else:
                    h["cia-controlword"] = self.CW_HOME_START
                    if self.state_timer >= 170:
                        self.state = self.WAIT_HOMING
                        self.state_timer = 0

                if statusword & (1 << self.SW_BIT_FAULT):
                    print(
                        f"[cia402_home] Fault while enabling: sw=0x{statusword:04x}",
                        file=sys.stderr,
                    )
                    self.state = self.FAULT
                    self.state_timer = 0

            elif self.state == self.WAIT_HOMING:
                h["cia-controlword"] = self.CW_HOME_START
                h["srv-opmode"] = 6
                self.state_timer += 1

                attained = bool(statusword & (1 << self.SW_BIT_HOMING_ATTAINED))
                target = bool(statusword & (1 << self.SW_BIT_TARGET_REACHED))
                herr = bool(statusword & (1 << self.SW_BIT_HOMING_ERROR))
                fault = bool(statusword & (1 << self.SW_BIT_FAULT))

                if herr or fault:
                    print(
                        f"[cia402_home] Homing FAILED! statusword=0x{statusword:04x}",
                        file=sys.stderr,
                    )
                    self.state = self.FAULT
                    self.state_timer = 0
                elif attained and target:
                    # Manual: bit12=1 bit10=1 → completed successfully
                    # (includes reverse move when 0x2036=1)
                    print(
                        f"[cia402_home] Homing completed (attained+target), "
                        f"statusword=0x{statusword:04x}",
                        file=sys.stderr,
                    )
                    self.state = self.READ_POSITION
                    self.state_timer = 0
                elif attained and self.move_home_offset == 0 and self.state_timer > 500:
                    # No backoff: some FW set attained before target on hard-stop
                    print(
                        f"[cia402_home] Homing attained (bit12), accepting "
                        f"statusword=0x{statusword:04x}",
                        file=sys.stderr,
                    )
                    self.state = self.READ_POSITION
                    self.state_timer = 0
                elif attained and self.move_home_offset != 0 and not target:
                    # Still reversing off the hard-stop — keep waiting for bit10
                    if self.state_timer % 1000 == 0:
                        print(
                            f"[cia402_home] hard-stop found, backing off... "
                            f"sw=0x{statusword:04x} pos={actual_pos}",
                            file=sys.stderr,
                        )
                elif self.state_timer > 60000:  # 60 s @ 1 ms
                    print("[cia402_home] Homing TIMEOUT!", file=sys.stderr)
                    self.state = self.FAULT
                    self.state_timer = 0
                elif self.state_timer % 1000 == 0:
                    print(
                        f"[cia402_home] waiting... sw=0x{statusword:04x} "
                        f"pos={actual_pos} t={self.state_timer}ms",
                        file=sys.stderr,
                    )

            elif self.state == self.READ_POSITION:
                # Clear Homing start bit; stay in Homing mode briefly
                h["cia-controlword"] = self.CW_ENABLE
                h["srv-opmode"] = 6
                self.state_timer += 1
                if self.state_timer >= 20:
                    self.home_position_counts = actual_pos
                    self.home_position_mm = self.home_position_counts / self.input_scale
                    h["home-position"] = self.home_position_mm
                    print(
                        f"[cia402_home] Home position: {self.home_position_counts} "
                        f"counts = {self.home_position_mm:.4f} mm",
                        file=sys.stderr,
                    )
                    self.state = self.SWITCH_TO_CSP
                    self.state_timer = 0

            elif self.state == self.SWITCH_TO_CSP:
                h["cia-controlword"] = self.CW_ENABLE
                h["srv-opmode"] = 8
                self.state_timer += 1
                if self.state_timer >= 50:
                    print(
                        "[cia402_home] Back to CSP, asserting home-done",
                        file=sys.stderr,
                    )
                    self.state = self.DONE
                    self.state_timer = 0

            elif self.state == self.DONE:
                h["cia-controlword"] = self._enable_controlword(statusword)
                h["srv-opmode"] = 8
                h["home-done"] = True
                h["home-fault"] = False
                h["homing-active"] = False
                if not home_req:
                    self.state = self.IDLE

            elif self.state == self.FAULT:
                h["cia-controlword"] = self.CW_FAULT_RESET
                h["srv-opmode"] = 8
                h["home-done"] = False
                h["home-fault"] = True
                h["homing-active"] = False
                self.state_timer += 1
                if self.state_timer > 200 and not home_req:
                    self.state = self.IDLE
                    self.state_timer = 0

            prev_home_req = home_req
            time.sleep(0.001)


def main():
    comp_name = "cia402_home"
    h = hal.component(comp_name)

    h.newpin("home-request", hal.HAL_BIT, hal.HAL_IN)
    h.newpin("home-done", hal.HAL_BIT, hal.HAL_OUT)
    h.newpin("home-fault", hal.HAL_BIT, hal.HAL_OUT)
    h.newpin("homing-active", hal.HAL_BIT, hal.HAL_OUT)
    h.newpin("home-position", hal.HAL_FLOAT, hal.HAL_OUT)
    h.newpin("cia-controlword", hal.HAL_U32, hal.HAL_OUT)
    h.newpin("cia-statusword", hal.HAL_U32, hal.HAL_IN)
    h.newpin("srv-opmode", hal.HAL_S32, hal.HAL_OUT)
    h.newpin("actual-position", hal.HAL_S32, hal.HAL_IN)
    h.newpin("input-scale", hal.HAL_FLOAT, hal.HAL_IN)
    h.newpin("slave-position", hal.HAL_S32, hal.HAL_IN)
    h.newpin("homing-method", hal.HAL_S32, hal.HAL_IN)
    h.newpin("search-speed-mm-s", hal.HAL_FLOAT, hal.HAL_IN)
    h.newpin("hardstop-current", hal.HAL_U32, hal.HAL_IN)
    h.newpin("home-offset-mm", hal.HAL_FLOAT, hal.HAL_IN)

    h["home-done"] = False
    h["home-fault"] = False
    h["homing-active"] = False
    h["home-position"] = 0.0
    h["cia-controlword"] = 0x000F
    h["srv-opmode"] = 8
    h["input-scale"] = 819.2
    h["slave-position"] = 0
    h["homing-method"] = -4
    h["search-speed-mm-s"] = 5.0
    h["hardstop-current"] = 100  # 1.0 A soft collision
    h["home-offset-mm"] = 5.0    # reverse 5 mm after hard-stop

    h.ready()

    # Allow HAL nets/setp from core_lcec.hal to apply
    time.sleep(0.5)
    home = Cia402Home(h, comp_name)
    print(
        f"[cia402_home] ready: method={int(h['homing-method'])}, "
        f"speed={float(h['search-speed-mm-s'])} mm/s, "
        f"offset={float(h['home-offset-mm'])} mm, "
        f"hardstop_I={int(h['hardstop-current'])}",
        file=sys.stderr,
    )

    try:
        home.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
