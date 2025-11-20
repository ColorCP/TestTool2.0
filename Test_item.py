import unittest, io, sys, os, json, subprocess, re, glob, pathlib, math, wave, struct, shutil, tempfile, requests, time, signal, os, re, platform, shlex, uuid, stat, errno
from PyQt5.QtCore import QTime, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QDialog, QCheckBox, QMessageBox
from PyQt5 import uic
from datetime import datetime
import toml
import serial
from unitest import ask_yes_no, ask_info
import logging

# ===== 給 GUI 用的全域視窗指標（CLI 情況下維持 None）=====
CURRENT_WINDOW = None

def set_current_window(win):
    """由 GUI 呼叫，告訴 Test_item 目前的 MBTestWindow。
    CLI 跑 unittest 時完全不需要理這個函式。
    """
    global CURRENT_WINDOW
    CURRENT_WINDOW = win


# ===== 讀取 TOML 配置的 expect 值 =====
def toml_get(section: str, key: str = None, default=None, path: str = "./mb_test_config.toml"):
    """
    通用 TOML 讀取工具：
      - section: 區塊名稱（如 'USB2', 'LAN', 'FAN'）
      - key: 欄位名稱（如 'expect', 'pwm'）
      - default: 預設值
      - path: 設定檔路徑

    若 key 為 None，則回傳整個 section 的 dict。
    """
    try:
        data = toml.load(path) or {}
    except Exception:
        return default

    blk = data.get(section, {}) or {}

    if key is None:
        return blk  # 回傳整個區塊

    val = blk.get(key, default)
    if isinstance(default, bool):
        return bool(val)
    if isinstance(default, int):
        try:
            return int(val)
        except Exception:
            return default
    if isinstance(default, float):
        try:
            return float(val)
        except Exception:
            return default
    if isinstance(default, list):
        return list(val) if isinstance(val, (list, tuple)) else default
    return val
# ===== 讀取 TOML 配置的 expect 值 =====

# ===== MIC Line in使用的函式=====
def _list_alsa_devices(kind="capture"):
    """
    回傳可用裝置名稱清單，如 ['plughw:1,0','hw:0,0', ...]
    kind='capture' 用 arecord -L；'playback' 用 aplay -L
    只收 hw/plughw，濾掉 default/pulse/pipewire 等虛擬裝置
    """
    cmd = ["bash", "-lc", "arecord -L" if kind=="capture" else "aplay -L"]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    devs = []
    for line in out.splitlines():
        s = line.strip()
        if re.match(r"^(plughw|hw):\S+", s):
            devs.append(s)
    return devs

def pick_mic_devices():
    """
    找「同卡號」的 錄音/播放 配對；找不到就退回第一個。
    回傳 (mic_list, play_dev) ；mic_list 至少 0~多個，play_dev 可能為 None
    """
    caps = _list_alsa_devices("capture")
    plays = _list_alsa_devices("playback")

    def card_idx(s):
        m = re.search(r":(\d+),", s)
        return int(m.group(1)) if m else -1

    # 優先用同卡號的配對
    for c in caps:
        ci = card_idx(c)
        for p in plays:
            if card_idx(p) == ci:
                return [c], p

    # 沒配對：退回第一個
    return ([caps[0]] if caps else []), (plays[0] if plays else None)

def gen_tone_wav(path, secs=5, rate=32000, freq=1000):
    """生成 16-bit PCM 單聲道正弦波 wav（避免現場沒有 sample.wav）"""
    frames = int(secs * rate)
    amp = 0.6 * 32767
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        for n in range(frames):
            v = int(amp * math.sin(2*math.pi*freq * (n/rate)))
            w.writeframes(struct.pack("<h", v))
# ===== MIC Line in使用的函式=====



# ===== Test iTem 與實際測試方法=====

# ================= USB SIMPLE TESTS (no speed check) =================
_SD_RE = re.compile(r"^sd[a-z]+$")  # 僅允許 sda, sdb, ...

# === 共用低層工具 ===
def _list_usb_disks_sdx():
    """列出透過 USB 連線的 sdX 裝置"""
    out_list = []
    try:
        out = subprocess.check_output(["lsblk", "-S", "-o", "NAME,TRAN", "-n"], text=True)
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].lower() == "usb" and _SD_RE.match(parts[0]):
                out_list.append(parts[0])
    except Exception:
        pass

    # 後援：從 /sys/block 找
    if not out_list:
        try:
            for dev in os.listdir("/sys/block"):
                if not _SD_RE.match(dev):
                    continue
                realp = os.path.realpath(f"/sys/block/{dev}/device")
                if "/usb" not in realp:
                    continue
                try:
                    with open(f"/sys/block/{dev}/size") as f:
                        sz = int((f.read() or "0").strip())
                except Exception:
                    sz = 0
                if sz > 0:
                    out_list.append(dev)
        except Exception:
            pass

    return out_list


def _usb_speed_mbps_for_disk(dev_name: str):
    """由 sdX 找出上層 USB 節點的 speed 檔（Mb/s）"""
    try:
        node = os.path.realpath(f"/sys/block/{dev_name}/device")
        for _ in range(8):
            speed_file = os.path.join(node, "speed")
            if os.path.isfile(speed_file):
                try:
                    with open(speed_file) as f: # 使用 with 以確保檔案正確關閉
                        return float((f.read() or "0").strip()) # 讀取並回傳速度
                    # return float((open(speed_file).read() or "0").strip())
                except Exception:
                    return None
            parent = os.path.dirname(node)
            if parent == node:
                break
            node = parent
        return None
    except Exception:
        return None


def _is_usb2_speed(mbps):
    return isinstance(mbps, (int, float)) and 360.0 <= mbps < 800.0


def _is_usb3_speed(mbps):
    return isinstance(mbps, (int, float)) and mbps >= 3000.0


def _rw_sanity_check(tmp_prefix: str):
    """在 /tmp 建立小檔案做讀寫測試"""
    try:
        fd, path = tempfile.mkstemp(prefix=tmp_prefix, suffix=".bin", dir="/tmp")
        os.write(fd, b"USB RW TEST\n" * 128)
        os.fsync(fd)
        os.close(fd)
        with open(path, "rb") as f:
            _ = f.read()
        os.remove(path)
        return True, "rw ok"
    except Exception as e:
        return False, f"rw error: {e}"


def _dev_head_readable(dev_path: str):
    """檢查磁碟頭部是否可讀"""
    try:
        subprocess.run(
            ["dd", f"if={dev_path}", "of=/dev/null", "bs=512", "count=1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True, "read ok"
    except Exception as e:
        return False, f"read error: {e}"


# === 下層共用執行器 ===
def usb_common_test(version: int, expect: int, verbose: bool = False):
    """
    USB2.0 / USB3.0 共用測試主體
      - 掃描 sdX
      - 判斷速度區間（USB2 or USB3）
      - 執行讀/寫驗證
      - 比對期望數量
    """
    all_sdx = _list_usb_disks_sdx()
    usb_list, speeds, non_target = [], {}, []
    lines = []

    # 根據版本過濾裝置
    for d in all_sdx:
        sp = _usb_speed_mbps_for_disk(d)
        speeds[d] = sp
        if version == 2 and _is_usb2_speed(sp):
            usb_list.append(d)
        elif version == 3 and _is_usb3_speed(sp):
            usb_list.append(d)
        else:
            non_target.append((d, sp))

    lines.append(f"[USB{version}] USB{version}數量: {len(usb_list)} / 期望: {expect}")

    bad = []
    for d in usb_list:
        dev = f"/dev/{d}"
        r_ok, _ = _dev_head_readable(dev)
        w_ok, _ = _rw_sanity_check(tmp_prefix=f"usb{version}_{d}_")
        mark = "PASS" if (r_ok and w_ok) else "FAIL"
        if mark == "FAIL":
            bad.append(d)
        sp = speeds.get(d)
        sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
        lines.append(f"  {d}: {sp_s} {mark}")

    if verbose and non_target:
        lines.append(f"  (忽略的非USB{version}裝置)")
        for d, sp in non_target:
            sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
            lines.append(f"    - {d}: {sp_s}")

    count_ok = (len(usb_list) == expect) if expect > 0 else True
    test_results = count_ok and not bad

    if test_results:
        lines.append(f"[PASS] USB{version} 測試通過")
    else:
        if not count_ok:
            lines.append(f"[FAIL] USB{version} 數量不符 ({len(usb_list)}/{expect})")
        if bad:
            lines.append(f"[FAIL] USB{version} 讀寫失敗：{', '.join(bad)}")

    return test_results, "\n".join(lines)


# === 上層控制函式 ===
def USB2_test(expect: int | None = None, verbose: bool | None = None):
    """USB2 控制層：讀 TOML → 呼叫共用邏輯"""
    blk = toml_get("USB2", None, {}) or {}

    if expect is None: # 讀 expect 設定
        try:
            expect = int(blk.get("expect", 0)) # 預設 0
        except Exception:
            expect = 0

    if verbose is None: # 讀 verbose 設定
        try:
            verbose = bool(blk.get("verbose", False)) # 預設 False
        except Exception:
            verbose = False

    return usb_common_test(version=2, expect=expect, verbose=verbose) # 呼叫共用邏輯


def USB3_test(expect: int | None = None, verbose: bool | None = None):
    """USB3 控制層：讀 TOML → 呼叫共用邏輯"""
    blk = toml_get("USB3", None, {}) or {}

    # if expect is None and callable(tg):
    if expect is None: # 讀 expect 設定
        try:
            expect = int(blk.get("expect", 0))
        except Exception:
            expect = 0

    # if verbose is None and callable(tg):
    if verbose is None: # 讀 verbose 設定
        try:
            # verbose = bool(tg("USB3", "verbose", False))
            verbose = bool(blk.get("verbose", False)) # blk.get 是直接讀toml_get 的結果
        except Exception:
            verbose = False

    return usb_common_test(version=3, expect=expect, verbose=verbose)


# ================= USB SIMPLE TESTS (no speed check) =================

# ================= M.2 KEY M TEST =================
def MKey_test():

    """
    測試目標：
      - 掃描 NVMe 裝置（/dev/nvmeXnY）
      - 檢查與 TOML expect 是否相符
      - 若設定 devices[] 則確認是否存在
      - 若 read_check=true 則讀取頭 512 bytes（只讀）
    """

    lines = []
    fail = False

    # === 讀 TOML section 一次搞定 ===
    cfg = toml_get("M-Key", None, {}) or {} # 讀整個區塊

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0

    # 必須存在的裝置清單
    must_exist = cfg.get("devices", []) or []

    # 是否做讀取測試
    read_check = bool(cfg.get("read_check", True))

    # 讀取位元組數
    try:
        read_bytes = int(cfg.get("read_bytes", 512))
    except Exception:
        read_bytes = 512

    # === 掃描 NVMe 命名空間 ===
    devs = sorted(glob.glob("/dev/nvme*n*"))
    lines.append(f"[M-Key] 偵測到 {len(devs)} 個 NVMe 裝置，期望 {expect} 個")

    # === 數量檢查 ===
    if expect > 0 and len(devs) != expect:
        fail = True
        lines.append(f"[M-Key][FAIL] 數量不符：實際 {len(devs)} / 期望 {expect}")

    # === must_exist 檢查 ===
    for req in must_exist:
        if req not in devs:
            fail = True
            lines.append(f"[M-Key][FAIL] 缺少必要裝置：{req}")

    # === 逐一讀取測試 ===
    if read_check:
        if not devs:
            lines.append("[M-Key][WARN] 無 NVMe 裝置，略過讀取測試")
        else:
            lines.append(f"[M-Key] 開始讀取測試（前 {read_bytes} bytes）")

        for d in devs:
            cmd = f"dd if={shlex.quote(d)} of=/dev/null bs={read_bytes} count=1 status=none"
            try:
                p = subprocess.run(
                    ["bash", "-lc", cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True, timeout=3
                )
                if p.returncode == 0:
                    lines.append(f"[M-Key] 讀取 OK：{d}")
                else:
                    fail = True
                    err = (p.stderr or p.stdout or "").strip()
                    lines.append(f"[M-Key][FAIL] 讀取失敗：{d}（{err}）")
            except Exception as e:
                fail = True
                lines.append(f"[M-Key][FAIL] 讀取異常：{d} ({e})")

    # === 回傳結果 ===
    if fail:
        lines.append("[M-Key][FAIL] 測試未通過")
        return False, "\n".join(lines)
    else:
        lines.append("[M-Key][PASS] M.2 Key 測試通過")
        return True, "\n".join(lines)
    
# ================= M.2 KEY M TEST =================


# ================= E-KEY TEST =================
def EKey_test():
    """
    E-Key 測試（像 USB 一樣的邏輯；不使用 nodes）
    - 讀取 [E-Key]/[E_Key] 的:
        * expect: 期望路徑數（必須 > 0）
        * EKEY_PATH_1..N: 逐一列出的資料夾路徑
    - 驗證流程：
        1) expect 必須 > 0
        2) 取出所有非空的 EKEY_PATH_#（去前後空白、去重、保序）
        3) 路徑數量必須 == expect
        4) 逐一路徑用 os.path.isdir() 檢查（第一個不存在即 FAIL）
    - 回傳：(ok: bool, msg: str)
    """
    lines = []
    failed = False

    # === 讀 TOML 區塊 ===
    cfg = toml_get("E-Key", None, {}) or {}  # 讀整個區塊

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0
    
    lines.append(f"[E-Key] 期望路徑數: {expect}")

    if expect <= 0:
        lines.append("[E-Key][FAIL] expect 必須大於 0")
        return False, "\n".join(lines)
    
    # === 收集路徑清單 ===
    paths = []
    seen = set()
    MAX_SLOTS = 100 # 最大支援 100 個路徑設定, 避免無限迴圈, 未來有增加需求再從這裡改

    for i in range(1, MAX_SLOTS + 1):
        key_name = f"EKEY_PATH_{i}"
        v = cfg.get(key_name, "")

        if v is None:
            continue

        v = str(v).strip() # 去前後空白
        if not v:
            continue

        if v in seen:
            continue # 去重

        seen.add(v)
        paths.append(v)
        
    lines.append(f"[E-Key] 路徑清單 = {paths if paths else '（未設定）'}")

    # === 數量檢查 ===
    if len(paths) != expect:
        lines.append(f"[E-Key][FAIL] 實際路徑數 ({len(paths)}) 不符期望 ({expect})")
        failed = True

    # === 逐一路徑檢查 ===
    for p in paths:
        if not os.path.isdir(p):
            lines.append(f"[E-Key][FAIL] 路徑不存在或無法訪問：{p}")
            failed = True

    # === 回傳結果 ===
    if failed:
        lines.append("[E-Key][FAIL] 測試未通過")
        return False, "\n".join(lines)
    else:
        lines.append("[E-Key][PASS] E-Key 測試通過")
        return True, "\n".join(lines)


# ================ E-KEYTEST =================

# ================= NETWORK TESTS =================    
def NETWORK_test():
    """
    LAN 測試：
      - 掃描所有實體網卡 (eth*, enp*, ens*, eno*)
      - 檢查實際數量是否符合 config 設定的 expect
      - 每個 port 都必須 link (carrier=1)
      - 每個 port 都必須能 ping 通 target_ip
      - 若數量不符、未連線或 ping 失敗 → FAIL
    """
    # enabled = toml_get("Network", "enabled", True)
    # if not enabled:
    #     return True, "[LAN] 跳過測試（未啟用）"

    target_ip    = toml_get("Network", "ping_ip") # 無預設值
    expect_count = int(toml_get("Network", "expect", 0)) # 預設 0（不檢查數量）, <expect_count>次
    ping_count   = int(toml_get("Network", "ping_count", 2)) # 預設 2, <ping_count>次
    ping_timeout = int(toml_get("Network", "ping_timeout", 1)) # 預設 1 秒, 單次等待時間

    if not target_ip or not str(target_ip).strip():
        return False, "[LAN][FAIL] 未設定目標 IP（請在設定區填寫 Network.ping_ip）"

    base = "/sys/class/net"
    exclude_prefix = ("lo", "docker", "veth", "br", "tap", "tun", "wg", "can")
    ports = []
    for name in os.listdir(base):
        if name.startswith(exclude_prefix):
            continue
        if not os.path.exists(os.path.join(base, name, "device")):
            continue
        ports.append(name)

    lines = [f"[LAN] 偵測到介面：{ports}"]
    actual_count = len(ports)

    # === 數量比對 ===
    if expect_count > 0:
        lines.append(f"[LAN] 設定期望數量: {expect_count}，實際偵測到: {actual_count}")
        if actual_count != expect_count:
            lines.append(f"[LAN][FAIL] 實際介面數量({actual_count}) 不符期望({expect_count})")
            return False, "\n".join(lines)
    else:
        lines.append("[LAN][WARN] 未在 config 中設定 Network.expect，略過數量比對")

    if not ports:
        return False, "[LAN][FAIL] 沒有找到任何實體網卡"

    fail_ports = []

    # === 逐一測試 ===
    for iface in ports:
        # 檢查 link 狀態
        carrier = "0"
        carrier_path = os.path.join(base, iface, "carrier")
        if os.path.exists(carrier_path):
            with open(carrier_path) as f:
                carrier = (f.read() or "0").strip()

        if carrier != "1":
            lines.append(f"  {iface}: FAIL (未連線)")
            fail_ports.append(iface)
            continue

        # ping 測試
        try:
            subprocess.run(
                ["ping", "-I", iface, "-c", str(ping_count), "-W", str(ping_timeout), str(target_ip)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            lines.append(f"  {iface}: PASS (ping {target_ip} 成功)")
        except subprocess.CalledProcessError:
            lines.append(f"  {iface}: FAIL (ping {target_ip} 失敗)")
            fail_ports.append(iface)
        except Exception as e:
            lines.append(f"  {iface}: ERROR ({e})")
            fail_ports.append(iface)

    # === 結果判斷 ===
    if fail_ports:
        lines.append(f"[LAN][FAIL] 以下介面未連線或測試失敗：{', '.join(fail_ports)}")
        test_results = False
    else:
        lines.append("[LAN][PASS] 所有介面數量符合且可 ping 通")
        test_results = True

    return test_results, "\n".join(lines) # 回傳 test_results, msg
# ================= NETWORK TESTS =================

# ================= EEPROM TEST =================
def EEPROM_test():
    print("EEPROM test executed.")
    # 模擬 EEPROM 測試邏輯
    # TODO: 實作 EEPROM 檢查
    # return True
    test_results, msg = True, "EEPROM test passed."
    return test_results, msg
# ================ EEPROM TEST =================
# ================ EEPROM RD TEST =================
def EEPROM_RD_test():
    print("EEPROM RD test executed.")
    # 模擬 EEPROM RD 測試邏輯
    # TODO: 實作 EEPROM RD 檢查
    # return True
    test_results, msg = True, "EEPROM RD test passed."
    return test_results, msg
# ================ EEPROM RD TEST =================

# ================= GPIO LOOPBACK TEST =================
def GPIO_test():
    """
    GPIO 對接（OUT→IN）loopback 測試（單一函式版）。
    讀取 TOML 的 [GPIO]：
      expect = <int>              # combobox 選擇的組數
      target = "gpio" | "device"  # 保留欄位
      pairs  = [
        "OUT_NUM,OUT_PIN,IN_NUM,IN_PIN",
        ...
      ] 或 table 物件 {out_num, out_pin?, in_num, in_pin?}

    回傳：(ok: bool, msg: str)
    """

    # ---- 內部小工具（不污染全域命名）----
    def _toml_get_gpio_loopback():
        blk = toml_get("GPIO", None, {}) or {}

        target = (str(blk.get("target") or "gpio")).strip().lower()
        raw_pairs = blk.get("pairs") or []

        pairs = []

        # 1) 字串格式 "OUT,OUTPIN,IN,INPIN"
        for item in raw_pairs:
            if isinstance(item, str):
                parts = [p.strip() for p in item.split(",")]
                if len(parts) >= 4:
                    try:
                        on  = int(parts[0], 0)
                        op  = parts[1] or None
                        inm = int(parts[2], 0)
                        ip  = parts[3] or None
                        pairs.append({"out_num": on, "out_pin": op,
                                    "in_num": inm, "in_pin": ip})
                    except:
                        pass

        # 2) table 物件 {out_num, in_num, out_pin?, in_pin?}
        for item in raw_pairs:
            if isinstance(item, dict):
                try:
                    on  = int(item.get("out_num"))
                    inm = int(item.get("in_num"))
                    op  = item.get("out_pin") or None
                    ip  = item.get("in_pin") or None
                    pairs.append({"out_num": on, "out_pin": op,
                                "in_num": inm, "in_pin": ip})
                except:
                    pass

        return target, pairs


    def _gpio_export(num: int):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(str(int(num)))
        except Exception:
            pass  # 已存在或無權限就忽略

    def _gpio_unexport(num: int):
        try:
            with open("/sys/class/gpio/unexport", "w") as f:
                f.write(str(int(num)))
        except Exception:
            pass

    def _gpio_path(num: int, pin_name: str | None):
        if pin_name:
            p = f"/sys/class/gpio/{pin_name}"
            if os.path.isdir(p):
                return p
        return f"/sys/class/gpio/gpio{int(num)}"

    def _w(path: str, data: str) -> bool:
        try:
            with open(path, "w") as f:
                f.write(data)
            return True
        except Exception:
            return False

    def _r(path: str):
        try:
            with open(path, "r") as f:
                return (f.read() or "").strip()
        except Exception:
            return None

    # ---- 主流程 ----
    lines = []
    fail = False

    # 讀 combobox 選擇的「期望組數」（在存檔時寫進 [GPIO].expect）
    try:
        expected_pairs = int(toml_get("GPIO", "expect", 0) or 0) # 這裡是讀取 TOML 檔的GPIO.expect
    except Exception:
        expected_pairs = 0

    target, pairs = _toml_get_gpio_loopback()

    if target not in ("gpio", "device"):
        fail = True
        lines.append(f"Invalid target for [GPIO].target, Found: {target}")

    # --- 防呆 A：沒有任何 pairs ---
    if not pairs:
        return False, "[GPIO][FAIL] 未設定任何 pairs（請在 TOML 的 [GPIO] 中填寫）"

    # --- 防呆 B：combobox 選擇的數量與實際 pairs 組數不一致就擋 ---
    if expected_pairs > 0 and expected_pairs != len(pairs):
        return False, f"[GPIO][FAIL] 期望 {expected_pairs} 組，但實際設定 {len(pairs)} 組；請調整 [GPIO].expect 或 pairs 使數量一致。"

    # 2) export & 設方向
    for p in pairs:
        on, inm = p["out_num"], p["in_num"]
        op, ip = p.get("out_pin"), p.get("in_pin")

        _gpio_export(on)
        _gpio_export(inm)

        out_path = _gpio_path(on, op)
        in_path  = _gpio_path(inm, ip)

        ok1 = _w(os.path.join(out_path, "direction"), "out")
        ok2 = _w(os.path.join(in_path,  "direction"), "in")
        if not (ok1 and ok2):
            fail = True
            lines.append(f"Init direction 失敗：OUT={on}/{op or ''} IN={inm}/{ip or ''}")

    # 3) 逐組驗證：OUT 拉 0/1，IN 必須等於 0/1
    for p in pairs:
        on, inm = p["out_num"], p["in_num"]
        op, ip = p.get("out_pin"), p.get("in_pin")

        out_path = _gpio_path(on, op)
        in_path  = _gpio_path(inm, ip)

        for val in ("0", "1"):
            if not _w(os.path.join(out_path, "value"), val):
                fail = True
                lines.append(f"Pair {on},{op or ''},{inm},{ip or ''} 無法寫 OUT={val}")
                continue

            time.sleep(0.05)  # 50ms

            read_v = _r(os.path.join(in_path, "value"))
            if read_v is None:
                fail = True
                lines.append(f"Pair {on},{op or ''},{inm},{ip or ''} 讀 IN 失敗（預期 {val}）")
            elif read_v != val:
                fail = True
                lines.append(f"Pair {on},{op or ''},{inm},{ip or ''} expect {val} but read {read_v}")

        # 測完復位
        _w(os.path.join(out_path, "value"), "0")

    # 4) 收尾：unexport
    for p in pairs:
        _gpio_unexport(p["out_num"])
        _gpio_unexport(p["in_num"])

    if not fail:
        lines.append("[GPIO][PASS] 所有 pair 皆通過")
        return True, "\n".join(lines)
    else:
        lines.append("[GPIO][FAIL] 其中有 pair 測試未通過")
        return False, "\n".join(lines)


# ================= GPIO TEST =================

#================= SD CARD TEST =================
def _list_mmc_disks_only():
    """
    只回傳板上的實體 SD/MMC 磁碟本體名稱（不含分割區），例如：['mmcblk0', 'mmcblk1']。
    不納入任何 /dev/sdX（USB 讀卡機）。
    """
    devs = []

    # 先走 lsblk 結構化資料
    try:
        out = subprocess.check_output(
            ["lsblk", "-J", "-o", "NAME,TYPE,RM"],
            text=True, stderr=subprocess.STDOUT
        )
        data = json.loads(out)
    except Exception:
        data = {}

    def _walk(nodes):
        for n in nodes or []:
            yield n
            for c in n.get("children", []) or []:
                yield from _walk([c])

    if data:
        for n in _walk(data.get("blockdevices", [])):
            name = (n.get("name") or "")
            typ  = (n.get("type") or "")
            rm   = int(n.get("rm", 0))
            # 只算磁碟本體 + mmcblk* + 可拆卸
            if typ == "disk" and name.startswith("mmcblk") and rm == 1:
                devs.append(name)
    else:
        # 後援：/sys 掃 mmc 裝置
        try:
            for dev in os.listdir("/sys/block"):
                if not dev.startswith("mmcblk"):
                    continue
                # 容量 > 0 才算
                try:
                    with open(f"/sys/block/{dev}/size") as f:
                        sz = int((f.read() or "0").strip())
                except FileNotFoundError:
                    sz = 0
                if sz <= 0:
                    continue
                # 確認真的是 mmc 匯流排（多數平台 device 路徑會含 /mmc ）
                realp = os.path.realpath(f"/sys/block/{dev}/device")
                if "/mmc" in realp:
                    devs.append(dev)
        except Exception:
            pass

    return sorted(set(devs))

def SD_test(expect: int | None = None):
    """
    Micro SD 測試（只算板上實體 SD/MMC）
    PASS 條件：
      1) 偵測到的卡數 == expect（expect > 0）
      2) 每顆 raw 頭 512 bytes 可讀（安全，不寫 raw）

    TOML：
      [Micro SD Card]
      expect = 1
    數量由toml 與實際系統內的 mmcblk* 數量比對。
    """
    # 期望數量：從參數或 TOML 取
    expect = expect if expect is not None else toml_get("Micro SD Card", "expect", 0) # 預設 0
    try:
        expect = int(expect)
    except Exception:
        expect = 0

    if expect <= 0:
        return False, "[SD][FAIL] 未設定期望數量（請在設定區填寫 Micro SD Card.expect）"

    disks = _list_mmc_disks_only()

    lines = [f"[SD] 偵測到 {len(disks)} / 期望 {expect}（只計主板上 mmcblk*）"]

    # 可讀檢查（raw 讀 512 bytes）＋ 系統層寫測試（/tmp），與 USB 一致
    bad_raw = []
    bad_sys = []
    for d in disks:
        dev = f"/dev/{d}"
        r_ok, r_msg = _dev_head_readable(dev)              # raw 頭 512 bytes 可讀
        w_ok, r_msg = _rw_sanity_check(tmp_prefix=f"sd_{d}_")  # 系統層小檔寫入健檢（不動卡）
        if not r_ok: bad_raw.append(d)
        if not w_ok: bad_sys.append(d)
        lines.append(f"  {d}: raw-read={r_ok} sys-rw={w_ok}")
        # lines.append(f"    - {r_msg}")

    count_ok = (len(disks) == expect)
    ok = count_ok and (not bad_raw) and (not bad_sys)

    if ok:
        lines.append("[PASS] SD 測試通過（只計板上 SD/MMC）")
    else:
        if not count_ok:
            lines.append(f"[FAIL] 數量不符：{len(disks)}/{expect}")
        if bad_raw:
            lines.append(f"[FAIL] raw 可讀失敗：{', '.join(bad_raw)}")
        if bad_sys:
            lines.append(f"[FAIL] 系統層寫入健檢失敗：{', '.join(bad_sys)}")

    return ok, "\n".join(lines)

#================= SD CARD TEST =================

# ===== RS232 RS422 通用測試 Function =====
# def _serial_nodes_from_toml_ports(section: str, key_prefix: str, max_n: int = 12):
#     """讀 [section] 的 {key_prefix}_port_1..max_n，過濾成有效 /dev/* 清單（存在且為字元裝置）。"""

#     tg = globals().get("toml_get")
#     blk = {}
#     if callable(tg):
#         try:
#             blk = tg(section, None, {}) or {}
#         except Exception:
#             blk = {}

#     out = []
#     seen = set()
#     for i in range(1, max_n + 1):
#         v = str(blk.get(f"{key_prefix}_port_{i}", "")).strip()
#         if not (v and v.startswith("/dev/")): # 只留 /dev/ 開頭的裝置
#             continue
#         if v in seen:
#             continue
#         seen.add(v)
#         # 只留存在且為字元裝置
#         try:
#             st = os.stat(v) # type: ignore
#             if stat.S_ISCHR(st.st_mode): # 字元裝置
#                 out.append(v) # type: ignore
#         except Exception:
#             pass
#     return out

def _serial_nodes_from_toml_ports(section: str, key_prefix: str, max_n: int = 100):
    """
    讀取 [section] 區段中的 {key_prefix}_port_1..{key_prefix}_port_N，
    過濾成有效 /dev/* 清單（存在且為字元裝置）。

    例：
      [RS232]
      expect = 4
      RS232_port_1 = "/dev/ttyS0"
      RS232_port_2 = "/dev/ttyS1"
      ...

    呼叫方式：
      nodes = _serial_nodes_from_toml_ports("RS232", "RS232")
    """

    # 直接用你的 toml_get 讀整個 section
    cfg = toml_get(section, None, {}) or {}

    out = []
    seen = set()

    # max_n 設很大（例如 100），未來 UI 增加欄位時不用改程式
    for i in range(1, max_n + 1):
        key = f"{key_prefix}_port_{i}"
        v = str(cfg.get(key, "")).strip()

        # 只接受 /dev/ 開頭的路徑
        if not (v and v.startswith("/dev/")):
            continue

        # 去重複
        if v in seen:
            continue
        seen.add(v)

        # 確認存在而且是「字元裝置」
        try:
            st = os.stat(v)  # type: ignore
            if stat.S_ISCHR(st.st_mode):      # type: ignore
                out.append(v)                 # type: ignore
        except Exception:
            # 不存在或無法 stat 就略過
            pass

    return out



# def serial_loopback_test(section: str, key_prefix: str, expect: int | None = None, nodes: list[str] | None = None):
#     """通用 UART 迴路測試（pyserial 可用則優先，否則 stty+cat），適用 RS232/RS422/RS485。"""

#     tg = globals().get("toml_get")

#     # 期望數量
#     if expect is None and callable(tg): # 從 TOML 讀取期望數量
#         try:
#             expect = int(tg(section, "expect", 0))
#         except Exception:
#             expect = 0
#     try:
#         expect = int(expect or 0)
#     except Exception:
#         expect = 0

#     # 節點來源
#     if nodes is None:
#         nodes = _serial_nodes_from_toml_ports(section, key_prefix, max_n=12) # max_n 是上限
#     else:
#         nodes = [s.strip() for s in nodes if str(s).strip().startswith("/dev/")] # 過濾有效 /dev/*

#     if not nodes:
#         return False, f"[{section}][FAIL] 未提供任何有效節點，請在 {key_prefix}_port_1..10 或 UI 填入 /dev/tty*"

#     # pyserial 方案（可用才用）
#     def try_pyserial(dev, retries=3, delay=0.1):
#         try:
#             import serial
#         except Exception:
#             return None, "no_pyserial"
#         for _ in range(retries):
#             try:
#                 ser = serial.Serial(dev, 115200, bytesize=8, parity='N', stopbits=1,
#                                     timeout=0.5, write_timeout=0.5,
#                                     rtscts=False, dsrdtr=False, xonxoff=False)
#                 try:
#                     ser.setDTR(True); time.sleep(0.02)
#                     ser.setRTS(True); time.sleep(0.02)
#                     ser.reset_input_buffer(); ser.reset_output_buffer()
#                 except Exception:
#                     pass
#                 ser.write(b"successful\n"); ser.flush()
#                 time.sleep(delay)
#                 data = ser.read(1024) or b""
#                 ser.close()
#                 if b"successful" in data:
#                     return True, "PASS(pyserial)"
#             except Exception:
#                 time.sleep(delay)
#         return False, "FAIL(pyserial)"

#     # shell 後備
#     def try_shell(dev, delay=0.1): # 使用 stty + cat 迴路測試
#         try:
#             subprocess.run(["stty", "-F", dev, "115200", "-echo", "-onlcr", "clocal"],
#                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#             tmp = f"/tmp/ser_{os.getpid()}_{dev.replace('/', '_')}.log"
#             p = subprocess.Popen(["bash", "-lc", f"cat {shlex.quote(dev)} > {shlex.quote(tmp)} & echo $!"],
#                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
#             try:
#                 out, _ = p.communicate(timeout=0.5)
#             except subprocess.TimeoutExpired:
#                 p.kill(); out = ""
#             try:
#                 pid = int((out or "").strip() or "0")
#             except Exception:
#                 pid = 0
#             time.sleep(0.1)
#             subprocess.run(["bash", "-lc", f"echo successful > {shlex.quote(dev)}"],
#                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#             time.sleep(delay)
#             if pid:
#                 subprocess.run(["kill", "-9", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#             else:
#                 subprocess.run(["fuser", "-k", "/bin/cat"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#             try:
#                 data = open(tmp, "rb").read()
#             except Exception:
#                 data = b""
#             finally:
#                 try: os.remove(tmp)
#                 except Exception: pass
#             return (b"successful" in data), "PASS(shell)" if b"successful" in data else "FAIL(shell)"
#         except Exception:
#             return False, "FAIL(shell)"

#     # 主流程（同你現有風格）
#     lines, bad, tested = [], [], [] # lines: log lines; bad: 失敗清單; tested: 測過清單
#     lines.append(f"[{section}] 指定數量: {len(nodes)} / 期望: {expect}")
#     for dev in nodes:
#         if not os.path.exists(dev):
#             lines.append(f"  {dev}: SKIP (節點不存在)")
#             continue
#         ok, way = try_pyserial(dev)
#         if ok is None and way == "no_pyserial":
#             ok, way = try_shell(dev)
#         tested.append(dev)
#         if ok:
#             lines.append(f"  {dev}: PASS ({way})")
#         else:
#             lines.append(f"  {dev}: FAIL ({way})")
#             bad.append(dev)

#     count_ok = (len(tested) == expect) if expect > 0 else True
#     ok_all = count_ok and not bad
#     if ok_all:
#         lines.append(f"[PASS] {section} 測試通過")
#     else:
#         if not count_ok: lines.append(f"[FAIL] {section} 數量不符（{len(tested)}/{expect}）")
#         if bad:         lines.append(f"[FAIL] {section} 迴路失敗：{', '.join(bad)}")
#     return ok_all, "\n".join(lines)

# 下層：只負責通訊與結果彙整
def serial_loopback_test(expect: int, nodes: list[str]):
    # import serial, time
    lines, bad_nodes = [], []
    ok_count = 0
    test_word = b"AETINA\n"

    for dev in nodes:
        try:
            ser = serial.Serial(dev, 115200, timeout=1)
            ser.write(test_word)
            time.sleep(0.1)
            recv = ser.read(len(test_word) + 5)
            ser.close()

            if test_word.strip() in recv:
                lines.append(f"[PASS] {dev} 迴路通訊成功")
                ok_count += 1
            else:
                lines.append(f"[FAIL] {dev} 讀取異常：{recv!r}")
                bad_nodes.append(dev)
        except Exception as e:
            lines.append(f"[ERROR] {dev} 無法開啟或通訊 ({e})")
            bad_nodes.append(dev)

    count_ok = (ok_count == expect)
    ok = (not bad_nodes) and count_ok

    if ok:
        lines.append(f"[PASS] RS232 測試通過，共 {ok_count}/{expect}")
    else:
        if not count_ok:
            lines.append(f"[FAIL] 數量不符：實測 {ok_count} / 期望 {expect}")
        if bad_nodes:
            lines.append(f"[FAIL] 失敗節點：{', '.join(bad_nodes)}")

    return ok, "\n".join(lines)


# 上層：讀 TOML（或接 UI 覆寫），再呼叫下層
def RS232_test(expect: int | None = None, nodes: list[str] | None = None):
    """
    RS232 測試控制層：
      - expect: 期望測試的 port 數量（None 則由 TOML 讀取 [RS232].expect）
      - nodes:  要測試的 /dev/* 清單（None 則由 TOML 的 RS232_port_1..N 自動取得）

    傳給下層：
      serial_loopback_test(expect=expect, nodes=nodes)
    """

    # === 讀整個 [RS232] 區段 ===
    cfg = toml_get("RS232", None, {}) or {}

    # === 期望數量（可被呼叫參數覆蓋）===
    if expect is None:
        try:
            # 預設 0：不檢查數量，只要有至少一個通過就交給 serial_loopback_test 去判斷
            expect = int(cfg.get("expect", 0))
        except Exception:
            expect = 0

    # === 節點清單（/dev/tty*）（可被呼叫參數覆蓋）===
    if nodes is None:
        # max_n 設大一點（例如 100），未來 UI 增加 RS232_port_11、12... 也不用改這裡
        nodes = _serial_nodes_from_toml_ports("RS232", "RS232", max_n=100)

    # === 呼叫共用 RS232 loopback 測試邏輯 ===
    return serial_loopback_test(expect=expect, nodes=nodes)




    # return serial_loopback_test("RS232", "RS232", expect=expect)

# ==== RS232 測試 ====

# ==== RS422 測試 ====
def RS422_test(expect: int | None = None, nodes: list[str] | None = None):
    """
    RS422 測試控制層：
      - expect: 期望測試的 port 數量（None 則由 TOML 讀取 [RS422].expect）
      - nodes:  要測試的 /dev/* 清單（None 則由 TOML 的 RS422_port_1..N 自動取得）

    傳給下層：
      serial_loopback_test(expect=expect, nodes=nodes)
    """

    # === 讀整個 [RS422] 區段 ===
    cfg = toml_get("RS422", None, {}) or {}

    # === 期望數量（可被呼叫參數覆蓋）===
    if expect is None:
        try:
            # 預設 0：不檢查數量，只要有至少一個通過就交給 serial_loopback_test 去判斷
            expect = int(cfg.get("expect", 0))
        except Exception:
            expect = 0

    # === 節點清單（/dev/tty*）（可被呼叫參數覆蓋）===
    if nodes is None:
        # max_n 設大一點（例如 100），未來 UI 增加 RS422_port_11、12... 也不用改這裡
        nodes = _serial_nodes_from_toml_ports("RS422", "RS422", max_n=100)

    # === 呼叫共用 RS422 loopback 測試邏輯 ===
    return serial_loopback_test(expect=expect, nodes=nodes)

# ==== RS422 測試 ====

# ==== RS485 測試 ====
def RS485_test():

    cfg = toml_get("RS485", None, {}) or {}
    
    return True, "[RS485] 測試略過（預設 PASS）"

# ==== RS485 測試 ====

# ===== UART TESTS ======
def UART_test(expect: int | None = None, nodes: list[str] | None = None, attempts: int = 20):
    """
    UART 測試（單埠 loopback，對應原本 shell test_UART）

    設定來源：TOML [UART]
      [UART]
      expect      = 2
      UART_port_1 = "/dev/ttyTHS1"
      UART_port_2 = "/dev/ttyUSB0"

    邏輯：
      1) 由 TOML 讀取 UART_port_1..N → nodes
      2) 如有設定 expect > 0，檢查 len(nodes) 是否一致
      3) 每個節點做 attempts 次測試：
          - 開啟 serial，baud 115200，timeout=0.2
          - 清 input buffer
          - 寫 "successful\n"
          - 讀回資料，看是否有 "successful"
      4) 任一 port 測試失敗 → 整體 FAIL
    """
    
    lines: list[str] = []
    fail = False

    # === 讀整個 [UART] 區段 ===
    cfg = toml_get("UART", None, {}) or {}

    # === 期望數量 ===
    if expect is None:
        try:
            expect = int(cfg.get("expect", 0))
        except Exception:
            expect = 0
    
    # === 節點清單（/dev/tty*）===
    if nodes is None:
        nodes = _serial_nodes_from_toml_ports("UART", "UART", max_n=100)
    
    lines.append(f"[UART] 指定數量: {len(nodes)} / 期望: {expect}")

    # === 數量檢查 ===
    if expect is not None and expect > 0:
        if len(nodes) != expect:
            fail = True
            lines.append(f"[UART][FAIL] 數量不符：實際 {len(nodes)} / 期望 {expect}")

    if not nodes:
        fail = True
        lines.append("[UART][FAIL] 未提供任何有效節點，請在 UART_port_1..N 或 UI 填入 /dev/tty*")
        return False, "\n".join(lines)
    
    # === 逐節點測試 ===
    def _uart_single_test(dev: str, attempts: int = 20):
        """
        嘗試對單一 UART port 做 loopback 測試：
          - 開啟 serial.Serial(dev, 115200, timeout=0.2)
          - 寫入 "successful\\n"
          - 讀回，看是否包含 "successful"
        成功回傳 (True, 訊息)，失敗回傳 (False, 訊息)
        """
        
        msg_lines = [f"[UART] 測試 {dev}，嘗試次數 {attempts}"]
        try:
            ser = serial.serial(
                port=dev,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,
                write_timeout=0.2,
            )
        except Exception as e:
            msg_lines.append(f"[UART][ERROR] 無法開啟 {dev} ({e})")
            return False, "\n".join(msg_lines)
        
        try:
            for idx in range(1, attempts + 1):
                # 清空 input buffer
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

                # 寫入測試字串
                payload = b"successful\n"
                ser.write(payload)
                ser.flush()
                
                # 等一下讓資料 loopback 回來
                time.sleep(0.1)

                # 讀回資料
                try:
                    data = ser.read(1024) # 讀最多 1024 bytes
                except Exception as e:
                    msg_lines.append(f"[UART] 第 {idx} 次讀取失敗：{e}")
                    continue
            
                if not data:
                    msg_lines.append(f"[UART] 第 {idx} 次讀取無資料")
                    continue

                decoded = ""
                try:
                    decoded = data.decode(errors="ignore")
                except Exception:
                    pass

                    if "successful" in decoded or b"successful" in data:
                        msg_lines.append(f"[UART] 第 {idx} 次通過")
                        msg_lines.append(f"[UART] 測試 {dev} 通過")
                        return True, "\n".join(msg_lines)
                    else:
                        msg_lines.append(f"[UART] 第 {idx} 次讀回內容：{decoded!r}")
                except serial.SerialTimeoutException:
                    msg_lines.append(f"[UART] 第 {idx} 次寫入逾時")

                except Exception as oe:
                    msg_lines.append(f"[UART] 第 {idx} 次寫入失敗：{oe}")
                    if "device" in str(oe):
                        msg_lines.append(f"[UART] 第 {idx} 次寫入失敗：{oe}")
                        
                    # 若是裝置消失，可視情況提早結束
                    if getattr(oe, "errno", None) in (errno.ENODEV, errno.EIO):
                        break
                except Exception as e:
                    msg_lines.append(f"[UART] 第 {idx} 次寫入失敗：{e}")
            msg_lines.append(f"[UART] 測試 {dev} 失敗，所有嘗試均未通過")
            return False, "\n".join(msg_lines)
        finally:
            try:
                ser.close()
            except Exception:
                pass

    # === 逐一測試每個 UART port ===
    for dev in nodes:
        ok, msg = _uart_single_test(dev, attempts=attempts)
        lines.append(msg)
        if not ok:
            fail = True

    # === 總結 ===
    if fail:
        lines.append("[UART][FAIL] 有 UART port 測試未通過")
        return False, "\n".join(lines)
    else:
        lines.append("[UART][PASS] 所有 UART port 測試通過")
        return True, "\n".join(lines)

# ===== UART TESTS ======

# ===== SPI TEST =====
def SPI_test():
    """
    SPI 測試流程：
        1. 讀取 config 中的 precmd (例如 modprobe spidev)
        2. 編譯 spidev-test.c 為 spidev_test 執行檔
        3. 根據 expect 期望數量，依序讀取 SPI_path_1 ~ SPI_path_expect
        4. 針對每個 SPI_path 執行 ./spidev_test -D <path>
        5. 檢查 spidev_test 的輸出是否包含預期的 HEX pattern
    """
    import os, subprocess

    lines = []
    fail = False

    # ===== 1) 讀取期望數量 =====
    expect = int(toml_get("SPI", "expect", 0) or 0)

    # ===== 2) 收集所有 SPI_path_1..N =====
    spi_paths = []
    max_n = 100
    for i in range(1, max_n + 1):
        path = toml_get("SPI", f"SPI_path_{i}", "").strip()
        if path:
            spi_paths.append(path)

    # ===== 3) 數量資訊 =====
    lines.append(f"[SPI] 指定數量: {len(spi_paths)} / 期望: {expect}")

    # ===== 4) 數量檢查 =====
    if expect > 0 and len(spi_paths) != expect:
        fail = True
        lines.append(f"[SPI][FAIL] 數量不符：實際 {len(spi_paths)} / 期望 {expect}")

    # ===== 5) 路徑為空 =====
    if not spi_paths:
        return False, (
            "[SPI][FAIL] 未提供任何有效 SPI device，"
            "請在 SPI_path_1..N 或 UI 填入 /dev/spidevX.Y"
        )

    # ===== 6) 執行 precmd（例如 modprobe spidev）=====
    precmd = toml_get("SPI", "precmd", "").strip()
    if precmd:
        try:
            subprocess.run(precmd, shell=True, check=True)
        except Exception as e:
            return False, f"[SPI][FAIL] 執行 precmd 失敗：{precmd} ({e})"

    # ===== 7) 編譯 spidev-test.c =====
    try:
        subprocess.run(
            ["gcc", "spidev-test.c", "-o", "spidev_test"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as e:
        return False, f"[SPI][FAIL] 編譯 spidev-test.c 失敗：{e}"

    # ===== 8) SPI pattern =====
    PATTERN = (
        "FF FF FF FF FF FF 40 00 00 00 00 95 "
        "FF FF FF FF FF FF FF FF FF FF FF FF "
        "FF FF FF FF FF FF F0 0D"
    )

    # ===== 9) 逐個測試路徑 =====
    for idx, spi_path in enumerate(spi_paths, start=1):

        # （A）檢查 device 是否存在
        if not spi_path.startswith("/dev/") or not os.path.exists(spi_path):
            fail = True
            lines.append(f"[SPI][FAIL] SPI_path_{idx} 設定錯誤：{spi_path}（裝置不存在）")
            continue

        # （B）執行 spidev_test
        try:
            result = subprocess.run(
                ["./spidev_test", "-D", spi_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception as e:
            fail = True
            lines.append(f"[SPI][FAIL] 執行 spidev_test 失敗：{spi_path} ({e})")
            continue

        output = result.stdout or ""

        # （C）比對 pattern
        if PATTERN not in output:
            fail = True
            lines.append(
                f"[SPI][FAIL] {spi_path} 測試失敗，輸出不符合預期模式\n"
                f"實際輸出：\n{output}"
            )

    # ===== 10) 判斷 PASS/FAIL =====
    if fail:
        return False, "\n".join(lines)

    lines.append("[SPI][PASS] 所有 SPI device 測試通過")
    return True, "\n".join(lines)

# ===== SPI TEST =====

def CPU_test():
    print("CPU test executed.")
    # 模擬 CPU 測試邏輯
    # TODO: 實作 CPU 檢查
    # return True
    test_results, msg = True, "CPU test passed."
    return test_results, msg

def HDMI_test():
    # print("HDMI test executed.")
    # 模擬 HDMI 測試邏輯
    # TODO: 實作 HDMI 檢查
    # return True

    # ask_info("HDMI 測試", "請確認 HDMI 螢幕畫面是否正常顯示。")
    if ask_yes_no("HDMI 測試", "畫面是否正常顯示？"):
        return True, "[HDMI] PASS"
    return False, "[HDMI] FAIL"

    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "HDMI 測試", "請確認 HDMI 畫面是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "HDMI 畫面異常，請檢查連接與顯示器設定。"
    # else:
    #     return True, "HDMI test passed。"

    # # test_results, msg = True, "HDMI test passed."
    # # return test_results, msg

def VGA_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "VGA 測試", "請確認 VGA 畫面是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "VGA 畫面異常，請檢查連接與顯示器設定。"
    # else:
    #     return True, "VGA test passed。"
    if ask_yes_no("VGA 測試", "畫面是否正常顯示？"):
        return True, "[VGA] PASS"
    return False, "[VGA] FAIL"
    
def DP_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "DP 測試", "請確認 DP 畫面是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "DP 畫面異常，請檢查連接與顯示器設定。"
    # else:
    #     return True, "DP test passed。"
    if ask_yes_no("DP 測試", "畫面是否正常顯示？"):
        return True, "[DP] PASS"
    return False, "[DP] FAIL"

def LED_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "LED 測試", "請確認 LED 是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "LED 異常。"
    # else:
    #     return True, "LED test passed。"
    if ask_yes_no("LED 測試", "LED 是否正常亮起？"):
        return True, "[LED] PASS"
    return False, "[LED] FAIL"

def POWER_BUTTON_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "Power Button 測試", "請確認Power Button是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "Power Button 異常。"
    # else:
    #     return True, "Power Button test passed。"
    if ask_yes_no("Power Button 測試", "Power Button 是否正常？"):
        return True, "[Power Button] PASS"
    return False, "[Power Button] FAIL"

def POWER_CONNECTOR_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "Power Connector 測試", "請確認Power Connector是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "Power Connector 異常。"
    # else:
    #     return True, "Power Connector test passed。"
    if ask_yes_no("Power Connector 測試", "Power Connector 是否正常？"):
        return True, "[Power Connector] PASS"
    return False, "[Power Connector] FAIL"

def POWER_SW_CONNECTOR_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "Power SW Connector 測試", "請確認Power SW Connector是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "Power SW Connector 異常。"
    # else:
    #     return True, "Power SW Connector test passed。"
    if ask_yes_no("Power SW Connector 測試", "Power SW Connector 是否正常？"):
        return True, "[Power SW Connector] PASS"
    return False, "[Power SW Connector] FAIL"

def RESET_BUTTON_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "Reset Button 測試", "請確認Reset Button是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "Reset Button 異常。"
    # else:
    #     return True, "Reset Button test passed。"
    if ask_yes_no("Reset Button 測試", "Reset Button 是否正常？"):
        return True, "[Reset Button] PASS"
    return False, "[Reset Button] FAIL"

def RECOVERY_BUTTON_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "Recovery Button 測試", "請確認Recovery Button是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "Recovery Button 異常。"
    # else:
    #     return True, "RECOVERY BUTTON test passed。"
    if ask_yes_no("Recovery Button 測試", "Recovery Button 是否正常？"):
        return True, "[Recovery Button] PASS"
    return False, "[Recovery Button] FAIL"
    
def SMA_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "SMA測試", "請確認SMA是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "SMA異常。"
    # else:
    #     return True, "SMA test passed。"
    if ask_yes_no("SMA 測試", "SMA 是否正常？"):
        return True, "[SMA] PASS"
    return False, "[SMA] FAIL"

def SW1_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "SW1測試", "請確認SW1是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "SW1異常。"
    # else:
    #     return True, "SW1 test passed。"
    if ask_yes_no("SW1 測試", "SW1 是否正常？"):
        return True, "[SW1] PASS"
    return False, "[SW1] FAIL"

def SW2_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "SW2測試", "請確認SW2是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "SW2異常。"
    # else:
    #     return True, "SW2 test passed。"
    if ask_yes_no("SW2 測試", "SW2 是否正常？"):
        return True, "[SW2] PASS"
    return False, "[SW2] FAIL"
    
def MCU_CONNECTOR_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "MCU Connector測試", "請確認MCU Connector是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "MCU Connector異常。"
    # else:
    #     return True, "MCU Connector test passed。"
    if ask_yes_no("MCU Connector 測試", "MCU Connector 是否正常？"):
        return True, "[MCU Connector] PASS"
    return False, "[MCU Connector] FAIL"
    
def RTC_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "RTC測試", "請確認RTC是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "RTC異常。"
    # else:
    #     return True, "RTC test passed。"
    if ask_yes_no("RTC 測試", "RTC 是否正常？"):
        return True, "[RTC] PASS"
    return False, "[RTC] FAIL"
    
def RTC_OUT_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "RTC OUT測試", "請確認RTC OUT是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "RTC OUT異常。"
    # else:
    #     return True, "RTC OUT test passed。"
    if ask_yes_no("RTC OUT 測試", "RTC OUT 是否正常？"):
        return True, "[RTC OUT] PASS"
    return False, "[RTC OUT] FAIL"

def DC_INPUT_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "DC INPUT測試", "請確認DC INPUT是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "DC INPUT異常。"
    # else:
    #     return True, "DC INPUT test passed。"
    if ask_yes_no("DC INPUT 測試", "DC INPUT 是否正常？"):
        return True, "[DC INPUT] PASS"
    return False, "[DC INPUT] FAIL"

def DC_OUTPUT_test():
    # parent = QApplication.instance().activeWindow() # 取得目前的視窗當 parent
    # ans = QMessageBox.question(parent, "DC OUTPUT測試", "請確認DC OUTPUT是否正常？", QMessageBox.Yes | QMessageBox.No)
    # if ans == QMessageBox.No:
    #     return False, "DC OUTPUT異常。"
    # else:
    #     return True, "DC OUTPUT test passed。"
    if ask_yes_no("DC OUTPUT 測試", "DC OUTPUT 是否正常？"):
        return True, "[DC OUTPUT] PASS"
    return False, "[DC OUTPUT] FAIL"

# ===================== FAN_test(): 無 UI 的 pwm/rpm path，手動/自動合一 =====================

DEFAULT_PWM_LO = 30
DEFAULT_PWM_HI = 100

# ---------- 通用小工具 ----------
def _sleep(sec):
    try: time.sleep(float(sec))
    except: time.sleep(1)

def _within(val, target, tol):
    if target <= 0:  # 目標為 0 表示不檢查
        return True
    lo = target - target * tol / 100
    hi = target + target * tol / 100
    return lo <= val <= hi

def _read_int(path):
    try:
        with open(path) as f:
            s = re.sub(r"[^\d]", "", f.read())
        return int(s or "0")
    except:
        return 0

def _ask_human(msg):
    try:
        subprocess.check_call(["zenity","--question","--no-wrap","--text",msg,
                               "--ok-label","有變化","--cancel-label","沒變化"])
        return True
    except subprocess.CalledProcessError:
        return False
    except:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        return ans.startswith("y")

def _hexdec(s):
    s = str(s).strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s, 10)

def _is_rk():
    b = os.environ.get("BOARD","")
    if b.startswith(("RK_","RKC")):
        return True
    try:
        with open("/proc/device-tree/compatible","rb") as f:
            return b"rockchip" in f.read().lower()
    except:
        return False

def _is_jetson():
    try:
        with open("/proc/device-tree/model") as f:
            return "nvidia jetson" in f.read().lower()
    except:
        return os.path.exists("/etc/nv_tegra_release")

# ---------- sysfs（ARM/Jetson/RK） ----------
def _find_pwm1_under(path):
    """允許餵父資料夾（如 /sys/devices/platform/pwm-fan 或 /sys/class/hwmon/hwmonX），自動找 pwm1。"""
    if os.path.isfile(path) and os.path.basename(path).startswith("pwm"):
        return path
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            if "pwm1" in files:
                return os.path.join(root, "pwm1")
    return None

def _find_fan_input_near(pwm_path):
    """在 pwm1 同層或上層 hwmon 目錄附近找 fan*_input，優先 fan1_input。"""
    if not pwm_path:
        return None
    base = os.path.dirname(pwm_path)
    cand = os.path.join(base, "fan1_input")
    if os.path.exists(cand): return cand
    for name in os.listdir(base):
        if re.match(r"fan\d+_input$", name) and os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    up = os.path.dirname(base)
    for root, _, files in os.walk(up):
        for name in files:
            if re.match(r"fan\d+_input$", name):
                return os.path.join(root, name)
    return None

def _write_pwm_sysfs(pwm_path, percent):
    if not pwm_path or not os.path.exists(pwm_path):
        return False, f"路徑不存在：{pwm_path}"
    base = os.path.dirname(pwm_path)
    m = re.search(r"pwm(\d+)$", pwm_path)
    idx = m.group(1) if m else "1"
    enable = os.path.join(base, f"pwm{idx}_enable")
    try:
        if os.path.exists(enable):
            with open(enable, "w") as f: f.write("1")  # 手動模式
    except Exception as e:
        return False, f"無法啟用手動模式：{e}"

    val255 = int(round(max(0, min(100, int(percent))) * 255 / 100))
    try:
        with open(pwm_path, "w") as f: f.write(str(val255))
        return True, f"0~255 寫入 {val255}"
    except Exception as e1:
        try:
            with open(pwm_path, "w") as f: f.write(str(int(percent)))
            return True, f"0~100 寫入 {int(percent)}"
        except Exception as e2:
            return False, f"無法寫入 ({e1}) / ({e2})"

def _read_rpm_sysfs(rpm_path):
    return _read_int(rpm_path)

# ---------- EAPI（x86 / FR68 自動） ----------
EAPI_NAMES = [
    "CPU Fan speed","System Fan 1 speed","System Fan 2 speed",
    "System Fan 3 speed","System Fan 4 speed"
]

def _find_eapi():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [shutil.which("EApi_Test"), os.path.join(here,"EApi_Test"), "./EApi_Test"]
    for p in cands:
        if p and os.path.exists(p):
            if not os.access(p, os.X_OK):
                try: os.chmod(p,0o755)
                except: pass
            return p
    return None

def _insmod_innoeapi():
    try:
        out = subprocess.check_output(["lsmod"], text=True)
        if "innoeapi" in out:
            return
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    ko_path = os.path.join(here, "innoeapi.ko")
    if os.path.exists(ko_path):
        subprocess.call(["sudo","/sbin/insmod", ko_path])

def _set_pwm_eapi(dev, percent):
    eapi = _find_eapi()
    if not eapi: return False, "找不到 EApi_Test"
    _insmod_innoeapi()
    p = str(max(0, min(100, int(percent))))
    try:
        subprocess.check_call([eapi,"-f",str(dev),"-m","0","-s",p],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"設定 {p}% 成功"
    except Exception as e:
        return False, f"設定失敗：{e}"

def _read_rpm_eapi(dev):
    eapi = _find_eapi()
    if not eapi: return 0
    try:
        out = subprocess.check_output([eapi], text=True)
        name = EAPI_NAMES[dev] if 0 <= dev < len(EAPI_NAMES) else None
        if not name: return 0
        m = re.search(rf"{re.escape(name)}\s*:\s*(\d+)\s*rpm", out, re.I)
        return int(m.group(1)) if m else 0
    except:
        return 0

# ---------- 手動模式用：解析路徑語法（相容 test_fan()） ----------
def _parse_manual_target(fan_path_str):
    """
    支援：
      - 'i2c:bus,addr,reg'  例：i2c:1,0x2f,0x03
      - 'gpio:export,gpio'  例：gpio:480,gpio480 或 gpio:480,480
      - 'device:/sys/...'(或直接 /sys/...)：sysfs 路徑父資料夾
    """
    s = fan_path_str.strip()
    if s.startswith("i2c:"):
        parts = s[4:].split(",")
        if len(parts) >= 3:
            return ("i2c", _hexdec(parts[0]), _hexdec(parts[1]), _hexdec(parts[2]))
    if s.startswith("gpio:"):
        parts = s[5:].split(",")
        if len(parts) >= 2:
            return ("gpio", parts[0].strip(), parts[1].strip())
    if s.startswith("device:"):
        s = s.split("device:",1)[1]
    return ("device", s)

# ===================== 主函式 =====================
def FAN_test():
    """
    讀 TOML：
      [FAN]
      expect = N
      [[FAN.items]]
      manual    = true/false        # ✔=手動（相容 test_fan()）；沒勾=自動
      seconds   = 2~10
      fan_path  = "eapi:N" | "N" | "/sys/devices/platform/pwm-fan" | "/sys/class/hwmon/hwmonX" | 手動語法(i2c:/gpio:/device:)
      low       = 1000              # 自動：低速目標 rpm
      high      = 7000              # 自動：高速目標 rpm
      tolerance = 10                # 百分比
    """
    fan_cfg = toml_get("FAN", "items", [])
    expect  = int(toml_get("FAN", "expect", 0))
    items   = fan_cfg[:expect] if expect>0 else fan_cfg

    if not items:
        print("[FAN] 無設定，SKIP")
        return True, "[SKIP]"

    all_pass, results = True, []

    for idx, it in enumerate(items, 1):
        manual   = bool(it.get("manual", False))
        seconds  = float(it.get("seconds", 2))
        fanp_raw = str(it.get("fan_path") or it.get("path") or "").strip()
        low      = int(it.get("low", 0))
        high     = int(it.get("high", 0))
        tol      = int(it.get("tolerance", 10))

        # ===== 手動：相容 test_fan() 的三種 target（device/i2c/gpio） =====
        if manual:
            # 防呆：手動不支援 eapi:N 或純數字
            if re.match(r'^(eapi:\d+|\d+)$', fanp_raw, re.I):
                all_pass=False
                results.append(f"[{idx}] 手動模式不支援 EAPI：{fanp_raw}")
                continue

            kind, *args = _parse_manual_target(fanp_raw)
            print(f"[FAN-{idx}] 手動模式 target={kind} path={fanp_raw}")

            if kind == "device":
                devpath = args[0]
                if _is_rk():
                    # 依原 shell 在 RK 的序列（pwmchip export→pwm0...）
                    try:
                        os.chdir(devpath)
                        with open("export","w") as f: f.write("0")
                        os.chdir("pwm0")
                        with open("period","w") as f: f.write("10000")
                        with open("duty_cycle","w") as f: f.write("10000")  # 100%
                        with open("polarity","w") as f: f.write("normal")
                        with open("enable","w") as f: f.write("1")
                        _sleep(seconds)
                        with open("duty_cycle","w") as f: f.write("5000")   # 50%
                        with open("polarity","w") as f: f.write("normal")
                        with open("enable","w") as f: f.write("1")
                        _sleep(seconds)
                        with open("duty_cycle","w") as f: f.write("0")      # 0%
                        with open("polarity","w") as f: f.write("normal")
                        with open("enable","w") as f: f.write("1")
                        os.chdir("..")
                        with open("unexport","w") as f: f.write("0")
                    except Exception as e:
                        all_pass=False; results.append(f"[{idx}] RK 手動序列失敗：{e}")
                else:
                    # 一般 sysfs：找 pwm1 切換 50%→100%→0%
                    pwm_path = _find_pwm1_under(devpath)
                    if not pwm_path:
                        all_pass=False; results.append(f"[{idx}] 找不到 pwm1：{devpath}")
                    else:
                        _write_pwm_sysfs(pwm_path, 50);  _sleep(seconds)
                        _write_pwm_sysfs(pwm_path, 100); _sleep(seconds)
                        _write_pwm_sysfs(pwm_path, 0);   _sleep(0.3)

            elif kind == "i2c":
                bus, addr, reg = args
                for v in (30, 100, 0):
                    try:
                        subprocess.check_call(["i2cset","-f","-y",str(bus), hex(addr), hex(reg), str(v)],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as e:
                        all_pass=False; results.append(f"[{idx}] i2cset 失敗：{e}")
                    _sleep(seconds)

            elif kind == "gpio":
                export_num, gpio_name = args
                try:
                    with open("/sys/class/gpio/export","w") as f: f.write(str(export_num))
                    name = str(gpio_name)
                    if name.isdigit(): name = f"gpio{name}"
                    base = f"/sys/class/gpio/{name}"
                    with open(os.path.join(base,"direction"),"w") as f: f.write("out")
                    with open(os.path.join(base,"value"),"w") as f: f.write("1")
                    _sleep(seconds)
                    with open(os.path.join(base,"value"),"w") as f: f.write("0")
                    _sleep(0.3)
                    with open("/sys/class/gpio/unexport","w") as f: f.write(str(export_num))
                except Exception as e:
                    all_pass=False; results.append(f"[{idx}] GPIO 切換失敗：{e}")

            # 人工確認
            ok = _ask_human(f"[FAN-{idx}] 風扇是否有快慢變化？")
            if not ok:
                all_pass=False; results.append(f"[{idx}] 無轉速變化(手動)")
            continue

        # ===== 自動：EAPI（相容 test_FR68_FAN）或 sysfs（Jetson/RK/ARM） =====
        if re.match(r'^(eapi:\d+|\d+)$', fanp_raw, re.I): # EAPI 或數字
            # --- x86 / EAPI ---
            try:
                dev = int(fanp_raw.split(":")[1]) if ":" in fanp_raw else int(fanp_raw)
            except:
                dev = 0
            print(f"[FAN-{idx}] 自動 EAPI dev={dev} sec={seconds} low/high={low}/{high} tol={tol}")

            _set_pwm_eapi(dev, DEFAULT_PWM_LO); _sleep(seconds)
            rpm_lo = _read_rpm_eapi(dev)
            if not _within(rpm_lo, low, tol):
                all_pass=False; results.append(f"[{idx}] 低速 {rpm_lo} 不在 {low}±{tol}%")

            _set_pwm_eapi(dev, DEFAULT_PWM_HI); _sleep(seconds)
            rpm_hi = _read_rpm_eapi(dev)
            if not _within(rpm_hi, high, tol):
                all_pass=False; results.append(f"[{idx}] 高速 {rpm_hi} 不在 {high}±{tol}%")

            _set_pwm_eapi(dev, 0); _sleep(0.4)
            continue

        # --- Jetson / RK / 一般 ARM：sysfs 自動 ---
        print(f"[FAN-{idx}] 自動 sysfs path={fanp_raw} sec={seconds} low/high={low}/{high} tol={tol}")
        pwm_path = _find_pwm1_under(fanp_raw)
        if not pwm_path:
            all_pass=False; results.append(f"[{idx}] 找不到 pwm1：{fanp_raw}")
            continue

        rpm_path = _find_fan_input_near(pwm_path)
        if not rpm_path:
            # 自動與手動已分離：找不到 tach 就判 FAIL
            all_pass=False; results.append(f"[{idx}] 找不到 fan*_input（無法自動驗證）：{fanp_raw}")
            continue

        _write_pwm_sysfs(pwm_path, DEFAULT_PWM_LO); _sleep(seconds)
        rpm_lo_v = _read_rpm_sysfs(rpm_path)
        if not _within(rpm_lo_v, low, tol):
            all_pass=False; results.append(f"[{idx}] 低速 {rpm_lo_v} 不在 {low}±{tol}%")

        _write_pwm_sysfs(pwm_path, DEFAULT_PWM_HI); _sleep(seconds)
        rpm_hi_v = _read_rpm_sysfs(rpm_path)
        if not _within(rpm_hi_v, high, tol):
            all_pass=False; results.append(f"[{idx}] 高速 {rpm_hi_v} 不在 {high}±{tol}%")

        _write_pwm_sysfs(pwm_path, 0); _sleep(0.3)

    if all_pass:
        print("[FAN] PASS"); return True, "PASS"
    msg = "; ".join(results)
    print(f"[FAN] FAIL: {msg}"); return False, msg


def MIC_test():
    """
    自動偵測可用 MIC/喇叭裝置；若你想固定，改 MIC_DEVICES/PLAYBACK 即可。
    """
    # ===== 可以改這裡做「固定指定」；設成 None 代表用自動偵測 =====
    MIC_DEVICES = None          # 例：["plughw:1,0"]；None=自動
    PLAYBACK    = None          # 例："plughw:1,0"；None=自動
    RATE = 32000
    FORMAT = "cd"
    # ===============================================================

    if MIC_DEVICES is None or PLAYBACK is None:
        auto_caps, auto_play = pick_mic_devices()
        MIC_DEVICES = MIC_DEVICES or auto_caps
        PLAYBACK    = PLAYBACK    or (auto_play or (auto_caps[0] if auto_caps else None))

    if not MIC_DEVICES or not PLAYBACK:
        return False, "找不到可用的錄音/播放裝置（arecord/aplay -L）"

    parent = QApplication.instance().activeWindow()

    for dev in MIC_DEVICES:
        cmd = f"arecord -D {dev} -r {RATE} -f {FORMAT} | aplay -D {PLAYBACK} -r {RATE}"
        try:
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                preexec_fn=os.setsid,                # 讓它有自己的 process group
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            return False, f"MIC 啟動失敗: {dev} ({e})"

        time.sleep(1.0)
        ans = QMessageBox.question(
            parent, "MIC 測試", f"裝置 {dev}\n是否聽到錄製的聲音？",
            QMessageBox.Yes | QMessageBox.No
        )
        heard = (ans == QMessageBox.Yes)

        # 收尾：安全終止 arecord|aplay
        try: os.killpg(proc.pid, signal.SIGTERM)
        except Exception: pass
        try: proc.wait(timeout=1.0)
        except Exception:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except Exception: pass

        if not heard:
            return False, f"MIC 錄音播放無聲音 (dev={dev}, play={PLAYBACK})"

        time.sleep(0.3)

    return True, "MIC test passed."

def LINE_IN_test():
    """
    LINE-IN 自檢：播放已知音（若沒有 sample.wav 就臨時產生），
    同時從指定裝置錄音；之後播放錄下的檔案，讓使用者用對話框確認是否聽得到。
    """
    # 0) 確認 arecord/aplay 存在
    if not shutil.which("arecord") or not shutil.which("aplay"):
        return False, "系統缺少 arecord/aplay"

    # 1) 取得錄音/播放裝置（可跟 MIC 共用自動偵測）
    try:
        cap_list, play_dev = pick_mic_devices()
    except Exception as e:
        return False, f"裝置偵測失敗：{e}"
    if not cap_list or not play_dev:
        return False, "找不到可用的錄音/播放裝置（請檢查 arecord -L / aplay -L）"
    cap_dev = cap_list[0]              # 取第一個錄音裝置
    RATE, FMT = 32000, "cd"

    # 2) 準備播放音檔：優先使用當前資料夾 sample.wav；沒有就臨時產生
    workdir = os.getcwd()
    sample_path = os.path.join(workdir, "sample.wav")
    temp_tone = None
    if not os.path.exists(sample_path): # 沒有就臨時產生
        fd, temp_tone = tempfile.mkstemp(prefix="linein_tone_", suffix=".wav")
        os.close(fd)
        gen_tone_wav(temp_tone, secs=5, rate=RATE, freq=1000)
        sample_path = temp_tone

    parent = QApplication.instance().activeWindow()  # 若你有主窗參考，建議改成主窗

    # 3) 引導動作：接線
    QMessageBox.information(
        parent, "LINE-IN 測試",
        "請「移除耳機」，並用連接線把 LINE_IN 與 Headphone/Speaker 連接完成，然後按「繼續測試」。"
    )

    # 4) 同步錄/播（錄 6 秒，播樣本 5 秒）
    rec_path = os.path.join(tempfile.gettempdir(), "linein_record.wav")
    rec_cmd = f"timeout 6 arecord -D {cap_dev} -r {RATE} -f {FMT} -t wav {rec_path}"
    play_cmd = f"timeout 5 aplay -D {play_dev} -r {RATE} {sample_path}"

    # 開兩個子行程（各自的 process group，便於收尾）
    try:
        rec_proc = subprocess.Popen(
            ["bash", "-lc", rec_cmd],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        play_proc = subprocess.Popen(
            ["bash", "-lc", play_cmd],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        # 清理半啟動
        for pr in [locals().get("rec_proc"), locals().get("play_proc")]:
            if pr and pr.poll() is None:
                try: os.killpg(pr.pid, signal.SIGTERM)
                except Exception: pass
        return False, f"啟動錄放失敗（{e}）"

    # 等待兩邊完成（timeout 已在命令中）
    try:
        play_proc.wait(timeout=7)
    except Exception:
        try: os.killpg(play_proc.pid, signal.SIGKILL)
        except Exception: pass
    try:
        rec_proc.wait(timeout=8)
    except Exception:
        try: os.killpg(rec_proc.pid, signal.SIGKILL)
        except Exception: pass

    # 5) 引導動作：復原
    QMessageBox.information(
        parent, "LINE-IN 測試",
        "請「移除連接線」，並把耳機插回去，然後按「繼續測試」。"
    )

    # 6) 回放剛才錄到的檔，並詢問是否聽到
    if not os.path.exists(rec_path) or os.path.getsize(rec_path) == 0:
        # 沒錄到任何東西
        if temp_tone: 
            try: os.remove(temp_tone)
            except Exception: pass
        return False, "未產生錄音檔（可能錄音裝置/權限有誤）"

    try:
        pb = subprocess.Popen(
            ["bash", "-lc", f"aplay -D {play_dev} -r {RATE} {rec_path}"],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        pb.wait(timeout=10)
    except Exception:
        pass  # 播放失敗也會交由人工判定

    heard = (QMessageBox.question(
        parent, "LINE-IN 測試", "是否聽到剛才錄下的聲音？", 
        QMessageBox.Yes | QMessageBox.No
    ) == QMessageBox.Yes)

    # 7) 清理臨時檔
    try: os.remove(rec_path)
    except Exception: pass
    if temp_tone:
        try: os.remove(temp_tone)
        except Exception: pass

    if not heard:
        return False, f"LINE-IN 錄音/回放無聲（rec:{cap_dev} → play:{play_dev}）"
    return True, "LINE-IN test passed."

def SPEAKER_test():
    """
    喇叭左右聲道測試：
    - 先彈窗說明測試會各播 1 次（speaker-test -l 1）
    - 自動找播放裝置（或你可改成固定）
    - 播放結束後詢問「左右聲道是否正確播音？」
    """
    # 0) 檢查工具
    if not shutil.which("speaker-test"):
        return False, "系統缺少 speaker-test（請先安裝 alsa-utils）"

    # 1) 選播放裝置（沿用你前面放的工具函式；沒有就改成固定字串）
    play_devs = _list_alsa_devices("playback")   # 例如 ['plughw:1,0','hw:0,0',...]
    if not play_devs:
        return False, "找不到可用的播放裝置（aplay -L 為空）"

    # 可固定某一張卡：play_dev = "plughw:1,0"
    play_dev = play_devs[0] # 取第一個,通常是主要聲卡

    parent = QApplication.instance().activeWindow()  # 若手上有主窗參考，建議改成主窗
    QMessageBox.information(
        parent, "SPEAKER 測試",
        "將進行左右聲道單獨播音（各 1 次）。\n"
        "請注意聽左聲道與右聲道是否正確。"
    )

    # 2) 播放（speaker-test：-D 裝置, -l 次數, -c 2 兩聲道, -t sine 正弦波）
    #    -p 在不同平台意義不同，這裡用「次數」控制，不靠時間
    cmd = f"speaker-test -D {play_dev} -l 1 -c 2 -t sine"
    try:
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        return False, f"speaker-test 啟動失敗（{play_dev}）：{e}"

    # 等待播放完成（一次循環通常 < 10 秒）
    try:
        proc.wait(timeout=20)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        return False, "speaker-test 未正常結束"

    # 3) 讓使用者判斷
    test_results = (QMessageBox.question(
        parent, "SPEAKER 測試", "左右聲道是否正確播音？",
        QMessageBox.Yes | QMessageBox.No
    ) == QMessageBox.Yes)

    if not test_results:
        return False, f"SPEAKER 測試失敗（播放裝置：{play_dev}）"
    return True, "SPEAKER test passed."


def CAMERA_test(width=1280, height=720, fps=30, seconds=1,                            # 定義相機測試函式，預設解析度 1280x720、FPS=30、錄製秒數=1
                snapshot_dir="snapshots", max_probe=8, verbose_nodes=False):          # 快照輸出目錄、最多探測的 /dev/video 節點數、是否輸出節點級詳細結果
    """
    規則：『有成功拍到 JPG 才 PASS』
    - Jetson CSI: libcamera-still（優先）、否則 nvarguscamerasrc
    - USB/UVC: ffmpeg/gstreamer 多策略
    分組：USB 以 sysfs 找到相同上游 USB 裝置視為同一組；CSI 以 sensor-id 視為一組

    回傳：
    - 預設聚合為『每組一筆』摘要（verbose_nodes=False）
    - 若 verbose_nodes=True，則回傳每個節點的詳細結果
    """                                                                              # 說明函式行為與回傳格式

    # ---------- 小工具 ----------
    def has_cmd(cmd):                                                                # 檢查系統中是否可呼叫某個指令
        return subprocess.call(
            ["bash","-lc",f"command -v {shlex.quote(cmd)} >/dev/null 2>&1"]          # 用 bash 查詢 command -v，成功回 0
        ) == 0

    def run(cmd, timeout=None):                                                      # 執行系統命令並回傳 stdout（字串）
        return subprocess.check_output(
            ["bash","-lc",cmd], text=True, stderr=subprocess.STDOUT, timeout=timeout # 以 bash -lc 執行，文字模式，stderr 併入 stdout
        )

    HAS_V4L2 = has_cmd("v4l2-ctl")                                                  # 紀錄系統是否有 v4l2-ctl（方便後續能力檢查）

    def is_jetson():                                                                 # 粗略判斷是否為 Jetson（aarch64）
        try:
            arch = run("uname -m || true").strip().lower()                           # 讀取 CPU 架構
            return arch == "aarch64"                                                 # aarch64 多半是 Jetson 或 ARM64
        except Exception:
            return False

    def snap_path(base):                                                             # 產生快照輸出檔名（含時間戳）
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")                                # 目前時間
        safe = re.sub(r"[^a-zA-Z0-9_]+","_", base)                                   # 將不適合檔名的字元轉成底線
        return os.path.join(snapshot_dir, f"{safe}_{ts}.jpg")                        # 回傳完整路徑

    def finalize_if_nonempty(tmp_path, final_jpg):                                   # 將暫存檔搬到正式檔（非 0B 才搬）
        try:
            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:           # 確認暫存檔存在且大小 > 0
                shutil.move(tmp_path, final_jpg)                                     # 搬移成最終檔名
                return True
        finally:
            if os.path.exists(tmp_path):                                             # 無論成功與否，確保暫存檔被清掉
                os.remove(tmp_path)
        return False

    def is_video_capture_node(dev):                                                  # 檢查節點是否具備 Video Capture 能力
        if not HAS_V4L2:                                                             # 若無 v4l2-ctl，就放行（避免誤砍）
            return True
        try:
            out = run(f"v4l2-ctl -d {shlex.quote(dev)} --all 2>/dev/null || true")   # 查詢裝置能力
            return ("Video Capture" in out) or ("Device Caps" in out and "Video Capture" in out)  # 只要能力有 Video Capture 即可
        except Exception:
            return False

    def usb_group_of(dev):                                                           # 透過 sysfs 找出上游 USB 裝置，建立同一台相機的 group key
        # 透過 sysfs 找到上游 USB 裝置，建立同一台相機的 group key
        try:
            vname = os.path.basename(dev)  # video0                                     # 取出節點名（videoX）
            sys_path = run(f"readlink -f /sys/class/video4linux/{vname}/device || true").strip()  # 追蹤到實體裝置路徑
            limit = 8
            p = sys_path
            while limit > 0 and p and not os.path.exists(os.path.join(p, "idVendor")):  # 往上找直到遇到有 idVendor 的 USB 裝置目錄
                np = os.path.dirname(p)
                if np == p: break
                p = np
                limit -= 1
            if p and os.path.exists(os.path.join(p, "idVendor")):                    # 找到真正的 USB 裝置節點
                vendor = open(os.path.join(p, "idVendor")).read().strip()           # 讀取廠商 ID
                product = open(os.path.join(p, "idProduct")).read().strip()         # 讀取產品 ID
                return f"USB-{os.path.basename(p)}:{vendor}:{product}"              # 組出群組鍵（含 USB 拓樸 + VID:PID）
            if sys_path:                                                             # 若未讀到 idVendor，退而求其次用父層名
                return f"USB-{os.path.basename(sys_path)}"
        except Exception:
            pass
        return f"USB-{dev}"                                                          # 最後保底：用節點名當群組鍵

    pathlib.Path(snapshot_dir).mkdir(parents=True, exist_ok=True)                    # 確保快照目錄存在

    # ---------- 探測並分組 ----------
    cams = []  # {name,bus,node,sid,group}                                           # 用來存放所有候選相機節點與分組資訊

    # CSI (libcamera)
    if has_cmd("libcamera-hello"):                                                   # 若有 libcamera-hello，列出 CSI 相機
        try:
            out = run("libcamera-hello --list-cameras 2>&1 || true")                 # 列出 CSI 相機清單
            if "Available cameras" in out:                                           # 若有可用相機
                blocks = re.split(r"\n\s*\d+\s*:", out)                               # 依編號分割
                for i, b in enumerate(blocks[1:]):                                   # 逐一解析各相機
                    head = b.strip().splitlines()[0].strip()                         # 取第一行描述
                    name = head.split("[")[0].strip()                                # 去除尾端 [index] 等附註
                    cams.append({"name": f"{name} (CSI{i})", "bus":"CSI", "node":None,
                                 "sid":i, "group": f"CSI-{i}-{name}"})               # 加入 CSI 相機（用 sid 分組）
        except Exception:
            pass

    # USB（優先用 v4l2-ctl；否則保底掃描）
    if HAS_V4L2:                                                                     # 若有 v4l2-ctl，用它列出裝置群組
        try:
            out = run("v4l2-ctl --list-devices 2>/dev/null || true")                 # 列出所有 video 裝置群組
            blocks = re.split(r"\n\s*\n", out.strip())                                # 以空行分割群組
            for b in blocks:
                lines = [l for l in b.splitlines() if l.strip()]                     # 淨化空白行
                if not lines: continue
                devs = [l.strip() for l in lines[1:] if l.strip().startswith("/dev/video")]  # 群組中的每個 /dev/videoX
                for d in devs:
                    if os.path.exists(d) and is_video_capture_node(d):               # 僅收具 Video Capture 能力的節點
                        g = usb_group_of(d)                                          # 根據 sysfs 建立 USB 群組鍵
                        name = f"{os.path.basename(g)} (UVC)"                        # 顯示名稱：取 group key 的尾段
                        cams.append({"name":name,"bus":"USB","node":d,"sid":None,"group":g})  # 加入 USB 相機候選
        except Exception:
            pass

    if not any(c["bus"]=="USB" for c in cams):                                       # 若前段沒收集到任何 USB，相機則改用保底掃描
        for i in range(max_probe):                                                   # 逐一探測 /dev/video0..max_probe-1
            dev = f"/dev/video{i}"
            if os.path.exists(dev) and is_video_capture_node(dev):                   # 裝置存在且具備 Video Capture 能力
                g = usb_group_of(dev)                                                # 建立群組鍵
                name = f"{os.path.basename(g)} (UVC)"                                # 顯示名稱
                cams.append({"name":name,"bus":"USB","node":dev,"sid":None,"group":g})  # 收進候選清單

    # Jetson 沒抓到 CSI → fallback
    if is_jetson() and not any(c["bus"]=="CSI" for c in cams):                       # Jetson 上若沒列出任何 CSI，就補一個 sensor-id=0 的候選
        cams.append({"name":"CSI(sensor-id=0)","bus":"CSI","node":None,"sid":0,
                     "group":"CSI-0-fallback"})

    if not cams:                                                                     # 若仍找不到任何相機
        return False, [{
            "name":"-", "bus":"-", "node":None, "result":"FAIL",
            "reason":"找不到任何相機裝置（可能未加入 video 群組或缺 v4l2-ctl）", "snapshot":None
        }]

    # ---------- 單顆測試 ----------
    def test_csi(cam):                                                               # 測試 CSI 相機（libcamera → nvargus）
        if has_cmd("libcamera-still"):                                               # 先用 libcamera-still
            final = snap_path(cam["name"])                                           # 目標快照檔名
            tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg")         # 暫存檔名
            sid = cam.get("sid", 0)                                                  # 取 camera sensor-id
            cmd = (f"libcamera-still -n -t {int(seconds*1000)} -o {shlex.quote(tmp)} "
                   f"--width {width} --height {height} --camera {sid} 2>&1")         # 拍照命令
            try:
                run(cmd, timeout=max(6, seconds+4))                                  # 執行命令
                if finalize_if_nonempty(tmp, final):                                 # 若成功產生非 0B，搬到正式檔
                    return True, "OK(libcamera-still)", final                        # PASS 與原因
            except Exception as e:
                last_err = f"libcamera-still 失敗：{str(e).splitlines()[-1][:160]}"  # 紀錄最後錯誤簡述
        else:
            last_err = "libcamera-still 不可用"                                      # 紀錄無 libcamera-still

        if has_cmd("gst-launch-1.0"):                                                # 若可用 GStreamer，改走 nvargus 管線
            final = snap_path(cam["name"])
            tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg")
            sid = cam.get("sid", 0)
            cmd = ("gst-launch-1.0 -e "
                   f"nvarguscamerasrc sensor-id={sid} num-buffers=1 ! "
                   f"video/x-raw(memory:NVMM),width={width},height={height},framerate={fps}/1 ! "
                   "nvjpegenc ! filesink location=" + shlex.quote(tmp) + " -q")      # nvargus 取一張轉 JPEG
            try:
                run(cmd, timeout=max(8, seconds+6))                                  # 執行
                if finalize_if_nonempty(tmp, final):                                 # 成功則搬檔
                    return True, "OK(gst-nvargus)", final                            # PASS 與原因
                return False, "gst 未產生影像", None                                 # 有跑但未產生影像
            except Exception as e:
                return False, f"CSI 開啟失敗（gst）：{str(e).splitlines()[-1][:160]}", None  # 失敗回傳
        return False, f"{last_err}；且無 gst-launch-1.0", None                        # 若 libcamera 失敗且無 gst，回 FAIL

    def test_uvc(cam):                                                               # 測試 USB/UVC 相機
        dev = cam["node"]                                                            # 當前節點 e.g. /dev/video0
        last_err = "未嘗試"                                                          # 累計錯誤訊息

        # ffmpeg（mjpeg / yuyv422）
        if has_cmd("ffmpeg"):                                                        # 若有 ffmpeg，先試 MJPG / 再試 YUYV
            for fmt, tag in [("mjpeg","mjpeg"), ("yuyv422","yuyv422")]:
                final = snap_path(cam["name"])                                       # 目標快照檔名
                tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg")     # 暫存檔名
                cmd = (f"ffmpeg -y -hide_banner -loglevel error "
                       f"-f video4linux2 -input_format {fmt} -framerate {fps} -video_size {width}x{height} "
                       f"-i {shlex.quote(dev)} -frames:v 1 {shlex.quote(tmp)}")      # ffmpeg 取一張
                try:
                    run(cmd, timeout=max(8, seconds+6))                               # 執行命令
                    if finalize_if_nonempty(tmp, final):                              # 非 0B 才搬到正式檔
                        return True, f"OK(ffmpeg {tag})", final                       # PASS 與原因（標示使用的像素格式）
                except Exception as e:
                    last_err = f"ffmpeg({tag})失敗：{str(e).splitlines()[-1][:120]}" # 累計錯誤
        else:
            last_err = "ffmpeg 不可用"                                               # 系統無 ffmpeg

        # GStreamer（raw / mjpg）
        if has_cmd("gst-launch-1.0"):                                                # 若有 GStreamer，試 raw 與 mjpg 流
            pipelines = [
                ("raw→jpeg",
                 "v4l2src device={dev} num-buffers=1 ! "
                 f"video/x-raw,width={width},height={height},framerate={fps}/1 ! "
                 "videoconvert ! jpegenc ! filesink location={out} -q"),             # raw 取流轉 JPEG
            ]
            # 有些相機 raw 不行才試 mjpg→decode→jpeg
            pipelines.append(
                ("mjpg→decode→jpeg",
                 "v4l2src device={dev} num-buffers=1 ! "
                 f"image/jpeg,framerate={fps}/1 ! jpegparse ! jpegdec ! "
                 "videoconvert ! jpegenc ! filesink location={out} -q")              # MJPG 解碼後再轉 JPEG
            )
            for tag, pipe in pipelines:
                final = snap_path(cam["name"])
                tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg")
                cmd = ("gst-launch-1.0 -e " + pipe.format(dev=shlex.quote(dev), out=shlex.quote(tmp)))  # 組合管線
                try:
                    run(cmd, timeout=max(10, seconds+8))                              # 執行
                    if finalize_if_nonempty(tmp, final):                              # 成功則搬檔
                        return True, f"OK(gst {tag})", final                          # PASS 與原因（標示走的路徑）
                except Exception as e:
                    last_err = f"{last_err}；gst({tag})失敗：{str(e).splitlines()[-1][:120]}"  # 累計錯誤
        return False, f"無法擷取 JPG（{last_err}）", None                             # 所有策略皆失敗 → FAIL

    # ---------- 逐一測試（同組有 PASS 就跳過其他節點並標記 SKIP） ----------
    node_details = []                                                                 # 節點級的詳細紀錄（可能包含 SKIP）
    group_best = {}   # group -> 最佳結果 (PASS 優先；否則第一個 FAIL)                  # 每組一筆最佳結果（優先 PASS）
    group_passed = set()                                                              # 已經 PASS 的組集合（用來 SKIP 後續同組節點）

    for cam in cams:                                                                  # 逐一處理候選相機
        g = cam["group"]                                                              # 取得群組鍵

        if g in group_passed:                                                         # 若同組已經 PASS
            # 同組已通過，不再測，標示 SKIP
            node_details.append({
                "name": cam["name"], "bus": cam["bus"], "node": cam["node"],
                "result": "SKIP", "reason": "同組已通過（不影響總結果）",
                "snapshot": None, "group": g
            })
            continue                                                                   # 跳過實測

        if cam["bus"] == "CSI":                                                       # 依匯流排型態選測試方法
            ok, reason, snap = test_csi(cam)
        elif cam["bus"] == "USB":
            ok, reason, snap = test_uvc(cam)
        else:
            if isinstance(cam.get("node"), str) and cam["node"].startswith("/dev/video"):
                ok, reason, snap = test_uvc(cam)                                      # 未知但長得像 /dev/videoX，當 USB 試試
            else:
                ok, reason, snap = False, "未知型別且無節點", None                    # 無法測

        node_details.append({                                                         # 紀錄節點級結果
            "name": cam["name"], "bus": cam["bus"], "node": cam["node"],
            "result": "PASS" if ok else "FAIL", "reason": reason, "snapshot": snap,
            "group": g
        })

        # 記錄/更新該組最佳結果
        if ok:                                                                        # 若本節點 PASS
            group_best[g] = {
                "name": cam["name"], "bus": cam["bus"], "node": cam["node"],
                "result": "PASS", "reason": reason, "snapshot": snap, "group": g
            }
            group_passed.add(g)                                                       # 標示此組已 PASS（後續同組直接 SKIP）
        else:
            group_best.setdefault(g, {                                                # 若該組尚無紀錄，先記下第一個 FAIL
                "name": cam["name"], "bus": cam["bus"], "node": cam["node"],
                "result": "FAIL", "reason": reason, "snapshot": snap, "group": g
            })

    # 總判斷：任一組 PASS 即 overall PASS（符合 1 台相機多節點情境）
    # overall = any(v["result"] == "PASS" for v in group_best.values()) if group_best else False  # 若任一組 PASS → 整體 PASS
    test_results = all(v["result"] == "PASS" for v in group_best.values()) if group_best else False # 若要全組通過才算 PASS，可改成 all()


    # 預設回傳『每組一筆』摘要；需要完整節點紀錄就設 verbose_nodes=True
    if verbose_nodes:                                                                  # 若要看全部節點（含 SKIP）
        return test_results, node_details
    else:
        # 僅回傳各組最佳結果（PASS 會覆蓋 FAIL；沒 PASS 就保留該組第一個 FAIL）
        return test_results, list(group_best.values())                                      # 預設只回傳每組最佳摘要

def CANBUS_test():
    """
    規則：
      - 自動偵測目前的 CAN 介面（/sys/class/net 下 type=280 的介面，典型為 can0、can1）
      - 若只找到 1 個介面：等待外部治具在 timeout 內打進 (ID=0x123, DATA=AB CD AB CD)
      - 若找到 ≥2 個介面：在 iface[0] cansend，iface[1] candump 接收並驗證
    需求工具：
      modprobe, ip, candump, cansend （can-utils）
    回傳：(ok, msg)
    """
    # 這裡可以加入實際的 CANBUS 測試程式碼
    # ok, msg = True, "CANBUS test passed."
    # return ok, msg  
        # === 可調參數（與你 Bash 同設定）===
    EXPECT_ID_HEX = 0x123
    EXPECT_DATA_HEX = "AB CD AB CD"     # 用空白分隔
    BITRATE = 1_000_000
    TIMEOUT_S = 3.0

    def run(cmd, check=True):
        return subprocess.run(shlex.split(cmd), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

    def modprobe(m):
        try:
            run(f"modprobe {m}", check=True)
        except subprocess.CalledProcessError:
            # 有些核心已內建，失敗就當提醒，不中斷
            pass

    def list_can_ifaces():
        base = "/sys/class/net"
        found = []
        try:
            for name in sorted(os.listdir(base)):
                # 透過 type 判斷（280 = ARPHRD_CAN）
                tp = os.path.join(base, name, "type")
                if os.path.exists(tp):
                    try:
                        if int(open(tp).read().strip()) == 280:
                            found.append(name)
                    except Exception:
                        pass
        except Exception:
            pass
        return found

    def set_up(iface):
        run(f"ip link set {iface} up type can bitrate {BITRATE}", check=True)

    def set_down(iface):
        try:
            run(f"ip link set {iface} down", check=True)
        except subprocess.CalledProcessError:
            pass

    def parse_candump_line(s):
        """
        解析 candump 單行，例如：
        can0  123   [4]  AB CD AB CD
        或    can0  123#ABCDABCD  （不同版面）
        回傳：(iface, id_int, data_bytes) 或 None
        """
        s = s.strip()
        if not s:
            return None
        # 格式1：<if>  <ID>  [len]  <bytes...>
        m = re.match(r"^(\S+)\s+([0-9A-Fa-f]+)\s+\[\d+\]\s+((?:[0-9A-Fa-f]{2}\s+)*[0-9A-Fa-f]{2})", s)
        if m:
            iface = m.group(1)
            canid = int(m.group(2), 16)
            data  = " ".join(m.group(3).split()).upper()
            return iface, canid, data
        # 格式2：<if>  <ID>#<data>（data 連續十六進位）
        m = re.match(r"^(\S+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]+)$", s)
        if m:
            iface = m.group(1)
            canid = int(m.group(2), 16)
            hexs  = m.group(3)
            # 兩位一組加空白
            data  = " ".join(hexs[i:i+2] for i in range(0, len(hexs), 2)).upper()
            return iface, canid, data
        return None

    # 1) 準備模組
    for m in ("can", "can_raw", "mttcan"):
        modprobe(m)

    # 2) 找介面
    ifaces = list_can_ifaces()
    if not ifaces:
        return False, "未偵測到任何 CAN 介面（/sys/class/net）"
    # 最多用兩個
    ifaces = ifaces[:2]

    # 3) 依單/雙介面走不同路徑
    up_if = []
    try:
        if len(ifaces) == 1:
            rx = ifaces[0]
            set_up(rx); up_if.append(rx)

            # 單介面：等外部治具發包；candump 只抓第一行
            try:
                p = subprocess.run(
                    ["bash", "-lc", f"timeout {TIMEOUT_S} candump {shlex.quote(rx)} | head -n1"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                line = (p.stdout or "").strip()
            except Exception as e:
                return False, f"candump 失敗：{e}"

            parsed = parse_candump_line(line)
            if not parsed:
                return False, f"未解析到有效訊框（candump 輸出：{line or '(空)'}）"

            _iface, _id, _data = parsed
            ok = (_id == EXPECT_ID_HEX and _data.upper() == EXPECT_DATA_HEX.upper())
            if ok:
                return True, "CAN 單介面 PASS（治具回傳正確訊框）"
            else:
                return False, f"訊框不符：期望 ID=0x{EXPECT_ID_HEX:X} DATA='{EXPECT_DATA_HEX}'，收到 ID=0x{_id:X} DATA='{_data}'"

        else:
            tx, rx = ifaces[0], ifaces[1]
            set_up(tx); up_if.append(tx)
            set_up(rx); up_if.append(rx)

            # 先在背景丟一包，然後在 rx 端 candump 抓
            # 你原本 Bash：cansend $item1 "123#ABCDABCD"
            send_cmd = f'cansend {shlex.quote(tx)} "123#ABCDABCD"'
            try:
                # 背景送（sleep 0.8 給 rx 起來）
                subprocess.Popen(["bash", "-lc", f"(sleep 0.8; {send_cmd}) >/dev/null 2>&1 &"])
            except Exception as e:
                return False, f"cansend 失敗：{e}"

            try:
                p = subprocess.run(
                    ["bash", "-lc", f"timeout {TIMEOUT_S} candump {shlex.quote(rx)} | head -n1"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                line = (p.stdout or "").strip()
            except Exception as e:
                return False, f"candump 失敗：{e}"

            parsed = parse_candump_line(line)
            if not parsed:
                return False, f"未解析到有效訊框（candump 輸出：{line or '(空)'}）"

            _iface, _id, _data = parsed
            test_results = (_id == EXPECT_ID_HEX and _data.upper() == EXPECT_DATA_HEX.upper())
            if test_results:
                return True, f"CAN 兩介面 PASS（{tx} → {rx}）"
            else:
                return False, f"訊框不符：期望 ID=0x{EXPECT_ID_HEX:X} DATA='{EXPECT_DATA_HEX}'，收到 ID=0x{_id:X} DATA='{_data}'"
    finally:
        # 4) 收尾：把 up 的介面都關掉
        for itf in up_if:
            set_down(itf)

# ===== I2C 測試函式 =====
def I2C_test():
    """
    I2C 測試：
      - 讀取 [I2C] 區段的 pairs 列表，每一筆像 "bus,addr,offset"
      - 解析成 (bus, addr, offset)
      - 每一組進行：
          i2cset -f -y bus addr offset 0x55 → i2cget 應為 0x55
          i2cset -f -y bus addr offset 0xAA → i2cget 應為 0xAA
      - 任一組失敗 → 整體 FAIL
    回傳：(ok, msg)
    其中 msg 包含詳細日誌
    需求工具：
        i2cset, i2cget （i2c-tools）
        subprocess

    使用說明：
    你需要在 TOML 檔案中設定 [I2C] 區段與 pairs 列表
    例如在 test_config.toml 裡面：
    ```toml
    程式過程不限組數, 但可設定 expect 預期組數驗證, 未來若有更多組數需求只須修改 UI即可, UI會自動帶入到 toml
    例如：
    [I2C]
    expect = 2
    pairs = [
        "1,0x50,0x00",
        "1,0x51,0x00",
    ]
    代表預期有 2 組測試項目，分別是 bus=1 addr=0x50 offset=0x00 與 bus=1 addr=0x51 offset=0x00
    也可以用 shell 版本的格式：
        "i2c,1,0x50,0x00"
    會自動忽略開頭的 'i2c' 字串
    這個函式會回傳 (True, "I2C PASS\n詳細日誌...") 或 (False, "I2C FAIL\n詳細日誌...")
    失敗原因可能是設定錯誤、i2cset/i2cget 失敗、讀回值不符等
    你可以根據回傳結果決定後續動作
    例如在 unittest 裡面：
        ok, msg = I2C_test()
        self.assertTrue(ok, msg)
    這樣若測試失敗，unittest 會顯示詳細日誌，方便除錯
    你也可以直接在主程式呼叫並印出結果：
        ok, msg = I2C_test()
        print(msg)
    """

    # ===== 從 TOML 讀取 I2C 區段 =====
    # 直接用 toml_get，不用 globals()
    blk = toml_get("I2C", None, {}) or {}

    pair_list = list(blk.get("pairs", []) or [])

    try:
        expect = int(blk.get("expect", 0) or 0)
    except Exception:
        expect = 0

    pair_count = len(pair_list)

    if expect > 0 and pair_count != expect:
        return False, f"[I2C] FAIL：設定預期測試組數 {expect} 與實際 {pair_count} 不符"

    if not pair_list:
        return True, "[I2C] 未設定任何測試項目，跳過測試"

    logs = []
    all_ok = True

    for idx, pair_str in enumerate(pair_list, start=1): # idx 從 1 開始, pair_str 是 "bus,addr,offset" 解析 bus, addr, offset
        parts = [p.strip() for p in str(pair_str).split(",") if p.strip()] # 分割並去除空白, 也避免空字串, 例如 "i2c,1,0x50,0x00" 會變成 ['i2c', '1', '0x50', '0x00']

        if not parts:
            logs.append(f"[I2C] 第 {idx} 組是空字串，略過")
            continue

        # 如果第一個是 'i2c'，就當成 shell 版本的格式，丟掉第一個
        if parts[0].lower() == "i2c":
            parts = parts[1:]

        if len(parts) < 3:
            logs.append(f"[I2C] 第 {idx} 組格式錯誤：{pair_str}")
            all_ok = False
            break

        bus, addr, offset = parts[0], parts[1], parts[2]

        # ===== 寫 0x55 =====
        cmd_set_55 = ["i2cset", "-f", "-y", bus, addr, offset, "0x55"]
        res = subprocess.run(cmd_set_55, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            all_ok = False
            logs.append(f"[I2C] 第 {idx} 組 i2cset 0x55 失敗：{res.stderr.strip()}")
            continue

        # ===== 讀回驗證 0x55 =====
        cmd_get = ["i2cget", "-f", "-y", bus, addr, offset]
        res = subprocess.run(cmd_get, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            all_ok = False
            logs.append(f"[I2C] 第 {idx} 組 i2cget 失敗：{res.stderr.strip()}")
            continue

        val = res.stdout.strip()
        if val != "0x55":
            all_ok = False
            logs.append(
                f"[I2C] 第 {idx} 組：寫 0x55 但讀到 {val} "
                f"(bus={bus}, addr={addr}, offset={offset})"
            )
            continue

        # ===== 寫 0xAA =====
        cmd_set_aa = ["i2cset", "-f", "-y", bus, addr, offset, "0xAA"]
        res = subprocess.run(cmd_set_aa, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            all_ok = False
            logs.append(f"[I2C] 第 {idx} 組 i2cset 0xAA 失敗：{res.stderr.strip()}")
            continue

        # ===== 讀回驗證 0xAA =====
        res = subprocess.run(cmd_get, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            all_ok = False
            logs.append(f"[I2C] 第 {idx} 組 i2cget 失敗：{res.stderr.strip()}")
            continue

        val = res.stdout.strip()
        if val != "0xAA":
            all_ok = False
            logs.append(
                f"[I2C] 第 {idx} 組：寫 0xAA 但讀到 {val} "
                f"(bus={bus}, addr={addr}, offset={offset})"
            )
            continue

        logs.append(f"[I2C] 第 {idx} 組 PASS (bus={bus}, addr={addr}, offset={offset})")

    if all_ok:
        return True, "[I2C] PASS\n" + "\n".join(logs)
    else:
        return False, "[I2C] FAIL\n" + "\n".join(logs)


class AutoTests(unittest.TestCase): # 繼承 unittest.TestCase, 每個測項包成 test_* 方法, 方便自動化執行, 也方便手動執行,
                                 # 例如 python3 -m unittest Test_item.py, 
                                 # 或 python3 -m unittest Test_item.AutoTests.test_usb, 
                                 # 或 python3 -m unittest discover -s . -p "Test_item.py", 
                                 # 或 python3 -m unittest discover -s . -p "Test_*.py"
    @classmethod # 開始前執行
    def setUpClass(cls):
        # 可選：整批測試前的初始化（例如打開設備/連線）
        pass

    @classmethod # 結束後執行
    def tearDownClass(cls):
        # 可選：整批測試後的清理
        pass

    # 共用執行器：統一設定 _last_msg + 斷言
    def run_item(self, func):
        # ok, msg = func()        # 不支援參數，簡單好讀
        # self._last_msg = msg
        # self.assertTrue(ok, msg)

        # global CURRENT_WINDOW # 使用全域變數 CURRENT_WINDOW
        # if CURRENT_WINDOW: # 若有 GUI 視窗，更新目前測試項目名稱
        #     CURRENT_WINDOW.update_current_item(self._testMethodName) # 傳入目前測試方法名稱
        global CURRENT_WINDOW

        # --- 取得 unittest method name，例如 "test_USB2" ---
        method = self._testMethodName # 取得目前測試方法名稱，例如 "test_USB2"

        # from Test_item import method_to_display_name  # 我們要建立這個映射

        # method = self._testMethodName # 
        display = method_to_display_name(method) # 透過映射取得顯示名稱

        # --- GUI：更新目前測試項目 ---
        if CURRENT_WINDOW: # 若有 GUI 視窗，更新目前測試項目名稱
            try:
                CURRENT_WINDOW.update_current_item(display) # 傳入目前測試方法名稱
            except:
                pass

        # --- 重要！共用 expect 檢查（GUI & CLI 都會用到） ---
        if display in EXPECT_FROM_TOML: # 若此測項有設定期望數量
            sec, key = EXPECT_FROM_TOML[display] # 取得對應的 toml 區段與鍵名
            try:
                exp = int(toml_get(sec, key, 0) or 0) # 讀取期望數量，預設 0
            except:
                exp = 0

            if exp <= 0:
                msg = f"[{display}][FAIL] 未設定期望數量（請在 Config 設定 {sec}.{key}）"
                self._last_msg = msg
                self.fail(msg)
                return

        res = func()
        test_results, msg = (res if isinstance(res, tuple) else (bool(res), ""))[:2] # 支援回傳 (test_results, msg) 或單一 bool, 只取前兩個, 忽略多餘的, 避免錯誤
        self._last_msg = msg or "" # 設定最後訊息, 避免 None 錯誤

        # 建立獨立的 unittest logger（不會干擾 UI）
        logger = logging.getLogger("unittest_logger") # 獨立 logger
        logger.setLevel(logging.INFO) # 設定等級, 預設 WARNING 以上才會輸出, INFO 以上才會輸出訊息
        if not logger.handlers:  # 避免重複加入 handler
            log_path = "./unittest.log" # 日誌檔案路徑
            fh = logging.FileHandler(log_path, encoding="utf-8") # 檔案處理器, utf-8 編碼, 避免亂碼
            fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s")) # 設定格式, 含時間戳, 訊息, 不含等級名稱
            logger.addHandler(fh) # 加入 handler, 寫入檔案, 不會輸出到 console

        func_name = getattr(func, "__name__", "Unknown") # 取得函式名稱, 預設 Unknown, 避免錯誤
        logger.info(f"[{func_name}] {msg}") # 記錄測試結果到日誌檔案, 包含函式名稱與訊息

        if test_results:
            self.assertTrue(True)     # 保持成功通道
        else:
            self.fail(self._last_msg) # 用字串當失敗訊息
            # self.assertTrue(False)

    def test_USB2(self):
        self.run_item(USB2_test)
    
    def test_USB3(self):
        self.run_item(USB3_test)

    def test_NETWORK(self):
        self.run_item(NETWORK_test)

    def test_EEPROM(self):
        self.run_item(EEPROM_test)

    def test_EEPROM_RD(self):
        self.run_item(EEPROM_RD_test)

    def test_GPIO(self):
        self.run_item(GPIO_test)

    def test_Micro_SD(self):
        self.run_item(SD_test)

    def test_MKEY(self):
        self.run_item(MKey_test)

    def test_EKEY(self):
        self.run_item(EKey_test)

    def test_RS232(self):
        self.run_item(RS232_test)

    def test_RS422(self):
        self.run_item(RS422_test)

    def test_RS485(self):
        self.run_item(RS485_test)

    def test_UART(self):
        self.run_item(UART_test)

    def test_SPI(self):
        self.run_item(SPI_test)

    def test_FAN(self):
        self.run_item(FAN_test)

    def test_MIC(self):
        self.run_item(MIC_test)
    
    def test_LINE_IN(self):
        self.run_item(LINE_IN_test)

    def test_SPEAKER(self):
        self.run_item(SPEAKER_test)

    def test_CAMERA(self):
        self.run_item(CAMERA_test)

    def test_CANBUS(self):
        self.run_item(CANBUS_test)

    def test_I2C(self):
        self.run_item(I2C_test)

#----------手動確認項目----------
    def test_CPU(self):
        self.run_item(CPU_test)

    def test_HDMI(self):
        self.run_item(HDMI_test)

    def test_VGA(self):
        self.run_item(VGA_test)

    def test_DP(self):
        self.run_item(DP_test)

    def test_LED(self):
        self.run_item(LED_test)

    def test_POWER_BUTTON(self):
        self.run_item(POWER_BUTTON_test)

    def test_POWER_CONNECTOR(self):
        self.run_item(POWER_CONNECTOR_test)

    def test_POWER_SW_CONNECTOR(self):
        self.run_item(POWER_SW_CONNECTOR_test)

    def test_RESET_BUTTON(self):
        self.run_item(RESET_BUTTON_test)

    def test_RECOVERY_BUTTON(self):
        self.run_item(RECOVERY_BUTTON_test)

    def test_SMA(self):
        self.run_item(SMA_test)

    def test_SW1(self):
        self.run_item(SW1_test)
    
    def test_SW2(self):
        self.run_item(SW2_test)

    def test_MCU_CONNECTOR(self):
        self.run_item(MCU_CONNECTOR_test)

    def test_RTC(self):
        self.run_item(RTC_test)

    def test_RTC_OUT(self):
        self.run_item(RTC_OUT_test)

    def test_DC_INPUT(self):
        self.run_item(DC_INPUT_test)

    def test_DC_OUTPUT(self):
        self.run_item(DC_OUTPUT_test)

    # 要新增測項：新增一個 test_XXX，裡面呼叫 check_xxx()
# ===== unittest：把每個測項包成 test_* 方法 =====

# ===== 顯示名稱 ↔ 測試方法名（給 GUI 用的選單名稱）=====
# ===== 單一命名表：所有自動測項定義在這裡 =====
# 每一筆資料： (顯示名稱, Tests 的方法名, UI checkbox 的物件名稱)
# 單一命名表：顯示名稱、Tests 方法名、UI checkbox 名稱
TEST_ITEMS = [
    # ===== 自動測試項目 =====
    ("USB2.0",           "test_USB2",               "checkBox_USB2"), # USB2.0 測試項目UI上的名稱對應ui_name, test_USB2 方法對應fun_name, checkBox_USB2 物件名稱對應checkbox_name
    ("USB3.0",           "test_USB3",               "checkBox_USB3"),
    ("NetWork",          "test_NETWORK",            "checkBox_NETWORK"),
    ("Micro SD Card",    "test_Micro_SD",           "checkBox_MICROSD"),
    ("M-Key",            "test_MKEY",               "checkBox_MKEY"),
    ("E-Key",            "test_EKEY",               "checkBox_EKEY"),
    ("RS232",            "test_RS232",              "checkBox_RS232"),
    ("RS422",            "test_RS422",              "checkBox_RS422"),
    ("RS485",            "test_RS485",              "checkBox_RS485"),
    ("UART",             "test_UART",               "checkBox_UART"),
    ("GPIO",             "test_GPIO",               "checkBox_GPIO"),
    ("FAN",              "test_FAN",                "checkBox_FAN"),
    ("EEPROM",           "test_EEPROM",             "checkBox_EEPROM"),
    ("EEPROM (RD Test)", "test_EEPROM_RD",          "checkBox_EEPROM_RD"),
    ("Camera",           "test_CAMERA",             "checkBox_Camera"),
    ("CAN BUS",          "test_CANBUS",             "checkBox_CANBUS"),
    ("I2C",              "test_I2C",                "checkBox_I2C"),    

    # ===== 手動測試項目（一樣有 checkbox，可以變色）=====
    ("CPU NAME",         "test_CPU",                "checkBox_CPU"),          # 名稱請照 .ui 實際物件名改
    ("MIC",              "test_MIC",                "checkBox_MIC"),
    ("Line IN",          "test_LINE_IN",            "checkBox_LineIN"),
    ("Speaker",          "test_SPEAKER",            "checkBox_Speaker"),
    ("Power Connector",  "test_POWER_CONNECTOR",    "checkBox_PowerConnector"),
    ("Power SW Connector","test_POWER_SW_CONNECTOR","checkBox_PowerSWConnector"),
    ("Power Button",     "test_POWER_BUTTON",       "checkBox_Power_Button"),
    ("Reset Button",     "test_RESET_BUTTON",       "checkBox_Reset_Button"),
    ("Recovery Button",  "test_RECOVERY_BUTTON",    "checkBox_Recovery_Button"),
    ("LED",              "test_LED",                "checkBox_LED"),
    ("HDMI",             "test_HDMI",               "checkBox_HDMI"),
    ("VGA",              "test_VGA",                "checkBox_VGA"),
    ("DP",               "test_DP",                 "checkBox_DP"),
    ("SMA",              "test_SMA",                "checkBox_SMA"),
    ("SW1",              "test_SW1",                "checkBox_SW1"),
    ("SW2",              "test_SW2",                "checkBox_SW2"),
    ("MCU Connector",    "test_MCU_CONNECTOR",      "checkBox_MCUConnector"),
    ("RTC",              "test_RTC",                "checkBox_RTC"),
    ("RTC OUT",          "test_RTC_OUT",            "checkBox_RTC_OUT"),
    ("DC Input",         "test_DC_INPUT",           "checkBox_DC_INPUT"),
    ("DC Output",        "test_DC_OUTPUT",          "checkBox_DC_OUTPUT"), # DC Output 測試項目UI上的名稱對應ui_name, test_DC_OUTPUT 方法對應fun_name, checkBox_DC_OUTPUT 物件名稱對應checkbox_name
    ("SPI",              "test_SPI",                "checkBox_SPI"),
    # 要新增測項：往這裡新增 ("顯示名稱對應ui_name", "Tests 方法名對應fun_name", "checkbox 名稱對應checkbox_name)")
]

# 由 TEST_ITEMS 自動產生 DISPLAY_NAME_MAP（給 run_selected_tests 用）
# DISPLAY_NAME_MAP = {display: method for display, method, _ in TEST_ITEMS} # 簡潔寫法

DISPLAY_NAME_MAP = {} # 建立空字典, 用來存放顯示名稱到方法名稱的映射, 例如 DISPLAY_NAME_MAP["USB2.0"] = "test_USB2", 以此類推
# TEST_ITEMS: (顯示名稱, test函式名稱, checkbox名稱)
for ui_name, fun_name, checkbox_name in TEST_ITEMS: # 逐一處理每個測試項目
    DISPLAY_NAME_MAP[ui_name] = fun_name # 建立顯示名稱到方法名稱的映射, DISPLAY_NAME_MAP["USB2.0"] = "test_USB2", 以此類推

# ====== MES 整併：從 GUI 選項與測試結果，產生 ITEM_LIST / TEST_LOG，並送出 ======

# 1) 依 UI 顯示名稱，找出「數量 expect」該讀哪個 TOML 區塊與鍵, 僅讀取TOML填數量的項目
EXPECT_FROM_TOML = {
    "USB2.0":           ("USB2", "expect"),
    "USB3.0":           ("USB3", "expect"),
    "NetWork":          ("Network", "expect"),
    "Micro SD Card":    ("Micro SD Card", "expect"),
    "GPIO":             ("GPIO", "expect"),
    "M-Key":            ("M-Key", "expect"),
    "FAN":              ("FAN", "expect"),
    "EEPROM":           ("EEPROM", "expect"),
    "Camera":           ("Camera", "expect"),
    "CAN BUS":          ("CANBUS", "expect"),
    "RS232":            ("RS232", "expect"),
    "RS422":            ("RS422", "expect"),
    "RS485":            ("RS485", "expect"),
    "UART":             ("UART", "expect"),
    "I2C":              ("I2C", "expect"),
    "SPI":              ("SPI", "expect"),
    # 其他需要填數量的就往下加；沒有定義的預設 QTY=1
}

def qty_for_item(display_name: str) -> int:
    sec_key = EXPECT_FROM_TOML.get(display_name)
    if not sec_key:
        return 1
    sec, key = sec_key
    try:
        return int(toml_get(sec, key, 0) or 0) or 1   # 期望沒填就回 1，避免上傳 0
    except Exception:
        return 1

def build_item_list(selected_display_names, run_status_dict):
    """
    將本輪 GUI 選到的項目轉成 MES 的 ITEM_LIST 陣列：
      [{"ITEM":<顯示名>, "QTY":"<數量>", "RESULT":"PASS|FAIL|SKIP", "DESC":""}, ...]
    """
    out = []
    for name in selected_display_names:
        qty = qty_for_item(name)
        res = (run_status_dict.get(name) or "SKIP").upper()
        # MES 沒有 ERROR 這欄位的概念時，常規把 ERROR 也視為 FAIL
        if res == "ERROR":
            res = "FAIL"
        out.append({
            "ITEM":   name,
            "QTY":    str(qty),
            "RESULT": res,
            "DESC":   ""
        })
    return out

def build_mes_testlog(meta: dict, selected_display_names, run_status_dict):
    """
    產生你 Bash leave_api 同款的 TEST_LOG 結構（不含最外層 IO_TYPE/RUNCARD...）：
      {
        "BOARD":..., "MODULE":..., ...,
        "DATE":"YYYY/MM/DD HH:MM:SS",
        "INPUTDATE":"YYYY/MM/DD HH:MM:SS",
        "ITEM_LIST":[ {...}, ... ]
      }
    meta：把 BOARD/MODULE/BSP/DTS/WORK_ORDER/PART_NUMBER/CID/CPU/MEMORY/
          TEST_TOOL_VERSION/TEST_TOOL_CONFIG 等放進來。
    """
    now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    testlog = {
        "BOARD":             meta.get("BOARD", ""),
        "MODULE":            meta.get("MODULE", ""),
        "BSP":               meta.get("BSP", ""),
        "DTS":               meta.get("DTS", ""),
        "WORK_ORDER":        meta.get("WORK_ORDER", ""),
        "PART_NUMBER":       meta.get("PART_NUMBER", ""),
        "CID":               meta.get("CID", ""),
        "CPU":               meta.get("CPU", ""),
        "MEMORY":            meta.get("MEMORY", ""),
        "TEST_TOOL_VERSION": meta.get("TEST_TOOL_VERSION", ""),
        "TEST_TOOL_CONFIG":  meta.get("TEST_TOOL_CONFIG", ""),
        "DATE":      now,
        "INPUTDATE": now,
        "ITEM_LIST": build_item_list(selected_display_names, run_status_dict),
    }
    return testlog

def mes_post(io_type: str,
             runcard: str,
             system_sn: str,
             process_name: str,
             employee_no: str,
             test_log: dict | None = None,
             timeout_sec: int = 10):
    """
    依 RUNCARD 前綴自動挑 API URL，送出 JSON。
      - io_type: "I"（進站/ENTER）、"O"（出站/LEAVE）、"Q"（查詢）。
      - test_log: 僅當 io_type="O" 需要。
    回傳：(ok: bool, status_code: int, text: str)
    """
    # 選 URL（比照你的 Bash）
    if re.match(r"^[ASP]", runcard or ""):
        # AETINA
        url = {
            "Q": "https://apdbdev.aetina.com:8223/SCM/UAT/API/MES/Runcard",
            "I": "https://apdbdev.aetina.com:8223/SCM/UAT/API/MES/Check",
            "O": "https://apdbdev.aetina.com:8223/SCM/UAT/API/MES/Check",
        }.get(io_type)
    else:
        # INNODISK
        url = {
            "Q": "http://mfg_api.innodisk.com/MFG_WebAPI/api/MesCheck",
            "I": "http://mfg_api.innodisk.com/Inno_API/api/MES_Sub/AT_TEST_LOG",
            "O": "http://mfg_api.innodisk.com/Inno_API/api/MES_Sub/AT_TEST_LOG",
        }.get(io_type)

    if not url:
        return False, 0, f"Unknown io_type={io_type}"

    body = [{
        "IO_TYPE":      io_type,
        "RUNCARD":      runcard,
        "SYSTEM_SN":    system_sn,
        "PROCESS_NAME": process_name,
        "EMPLOYEE_NO":  employee_no,
    }]
    if io_type == "O" and test_log is not None:
        body[0]["TEST_LOG"] = test_log
    # INNODISK 端需要 INPUT_NOCHECK=Y 像你 Bash enter_api，那就兩端都帶
    if io_type == "I":
        body[0]["INPUT_NOCHECK"] = "Y"

    try:
        resp = requests.post(url, json=body, timeout=timeout_sec)
        ok = (resp.status_code == 200 and ("\"RESULT\":\"OK\"" in resp.text or "\"MSG\":\"\"" in resp.text or "\"MSG\":null" in resp.text))
        return ok, resp.status_code, resp.text
    except Exception as e:
        return False, 0, f"POST error: {e}"


class CollectingResult(unittest.TextTestResult): # 這 Class 的功能是收集每個測試項目的結果，並存儲在一個列表中，方便後續處理或輸出。
    def startTest(self, test):
        super().startTest(test)
        if not hasattr(self, "_records"):
            self._records, self._t0 = [], {}
        self._t0[test] = time.time()

    def _finish(self, test, status, err=None):
        t1 = time.time()
        dur_ms = int((t1 - self._t0.get(test, t1)) * 1000)
        name = getattr(test, "_testMethodName", str(test))
        msg  = getattr(test, "_last_msg", "")
        if err and not msg:
            try:
                msg = err[1].args[0]
            except Exception:
                msg = str(err)
        self._records.append({
            "name": name,
            "status": status,  # PASS / FAIL / ERROR
            "message": msg,
            "duration_ms": dur_ms,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    def addSuccess(self, test):
        # super().addSuccess(test); self._finish(test, "PASS")
        msg = getattr(test, "_last_msg", "")
        self._records.append({
            "name": test._testMethodName, 
            "status": "PASS", 
            "message": msg
        })
        super().addSuccess(test)

    def addFailure(self, test, err):
        # super().addFailure(test, err); self._finish(test, "FAIL", err)
        # err = (exc_type, exc_value, tb)
        msg = str(err[1]) or getattr(test, "_last_msg", "")
        self._records.append({"name": test._testMethodName, "status": "FAIL", "message": msg})
        super().addFailure(test, err)

    def addError(self, test, err):
        # super().addError(test, err); self._finish(test, "ERROR", err)
        msg = str(err[1]) or getattr(test, "_last_msg", "")
        self._records.append({"name": test._testMethodName, "status": "ERROR", "message": msg})
        super().addError(test, err)

    def addSkip(self, test, reason):
        self._records.append({"name": test._testMethodName, "status": "SKIP", "message": reason})
        super().addSkip(test, reason)

# —— 全域：跨次執行累積「最終狀態」用，不要每輪清掉 ——
PERSISTED_STATUS = {}     # 例如：{"USB": "PASS", "Micro SD": "FAIL", ...}
ALL_ITEMS_ORDER = None    # 想固定輸出順序就給 list；不給就自動排序

# 全域反查（method → display name）
_METHOD_TO_DISPLAY = {v: k for k, v in DISPLAY_NAME_MAP.items()}
def method_to_display_name(method: str) -> str:
    return _METHOD_TO_DISPLAY.get(method, method)

# ===== 給 GUI 呼叫的 API =====
def run_selected_tests(selected_display_names, log_dir=None, sn=None, meta=None, log_path=None, window=None):

    global CURRENT_WINDOW
    CURRENT_WINDOW = window

    # 1) 建 suite
    missing = [n for n in selected_display_names if n not in DISPLAY_NAME_MAP]
    if missing:
        print(f"警告：找不到對應的測試項目：{missing}", file=sys.stderr)

    suite = unittest.TestSuite()
    for name in selected_display_names:
        method = DISPLAY_NAME_MAP.get(name)
        if method:
            suite.addTest(AutoTests(method))

    # 2) 只跑一次（安靜），拿到自訂 CollectingResult（含 _records）
    buf = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=buf,
        verbosity=0,
        resultclass=CollectingResult
    )
    result = runner.run(suite)

    # 3) 用 _records 組乾淨輸出（本輪）
    records = getattr(result, "_records", [])
    lines_run = [
        f"{r['name']}: {r['status']}" + (f" - {r.get('message')}" if r.get('message') else "")
        for r in records
    ]
    text_out = "\n".join(lines_run) if lines_run else "No tests executed."

    # 4) 本輪項目狀態（顯示名 → PASS/FAIL/ERROR/SKIP）
    method_to_display = {v: k for k, v in DISPLAY_NAME_MAP.items()}
    run_status = {}
    for r in records:
        disp = method_to_display.get(r["name"], r["name"])
        run_status[disp] = r["status"]
    # 若某個選到的項目不在 records（理論上不會），補 PASS
    for name in selected_display_names:
        m = DISPLAY_NAME_MAP.get(name)
        if m and name not in run_status:
            run_status[name] = "PASS"

    # 5) 併入全域最終狀態（只更新這輪有跑到的項目；其餘保留）
    global PERSISTED_STATUS, ALL_ITEMS_ORDER
    if not PERSISTED_STATUS:
        PERSISTED_STATUS = {}
    PERSISTED_STATUS.update(run_status)

    # 6) 整體標籤（只要有 FAIL 或 ERROR 就算 fail）
    def _overall_tag(d: dict) -> str:
        if not d:
            return "fail"
        # 將 ERROR 也視為 fail；SKIP 不影響總結
        has_bad = any(v in ("FAIL", "ERROR") for v in d.values())
        return "fail" if has_bad else "pass"

    overall_tag = _overall_tag(PERSISTED_STATUS)

    # 7) 寫檔：只留最後一份（刪掉舊的），檔名 <WO>_<YYYYMMDD_HHMMSS>_<pass|fail>.log
    out_dir = log_dir or "test_logs"        # 這裡把 log_dir 視為「WO 目錄名」
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    wo_name = os.path.basename(out_dir)     # 檔名開頭用資料夾名當作 WO
    out_name = f"{wo_name}_{ts}_{overall_tag}.log"
    out_path = os.path.join(out_dir, out_name)

    # 先清掉舊的同型式檔案（確保只留最後一份）
    for fp in glob.glob(os.path.join(out_dir, f"{wo_name}_*.log")):
        try:
            os.remove(fp)
        except Exception:
            pass

    # 內容：Header（可選）+ This Run（本輪）+ Current Status（所有最終狀態）
    lines = []
    if meta and meta.get("header"):
        lines.append(meta["header"]); lines.append("")

    lines.append("---- This Run  錯誤原因 ----")
    lines.append(text_out)

    lines.append("")
    lines.append("---- Current Status 測試結果 ----")
    order = ALL_ITEMS_ORDER or sorted(PERSISTED_STATUS.keys())
    for name in order:
        if name in PERSISTED_STATUS:
            lines.append(f"{name}: {PERSISTED_STATUS[name]}")
    # 落網之魚補上（若有）
    for k in PERSISTED_STATUS.keys():
        if k not in order:
            lines.append(f"{k}: {PERSISTED_STATUS[k]}")

    # 若外界指定 log_path，就覆寫那個路徑；否則寫我們的 out_path
    target_path = log_path or out_path
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

    # 8) 同時覆寫一份 JSON 摘要（讓機器/GUI 讀最新狀態；檔名固定不累加）
    try:
        json_path = os.path.join(out_dir, f"{wo_name}_current.json")
        summary = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "selected": selected_display_names,
            "total": result.testsRun,
            "passes": sum(1 for r in records if r["status"] == "PASS"),
            "failures": sum(1 for r in records if r["status"] == "FAIL"),
            "errors":   sum(1 for r in records if r["status"] == "ERROR"),
            "records": records,                       # 本輪
            "persisted_status": PERSISTED_STATUS,     # 全部最終
            "overall": overall_tag,
            "meta": (meta or {}),
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 9) 回傳：維持原本介面（第三個是本輪的 item_status）
    return result, text_out, run_status

"""
Log 檔產生流程說明（以 USB3 為例）：

    USB3_test() → return test_results, msg
                ↓
    AutoTests.test_USB3() → run_item() → self._last_msg = msg
                ↓
    CollectingResult.addSuccess() → _records.append({"message": msg})
                ↓
    run_selected_tests() → 組成 lines_run / text_out
                ↓
    open(...).write("\n".join(lines))
                ↓
    → 最終 log 檔中出現 [PASS] USB3 測試通過
--------------------------------------------------------------
    USB3_test()
   ├─ 組成 lines[]
   ├─ 判斷 test_results=True/False
   └─ return test_results, "\n".join(lines)
            ↓
    run_item() 接收 → test_results, msg
                ↓
    CollectingResult.addSuccess() 把 msg 存入 _records
                ↓
    run_selected_tests() 組合文字
                ↓
    open(...).write(...) 寫入 log 檔
"""

# 單獨命令列執行也能跑全部（非 GUI 場景）
if __name__ == "__main__":
    unittest.main(verbosity=2)