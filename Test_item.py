import unittest, io, sys, os, json, subprocess, re, glob, pathlib, math, wave, struct, shutil, tempfile, requests, time, signal, os, re, platform, shlex, uuid, stat, errno
from PyQt5.QtCore import QTime, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QDialog, QCheckBox, QMessageBox
from PyQt5 import uic
from datetime import datetime
import toml
import serial
from unitest import ask_yes_no, ask_info
import logging
from pathlib import Path
import csv
import re

# ===== 給 GUI 用的全域視窗指標（CLI 情況下維持 None）=====
CURRENT_WINDOW = None

def set_current_window(win):
    """由 GUI 呼叫，告訴 Test_item 目前的 MBTestWindow。
    CLI 跑 unittest 時完全不需要理這個函式。
    """
    global CURRENT_WINDOW
    CURRENT_WINDOW = win


# ===== 取得 MAC Address =====
def get_mac_addresses():
    """
    回傳所有實體網卡的 MAC Address 清單
    格式：[(iface, MAC), ...]，只收實體介面、排除 lo / 00:00:...
    """
    macs = []
    base = "/sys/class/net/"
    try:
        for iface in sorted(os.listdir(base)):
            if iface == "lo":
                continue
            # 沒有 'device' 代表多半是 virtual（bridge/vlan），先排除
            if not os.path.exists(os.path.join(base, iface, "device")):
                continue
            addr_path = os.path.join(base, iface, "address")
            try:
                with open(addr_path) as f:
                    mac = f.read().strip().upper()
            except Exception:
                mac = ""
            if not mac or mac == "00:00:00:00:00:00":
                continue
            macs.append((iface, mac))
    except Exception:
        pass
    return macs

def format_mac_addresses_for_log(macs=None):
    """
    將 MAC Address 清單格式化為字串，用於 log 檔案
    格式：eth0: AA:BB:CC:DD:EE:FF, eth1: 11:22:33:44:55:66
    """
    if macs is None:
        macs = get_mac_addresses()
    if not macs:
        return "N/A"
    return ", ".join([f"{iface}: {mac}" for iface, mac in macs])

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

# ================= USB TESTS =================
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
        node = os.path.realpath(f"/sys/block/{dev_name}/device") # 找出 sdX 的上層 USB 節點
        for _ in range(8):
            speed_file = os.path.join(node, "speed") # 找出 sdX 的上層 USB 節點的 speed 檔
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


def _dev_head_readable(dev_path: str, read_bytes: int = 512):
    """檢查磁碟頭部是否可讀"""
    try:
        subprocess.run(
            ["dd", f"if={dev_path}", "of=/dev/null", f"bs={read_bytes}", "count=1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True, "read ok"
    except Exception as e:
        return False, f"read error: {e}"


# === USB2 測試 ===
def USB2_test():
    """
    USB2.0 測試
      - 掃描 sdX
      - 判斷速度區間（USB2）
      - 執行讀/寫驗證
      - 比對期望數量
    
    TOML：
      [USB2]
      expect = 2
      verbose = false
    """
    lines = []
    fail = False

    # === 讀 TOML section 一次搞定 ===
    cfg = toml_get("USB2", None, {}) or {}

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0

    # 是否顯示忽略的裝置
    verbose = bool(cfg.get("verbose", False))

    # === 掃描 USB 裝置 ===
    all_sdx = _list_usb_disks_sdx()
    usb_list, speeds, non_target = [], {}, []

    # 根據速度過濾 USB2 裝置（360 ≤ mbps < 800）
    for d in all_sdx:
        sp = _usb_speed_mbps_for_disk(d)
        speeds[d] = sp
        # USB2 速度範圍：360 ~ 800 Mb/s
        if isinstance(sp, (int, float)) and 360.0 <= sp < 800.0:
            usb_list.append(d)
        else:
            non_target.append((d, sp))

    lines.append(f"[USB2] 在系統上偵測到 {len(usb_list)} 個 USB2 裝置，Toml 設定 {expect} 個")

    # === 讀寫測試 ===
    bad = []
    for d in usb_list:
        dev = f"/dev/{d}"
        r_ok, _ = _dev_head_readable(dev)
        w_ok, _ = _rw_sanity_check(tmp_prefix=f"usb2_{d}_")
        mark = "PASS" if (r_ok and w_ok) else "FAIL"
        if mark == "FAIL":
            bad.append(d)
        sp = speeds.get(d)
        sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
        lines.append(f"  {d}: {sp_s} {mark}")

    # === 顯示忽略的裝置 ===
    if verbose and non_target:
        lines.append("  (忽略的非USB2裝置)")
        for d, sp in non_target:
            sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
            lines.append(f"    - {d}: {sp_s}")

    # === 數量檢查 ===
    if expect > 0 and len(usb_list) != expect:
        fail = True
        lines.append(f"[USB2][FAIL] 數量不符：系統上偵測到 {len(usb_list)} 個 / Toml 設定 {expect} 個")

    # === 讀寫失敗檢查 ===
    if bad:
        fail = True
        lines.append(f"[USB2][FAIL] 讀寫失敗：{', '.join(bad)}")

    # ===== 最後依 fail 決定 PASS / FAIL =====
    if not fail:
        lines.append("[USB2][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[USB2][FAIL] 測試未通過")
        return False, "\n".join(lines)


# === USB3 測試 ===
def USB3_test():
    """
    USB3.0 測試
      - 掃描 sdX
      - 判斷速度區間（USB3）
      - 執行讀/寫驗證
      - 比對期望數量
    
    TOML：
      [USB3]
      expect = 2
      verbose = false
    """
    lines = []
    fail = False

    # === 讀 TOML section 一次搞定 ===
    cfg = toml_get("USB3", None, {}) or {}

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0

    # 是否顯示忽略的裝置
    verbose = bool(cfg.get("verbose", False))

    # === 掃描 USB 裝置 ===
    all_sdx = _list_usb_disks_sdx()
    usb_list, speeds, non_target = [], {}, []

    # 根據速度過濾 USB3 裝置（mbps ≥ 3000）
    for d in all_sdx:
        sp = _usb_speed_mbps_for_disk(d)
        speeds[d] = sp
        # USB3 速度範圍：≥ 3000 Mb/s
        if isinstance(sp, (int, float)) and sp >= 3000.0:
            usb_list.append(d)
        else:
            non_target.append((d, sp))

    lines.append(f"[USB3] 系統上偵測到 {len(usb_list)} 個 USB3 裝置，Toml 設定 {expect} 個")

    # === 讀寫測試 ===
    bad = []
    for d in usb_list:
        dev = f"/dev/{d}"
        r_ok, _ = _dev_head_readable(dev)
        w_ok, _ = _rw_sanity_check(tmp_prefix=f"usb3_{d}_")
        mark = "PASS" if (r_ok and w_ok) else "FAIL"
        if mark == "FAIL":
            bad.append(d)
        sp = speeds.get(d)
        sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
        lines.append(f"  {d}: {sp_s} {mark}")

    # === 顯示忽略的裝置 ===
    if verbose and non_target:
        lines.append("  (忽略的非USB3裝置)")
        for d, sp in non_target:
            sp_s = f"{int(sp)}Mb/s" if isinstance(sp, (int, float)) else "N/A"
            lines.append(f"    - {d}: {sp_s}")

    # === 數量檢查 ===
    if expect > 0 and len(usb_list) != expect:
        fail = True
        lines.append(f"[USB3][FAIL] 數量不符：系統上偵測到 {len(usb_list)} 個 / Toml 設定 {expect} 個")

    # === 讀寫失敗檢查 ===
    if bad:
        fail = True
        lines.append(f"[USB3][FAIL] 讀寫失敗：{', '.join(bad)}")

    # ===== 最後依 fail 決定 PASS / FAIL =====
    if not fail:
        lines.append("[USB3][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[USB3][FAIL] 測試未通過")
        return False, "\n".join(lines)
# ================= USB TESTS =================

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
    # devs = sorted(glob.glob("/dev/nvme*n*"))
    # 只匹配 namespace，排除分割區
    # devs = sorted([d for d in glob.glob("/dev/nvme*n*") if re.match(r"/dev/nvme\d+n\d+$", d)])

    # 只匹配控制器：/dev/nvme0, /dev/nvme1, ...
    devs = sorted([d for d in glob.glob("/dev/nvme*") if re.match(r"/dev/nvme\d+$", d)])
    
    lines.append(f"[M-Key] 系統上偵測到 {len(devs)} 個 NVMe 裝置，Toml 設定 {expect} 個")

    # === 數量檢查 ===
    if expect > 0 and len(devs) != expect:
        fail = True
        lines.append(f"[M-Key][FAIL] 數量不符：系統上偵測到 {len(devs)} 個 / Toml 設定 {expect} 個")

    # === must_exist 檢查 ===
    for req in must_exist:
        if req not in devs:
            fail = True
            lines.append(f"[M-Key][FAIL] 缺少必要裝置：{req}")

    # === 逐一數量檢查 ===
    if read_check:
        if not devs:
            lines.append("[M-Key][FAIL] 無 NVMe 裝置")
            fail = True
        # else:
        #     lines.append(f"[M-Key] 開始讀取測試（前 {read_bytes} bytes）")

        # for d in devs:
        #     cmd = f"dd if={shlex.quote(d)} of=/dev/null bs={read_bytes} count=1 status=none"
        #     try:
        #         p = subprocess.run(
        #             ["bash", "-lc", cmd],
        #             stdout=subprocess.PIPE,
        #             stderr=subprocess.PIPE,
        #             text=True, timeout=3
        #         )
        #         if p.returncode == 0:
        #             lines.append(f"[M-Key] 讀取 OK：{d}")
        #         else:
        #             fail = True
        #             err = (p.stderr or p.stdout or "").strip()
        #             lines.append(f"[M-Key][FAIL] 讀取失敗：{d}（{err}）")
        #     except Exception as e:
        #         fail = True
        #         lines.append(f"[M-Key][FAIL] 讀取異常：{d} ({e})")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[M-Key][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[M-Key][FAIL] 測試未通過")
        return False, "\n".join(lines)
    
# ================= M.2 KEY M TEST =================

# ================= M.2 KEY B TEST =================
def BKEY_test():
    """
    B-Key 測試
    - 讀取 [B-Key]/[B_KEY] 的:
        * expect: 期望路徑數（必須 > 0）
        * BKEY_PATH_1..N: 逐一列出的資料夾路徑
    - 驗證流程：
        1) expect 必須 > 0
        2) 取出所有非空的 BKEY_PATH_#（去前後空白、去重、保序）
        3) 路徑數量必須 == expect
        4) 逐一路徑用 os.path.isdir() 檢查（第一個不存在即 FAIL）
    - 回傳：(ok: bool, msg: str)
    """
    lines = []
    fail = False

    # === 讀 TOML 區塊 ===
    cfg = toml_get("B-KEY", None, {}) or {}  # 讀整個區塊

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0
    
    lines.append(f"[B-Key] 期望路徑數: {expect}")

    if expect <= 0:
        lines.append("[B-Key][FAIL] expect 必須大於 0")
        return False, "\n".join(lines)
    
    # === 收集路徑清單 ===
    paths = []
    seen = set()
    MAX_SLOTS = 100 # 最大支援 100 個路徑設定, 避免無限迴圈, 未來有增加需求再從這裡改

    for i in range(1, MAX_SLOTS + 1):
        key_name = f"BKEY_PATH_{i}"
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
        
    lines.append(f"[B-Key] 路徑清單 = {paths if paths else '（未設定）'}")

    # === 數量檢查 ===
    if len(paths) != expect:
        fail = True
        lines.append(f"[B-Key][FAIL] 路徑數量不符：系統上偵測到 {len(paths)} 個路徑，Toml 設定 {expect} 個")

    # === 逐一路徑檢查 ===
    for p in paths:
        if not os.path.isdir(p):
            fail = True
            lines.append(f"[B-Key][FAIL] 路徑不存在或無法訪問：{p}")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[B-Key][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[B-Key][FAIL] 測試未通過")
        return False, "\n".join(lines)
    
# ================= M.2 KEY B TEST =================


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
    fail = False

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
        fail = True
        lines.append(f"[E-Key][FAIL] 路徑數量不符：系統上偵測到 {len(paths)} 個路徑，Toml 設定 {expect} 個")

    # === 逐一路徑檢查 ===
    for p in paths:
        if not os.path.isdir(p):
            fail = True
            lines.append(f"[E-Key][FAIL] 路徑不存在或無法訪問：{p}")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[E-Key][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[E-Key][FAIL] 測試未通過")
        return False, "\n".join(lines)


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
    
    # === 白名單方式：只包含符合有線網卡命名規則的介面 ===
    # 預設的有線網卡前綴（可透過設定檔覆蓋）
    default_include_prefix = ("eth", "enp", "ens", "eno")
    
    # 從設定檔讀取自訂的介面前綴（可選）
    # 例如: interfaces = ["eth", "enp"] 或 interfaces = ["eth0", "eth1"]（精確指定）
    custom_interfaces = toml_get("Network", "interfaces", None)
    
    ports = []
    for name in os.listdir(base):
        iface_path = os.path.join(base, name)
        
        # 必須有 device 資料夾（實體介面）
        if not os.path.exists(os.path.join(iface_path, "device")):
            continue
        
        # 排除光纖介面，只留「非 fiber」當 LAN 測
        if _is_fiber_interface(iface_path):
            continue
        
        # 使用白名單過濾
        if custom_interfaces:
            # 設定檔有指定：支援精確匹配或前綴匹配
            if isinstance(custom_interfaces, list):
                match = any(name == iface or name.startswith(iface) for iface in custom_interfaces)
            else:
                # 單一字串
                match = name == custom_interfaces or name.startswith(custom_interfaces)
        else:
            # 使用預設白名單（前綴匹配）
            match = name.startswith(default_include_prefix)
        
        if match:
            ports.append(name)

    lines = [f"[LAN] 偵測到介面：{ports}"]
    actual_count = len(ports)

    # === 數量比對 ===
    if expect_count > 0:
        lines.append(f"[LAN] Toml 設定數量: {expect_count} 個，系統上偵測到 {actual_count} 個介面")
        if actual_count != expect_count:
            lines.append(f"[LAN][FAIL] 數量不符：系統上偵測到 {actual_count} 個介面，Toml 設定 {expect_count} 個")
            return False, "\n".join(lines)
    else:
        lines.append("[LAN][WARN] 未在 config 中設定 Network.expect，略過數量比對")

    if not ports:
        return False, "[LAN][FAIL] 沒有找到任何實體網卡"

    fail_ports = []
    fail = False

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
        fail = True
        lines.append(f"[LAN][FAIL] 以下介面未連線或測試失敗：{', '.join(fail_ports)}")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[LAN][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[LAN][FAIL] 測試未通過")
        return False, "\n".join(lines)
# ================= NETWORK TESTS =================

# ================= OPTICAL FIBER TESTS =================
def _is_fiber_interface(iface_path):
    """
    檢查接口是否為光纖接口
    判斷方式：檢查 /sys/class/net/<iface>/device/ 下是否有光功率相關檔案
    """
    device_path = os.path.join(iface_path, "device")
    if not os.path.exists(device_path):
        return False

    try:
        for root, dirs, files in os.walk(device_path):
            for f in files:
                name = f.lower()
                # 把泛用的 "power" 拿掉，只留比較專一的關鍵字
                if any(k in name for k in ["rx_power", "tx_power", "optical", "sfp", "qsfp"]):
                    return True
    except Exception:
        pass

    return False

def _get_gateway_for_iface(iface: str) -> str:
    """
    取得指定接口的預設 gateway
    使用 ip route show dev <iface> | grep default 來取得
    """
    try:
        result = subprocess.run(
            ["ip", "route", "show", "dev", iface],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "default" in line:
                # 格式：default via 192.168.1.1 dev eth0 ...
                parts = line.split()
                if "via" in parts:
                    idx = parts.index("via")
                    if idx + 1 < len(parts):
                        return parts[idx + 1]
    except Exception:
        pass
    return ""


def FIBER_test():
    """
    光纖測試：
      - 自動掃描光纖接口，或讀取 TOML 配置中指定的光纖接口
      - 檢查實際數量是否符合 config 設定的 expect
      - 每個 port 都必須 link (carrier=1)
      - 檢查光纖訊號強度（如果支援，僅作為提醒，不影響 pass/fail）
      - 每個 port 都必須能 ping 通該接口的 gateway
      - 若數量不符、未連線或 ping 失敗 → FAIL
    """
    # 讀取 TOML 配置
    cfg = toml_get("OPTICAL FIBER", None, {}) or {}
    
    expect_count = int(cfg.get("expect", 0))  # 預設 0（不檢查數量）
    
    # 從 Network 配置取得 ping 相關參數
    ping_count   = int(toml_get("Network", "ping_count", 3))  # 預設 3 次（與 Bash 版一致）
    ping_timeout = int(toml_get("Network", "ping_timeout", 1))  # 預設 1 秒
    
    # 讀取要測試的光纖接口列表
    # 格式：FIBER_port_1 = "eth0", FIBER_port_2 = "eth1", ...
    # 如果沒有在配置檔中指定，則自動掃描
    ports = []
    max_n = 100
    for i in range(1, max_n + 1):
        port_key = f"FIBER_port_{i}"
        port_val = cfg.get(port_key)
        if port_val:
            ports.append(str(port_val).strip())
        else:
            break
    
    # 如果配置檔中沒有指定接口，則自動掃描光纖接口
    if not ports:
        base = "/sys/class/net"
        exclude_prefix = ("lo", "docker", "veth", "br", "tap", "tun", "wg", "can")
        for name in os.listdir(base):
            if name.startswith(exclude_prefix):
                continue
            if not os.path.exists(os.path.join(base, name, "device")):
                continue
            iface_path = os.path.join(base, name)
            if _is_fiber_interface(iface_path):
                ports.append(name)
        ports = sorted(ports)
        lines = [f"[光纖] 自動掃描到接口：{ports}"]
    else:
        lines = [f"[光纖] 設定要測試的接口：{ports}"]
    
    actual_count = len(ports)
    
    # === 數量比對 ===
    if expect_count > 0:
        lines.append(f"[光纖] Toml 設定數量: {expect_count} 個，系統上偵測到 {actual_count} 個介面")
        if actual_count != expect_count:
            lines.append(f"[光纖][FAIL] 數量不符：系統上偵測到 {actual_count} 個介面，Toml 設定 {expect_count} 個")
            return False, "\n".join(lines)
    else:
        lines.append("[光纖][WARN] 未在 Toml 中設定 FIBER.expect，略過數量比對")
    
    if not ports:
        return False, "[光纖][FAIL] 沒有找到任何光纖接口"
    
    fail_ports = []
    fail = False
    base = "/sys/class/net"
    
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
        
        # 檢查光纖訊號強度（如果支援，僅作為提醒，不影響 pass/fail）
        iface_path = os.path.join(base, iface)
        device_path = os.path.join(iface_path, "device")
        if os.path.exists(device_path):
            try:
                optical_power = None
                for root, dirs, files in os.walk(device_path):
                    for f in files:
                        if any(keyword in f.lower() for keyword in ["power", "rx_power", "optical", "tx_power"]):
                            power_file = os.path.join(root, f)
                            try:
                                with open(power_file) as pf:
                                    optical_power = pf.read().strip()
                                lines.append(f"  {iface}: [提醒] 光功率資訊 ({f}): {optical_power}")
                                break
                            except Exception:
                                pass
                    if optical_power:
                        break
            except Exception:
                pass
        
        # 取得該接口的 gateway
        gateway = _get_gateway_for_iface(iface)
        if not gateway:
            lines.append(f"  {iface}: FAIL (無法取得 gateway)")
            fail_ports.append(iface)
            continue
        
        # ping gateway 測試
        try:
            subprocess.run(
                ["ping", "-I", iface, "-c", str(ping_count), "-W", str(ping_timeout), gateway],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            lines.append(f"  {iface}: PASS (linked, ping gateway {gateway} 成功)")
        except subprocess.CalledProcessError:
            lines.append(f"  {iface}: FAIL (ping gateway {gateway} 失敗)")
            fail_ports.append(iface)
        except Exception as e:
            lines.append(f"  {iface}: ERROR ({e})")
            fail_ports.append(iface)
    
    # === 結果判斷 ===
    if fail_ports:
        fail = True
        lines.append(f"[光纖][FAIL] 以下接口未連線或測試失敗：{', '.join(fail_ports)}")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[光纖][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[光纖][FAIL] 測試未通過")
        return False, "\n".join(lines)
# ================= OPTICAL FIBER TESTS =================

# ================= EEPROM TEST =================
def EEPROM_test():
    """
    EEPROM 最終寫入測試：
      1. RD 模式 => 直接略過
      2. 檢查是否所有必要測項都 PASS（不含 EEPROM FUNCTION / EEPROM FINAL）
      3. 從 [EEPROM] 讀取 I2C bus / addr / GPIO / PN / 板號 / 版號
      4. 讀取 DTS 名稱、SoC Serial Number
      5. 呼叫 aetina-eeprom-tool.py gen 產生 eeprom.bin
      6. 呼叫 flash 寫入 EEPROM
      7. 呼叫 dump / verify 驗證內容一致
      8. GPIO 拉 HIGH 開始寫入，最後拉 LOW 並 unexport
    """

    lines = []
    fail = False

    # ===== 基本環境變數 =====
    system_sn = os.environ.get("SYSTEM_SN", "").strip() or  "UNKNOWN_SN"
    mode = os.environ.get("MODE", "RD").strip().upper()
    bsp = os.environ.get("BSP", "").strip()

    eeprom_trace_log = f"{system_sn}_trace.log"

    # --- 小工具：寫 log（同時記在 lines 方便回傳） ---
    def log(msg: str):
        lines.append(msg)
        try:
            with open(eeprom_trace_log, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            # trace.log 寫失敗不要讓測項中斷, 只記錄在 lines 方便回傳錯誤訊息
            pass
    
    # ===== 檢查 RD 模式，跳過 EEPROM 最終寫入 =====
    if mode == "RD":
        log(f"[INFO] 模式為 RD，跳過 EEPROM 最終寫入")
        lines.append("[SKIP] 模式為 RD，跳過 EEPROM 最終寫入")
        return "SKIP", "\n".join(lines)  # 回傳 "SKIP" 而不是 True，表示跳過而非通過

    # ===== 檢查是否所有測試項目都通過（排除 EEPROM 相關項目）=====
    def is_all_test_items_pass():
        """檢查這次被勾選的測試項目是否都通過，排除 EEPROM 相關項目"""
        skip_items = ["EEPROM", "EEPROM (RD Test)"]  # 排除的項目
        global PERSISTED_STATUS, SELECTED_ITEMS_THIS_RUN
        
        if not PERSISTED_STATUS:
            log("[DEBUG] PERSISTED_STATUS 為空，無法檢查所有測試項目狀態")
            return False
        
        # 如果沒有被選中的項目，視為通過（避免誤判）
        if not SELECTED_ITEMS_THIS_RUN:
            log("[DEBUG] 沒有被勾選的測試項目，視為通過")
            return True
        
        all_pass = True
        # 只檢查這次被勾選的項目
        for item_name in SELECTED_ITEMS_THIS_RUN:
            # 跳過 EEPROM 相關項目
            if any(skip in item_name for skip in skip_items):
                log(f"[DEBUG] 測項 {item_name} 狀態: (已排除，不檢查)")
                continue
            
            # 取得該項目的狀態
            status = PERSISTED_STATUS.get(item_name)
            if status is None:
                log(f"[DEBUG] 測項 {item_name} 尚未執行，視為未通過")
                all_pass = False
                continue
            
            log(f"[DEBUG] 測項 {item_name} 狀態: {status}")
            
            if status not in ("PASS", "pass"):
                log(f"[DEBUG] 測項 {item_name} 不通過，被判定為 fail")
                all_pass = False
        
        return all_pass

    # 檢查這次被勾選的測試項目是否都通過
    if not is_all_test_items_pass():
        log("[SKIP] 被勾選的測項尚未全部通過（不含 EEPROM 測項），跳過寫入")
        log("[DEBUG] 被勾選的測項狀態總覽：")
        global PERSISTED_STATUS, SELECTED_ITEMS_THIS_RUN
        if SELECTED_ITEMS_THIS_RUN:
            for item_name in sorted(SELECTED_ITEMS_THIS_RUN):
                # 跳過 EEPROM 相關項目
                if any(skip in item_name for skip in ["EEPROM", "EEPROM (RD Test)"]):
                    continue
                status = PERSISTED_STATUS.get(item_name, "未執行")
                log(f"  {item_name}: {status}")
        else:
            log("  沒有被勾選的測試項目")
        fail = True
        lines.append("Fail: 被勾選的測項未全部通過，未執行 EEPROM 寫入")
        return False, "\n".join(lines)

    # ===== 讀取 [EEPROM] 的 I2C bus / addr / GPIO / PN / 板號 / 版號 =====
    # 原則：EEPROM 最終寫入必須「由 TOML 提供完整參數」，不要用預設值偷偷補上避免誤寫。
    expect = int(toml_get("EEPROM", "expect", 0) or 0)
    if expect <= 0:
        log("[SKIP] [EEPROM].expect <= 0，略過 EEPROM FINAL WRITE")
        lines.append("[SKIP] [EEPROM].expect <= 0，略過 EEPROM FINAL WRITE")
        return "SKIP", "\n".join(lines)

    i2c_bus_raw         = toml_get("EEPROM", "eeprom_i2c_bus", None)
    i2c_addr_raw        = toml_get("EEPROM", "eeprom_i2c_addr", None)
    gpio_num_raw        = toml_get("EEPROM", "eeprom_gpio_write_num", None)
    gpio_pin_raw        = toml_get("EEPROM", "eeprom_gpio_write_pin", None)
    pn_raw              = toml_get("EEPROM", "pn", None)
    board_name_raw      = toml_get("EEPROM", "board_name", None)
    board_revision_raw  = toml_get("EEPROM", "board_revision", None)

    # 檢查必要欄位（缺一就 FAIL，避免用錯預設值去寫 EEPROM）
    missing = []
    if i2c_bus_raw in (None, ""): missing.append("eeprom_i2c_bus")
    if i2c_addr_raw in (None, ""): missing.append("eeprom_i2c_addr")
    if gpio_num_raw in (None, ""): missing.append("eeprom_gpio_write_num")
    if gpio_pin_raw in (None, ""): missing.append("eeprom_gpio_write_pin")
    if pn_raw in (None, ""): missing.append("pn")
    if board_name_raw in (None, ""): missing.append("board_name")
    if board_revision_raw in (None, ""): missing.append("board_revision")
    if missing:
        msg = "[FAIL] [EEPROM] 未設定必要欄位：" + ", ".join(missing)
        log(msg)
        return False, "\n".join(lines + [msg])

    # 轉換格式（與 EEPROM_RD_test 相容：bus/gpio_num 支援 '0x..' 字串）
    try:
        i2c_bus = str(int(i2c_bus_raw, 0)) if isinstance(i2c_bus_raw, str) else str(int(i2c_bus_raw))
        # i2c_addr 保留原始格式（可能是 "0x55" 或 85），aetina-eeprom-tool 以字串收參數即可
        if isinstance(i2c_addr_raw, str):
            i2c_addr = i2c_addr_raw.strip()
        else:
            i2c_addr = str(i2c_addr_raw)
        gpio_num = int(gpio_num_raw, 0) if isinstance(gpio_num_raw, str) else int(gpio_num_raw)
        gpio_pin = str(gpio_pin_raw).strip()
        pn = str(pn_raw).strip()
        board_name = str(board_name_raw).strip()
        board_revision = str(board_revision_raw).strip()
    except Exception as e:
        msg = f"[FAIL] [EEPROM] 設定值格式錯誤: {e}"
        log(msg)
        return False, "\n".join(lines + [msg])

    # ===== GPIO 相關路徑 =====
    # 為了避免使用者在 TOML 填入 "PEE.06" 這類非 sysfs 目錄名而導致找不到路徑，
    # 這裡「實際操作 sysfs」一律使用 gpio_num 對應的 /sys/class/gpio/gpio{N}。
    # gpio_pin 僅作為顯示/記錄用途（除非它本身就是 gpio345 這種 sysfs 名稱）。
    use_pin_dir = bool(re.match(r"^gpio\d+$", gpio_pin or "", re.I)) # 這裡是判斷 gpio_pin 是否為 sysfs 目錄名, 例如 True
    gpio_dir = Path("/sys/class/gpio") / (gpio_pin if use_pin_dir else f"gpio{gpio_num}") # 這裡是 GPIO 路徑, 例如 /sys/class/gpio/gpio345
    gpio_value = gpio_dir / "value" # 這裡是 GPIO 值路徑, 例如 /sys/class/gpio/PEE.06/value
    gpio_direction = gpio_dir / "direction" # 這裡是 GPIO 方向路徑, 例如 /sys/class/gpio/PEE.06/direction
    export_path = Path("/sys/class/gpio/export") # 這裡是 GPIO 匯出路徑, 例如 /sys/class/gpio/export
    unexport_path = Path("/sys/class/gpio/unexport") # 這裡是 GPIO 取消匯出路徑, 例如 /sys/class/gpio/unexport

    def gpio_release():
        """把 GPIO 拉 LOW 並 unexport，失敗只記 log 不中斷"""
        try:
            if gpio_value.exists():
                try:
                    gpio_value.write_text("0")
                except Exception as e:
                    log(f"[GPIO] 設定 LOW 失敗: {e}") # log 到 trace.log
            if gpio_num and unexport_path.exists():
                try:
                    # gpio_num 在上方已轉成 int，直接寫即可
                    unexport_path.write_text(str(gpio_num))
                except Exception as e:
                    log(f"[GPIO] unexport 失敗: {e}")
        except Exception as e:
            log(f"[GPIO] 釋放 GPIO 發生例外: {e}")

    # ===== GPIO 拉 HIGH 允許寫入 =====
    try:
        if not gpio_dir.exists():
            log(f"{time.strftime('[%Y-%m-%d %H:%M:%S]')} ===== GPIO拉HIGH 開始 =====")
            log(f"[GPIO] 匯出 GPIO: {gpio_num}")
            if export_path.exists():
                export_path.write_text(str(gpio_num))
                # 等待 sysfs 節點出現（避免 export 後 race）
                for _ in range(20):
                    if gpio_dir.exists():
                        break
                    time.sleep(0.05)
            else:
                log(f"[GPIO] export 失敗: {export_path} 不存在")
                fail = True
                return False, "\n".join(lines)

            log(f"[GPIO] 設定 GPIO 為輸出模式: {gpio_direction}")
            gpio_direction.write_text("out")
            gpio_value.write_text("1")  # 初始設定為 HIGH
        
        # 確保每次都拉 HIGH
        gpio_value.write_text("1")
        
        # 檢查 GPIO 狀態，確保 GPIO 已經拉高
        if gpio_value.exists():
            try:
                gpio_state = gpio_value.read_text().strip()
                log(f"[GPIO] 已拉 HIGH (value={gpio_state})")
            except Exception as e:
                log(f"[GPIO] 無法讀取 GPIO 狀態: {e}")

    except Exception as e:
        log(f"[GPIO] 拉 HIGH 失敗: {e}")
        fail = True
        return False, "\n".join(lines)

    # ===== 取得 BSP 名稱（與 Shell 版本相同：優先使用環境變數 BSP）=====
    # Shell 版本邏輯：BSP=${DTS:0:-4}（去掉最後4個字元 ".dts"）
    # 優先使用環境變數 BSP，如果不存在則從 DTS 檔案名稱推導
    bsp_for_gen = bsp  # 先使用環境變數 BSP
    if not bsp_for_gen:
        # 如果環境變數 BSP 不存在，從 DTS 檔案名稱推導（與 Shell 版本相同）
        dts_filename = Path("/proc/device-tree/nvidia,dtsfilename")
        if dts_filename.exists():
            try:
                # 讀取檔案並移除 null 字元（與 Shell 的 tr -d '\0' 相同）
                dts_name = dts_filename.read_bytes().decode("ascii", errors="ignore").strip("\x00")
                # 去掉最後4個字元 ".dts"（與 Shell 的 BSP=${DTS:0:-4} 相同）
                bsp_for_gen = dts_name[:-4] if dts_name.endswith(".dts") else dts_name
                log(f"[DTS] 從檔案讀取 DTS 名稱並推導 BSP: {dts_name} -> {bsp_for_gen}")
            except Exception as e:
                log(f"[DTS] 取得 DTS 名稱失敗: {e}")
                fail = True
                gpio_release()
                return False, "\n".join(lines)
        else:
            fail = True
            log("[DTS] 無法取得 DTS 名稱：環境變數 BSP 未設定且 /proc/device-tree/nvidia,dtsfilename 不存在")
            gpio_release()
            return False, "\n".join(lines)
    else:
        log(f"[BSP] 使用環境變數 BSP: {bsp_for_gen}")

    # ===== 取得 SoC Serial Number =====
    soc_sn_path = Path("/sys/firmware/devicetree/base/serial-number") # 這裡是 SoC Serial Number 路徑, 例如 /sys/firmware/devicetree/base/serial-number
    if soc_sn_path.exists():
        try:
            soc_sn = soc_sn_path.read_bytes().decode("ascii", errors="ignore").strip("\x00") # 這裡是 SoC Serial Number, 例如 1234567890
        except Exception as e:
            soc_sn = ""
            log(f"[WARN] 讀取 SoC Serial Number 失敗: {e}")
    else:
        soc_sn = ""

    # ===== 產生 EEPROM binary =====
    log("=== EEPROM GEN 開始 ===")
    log(f"[GEN][{time.strftime('%F %T')}] serial-num={system_sn} part-num={pn} soc-serial={soc_sn} board-name={board_name} rev={board_revision} dts={bsp_for_gen}")
    log(f"serial-num      : {system_sn}") # 這裡是 System Serial Number, 例如 1234567890
    log(f"part-num        : {pn}") # 這裡是 PN, 例如 92-CExxxx-xxxx
    log(f"soc-serial-num  : {soc_sn}") # 這裡是 SoC Serial Number, 例如 1234567890
    log(f"board-name(Board name)      : {board_name}") # 這裡是 板號, 例如 AX720
    log(f"board-revision(Board ver)  : {board_revision}") # 這裡是 版號, 例如 AIB-MX01-MX02-A2
    log(f"bsp-dts-name    : {bsp_for_gen}")
    log("output          : eeprom.bin") # 這裡是 輸出檔案, 例如 eeprom.bin

    tool = Path("aetina-eeprom-tool.py")

    def run_cmd(cmd_list, desc):
        """執行外部指令，stdout/stderr 全部寫入 trace.log，回傳 bool"""
        log(f"[CMD] {desc}: {' '.join(cmd_list)}")
        try:
            result = subprocess.run(
                cmd_list,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.stdout:
                for line in result.stdout.splitlines():
                    log("  " + line)
            return True
        except subprocess.CalledProcessError as e:
            log(f"[ERROR] {desc} 失敗，returncode={e.returncode}")
            if e.stdout:
                for line in e.stdout.splitlines():
                    log("  " + line)
            return False
        except Exception as e:
            log(f"[ERROR] {desc} 執行例外: {e}")
            return False

    # --- gen ---
    ok = run_cmd(
        [
            "python3",
            tool,
            "gen",
            "--serial-num", system_sn,
            "--part-num", pn,
            "--soc-serial-num", soc_sn,
            "--board-name", board_name,
            "--board-revision", board_revision,
            "--bsp-dts-name", bsp_for_gen,
            "--out-file", "eeprom.bin",
        ],
        "EEPROM gen",
    )
    if not ok:
        fail = True
        log("[ERROR] EEPROM gen 失敗")
        gpio_release()
        return (not fail), "\n".join(lines)

    # ===== 寫入 EEPROM =====
    log(f"[FLASH] 開始將 eeprom.bin 寫入 EEPROM (bus={i2c_bus}, addr={i2c_addr})")
    ok = run_cmd(
        [
            "python3",
            tool,
            "flash",
            "-b", "eeprom.bin",
            "-c", str(i2c_bus),
            "-a", str(i2c_addr),
        ],
        "EEPROM flash",
    )
    if not ok:
        fail = True
        log("[ERROR] EEPROM flash 失敗")
        gpio_release()
        return (not fail), "\n".join(lines)

    # ===== 驗證 / DUMP =====
    log("[VERIFY] 驗證 EEPROM 內容與 eeprom.bin 是否一致")
    
    # Dump EEPROM 內容到 log
    log("[DUMP] Dump EEPROM 內容如下：")
    run_cmd(
        [
            "python3",
            tool,
            "dump",
            "-c", str(i2c_bus),
            "-a", str(i2c_addr),
        ],
        "EEPROM dump",
    )

    # 驗證 Verify EEPROM 內容是否與 eeprom.bin 一致
    log("[VERIFY] 開始比對 EEPROM 與 eeprom.bin 是否一致")
    ok = run_cmd(
        [
            "python3",
            tool,
            "verify",
            "-b", "eeprom.bin",
            "-c", str(i2c_bus),
            "-a", str(i2c_addr),
        ],
        "EEPROM verify",
    )
    if not ok:
        fail = True
        log("[ERROR] EEPROM verify 失敗，檔案內容不一致")
        gpio_release()
        return (not fail), "\n".join(lines)

    # ===== GPIO 收尾 =====
    log("[GPIO] 寫入完成，GPIO 拉為 LOW 並釋放 GPIO")
    
    # 先拉 LOW
    try:
        if gpio_value.exists():
            gpio_value.write_text("0")
            # 檢查 GPIO 狀態，確保 GPIO 已經拉低
            try:
                gpio_state = gpio_value.read_text().strip()
                if gpio_state == "0":
                    log("[GPIO] 已成功拉 LOW (value=0)")
                else:
                    log(f"[GPIO] 設定 LOW 失敗，當前值為 {gpio_state}")
            except Exception as e:
                log(f"[GPIO] 無法讀取 GPIO 值: {e}")
        else:
            log(f"[GPIO] 無法讀取 GPIO 值，{gpio_value} 不存在")
    except Exception as e:
        log(f"[GPIO] 拉 LOW 失敗: {e}")
    
    # 釋放 GPIO
    try:
        if gpio_num and unexport_path.exists():
            log(f"[GPIO] 釋放 GPIO: {gpio_num}")
            unexport_path.write_text(str(gpio_num))
    except Exception as e:
        log(f"[GPIO] unexport 失敗: {e}")

    if not fail:
        log("[PASS] EEPROM_FINAL_WRITE 測試通過")

    return (not fail), "\n".join(lines)

# ================ EEPROM TEST =================

# ================ EEPROM RD TEST =================
def EEPROM_RD_test():
    """
    EEPROM 功能檢查測試（EEPROM RD TEST）：
      1. 從 [EEPROM] 讀取 I2C bus / addr / GPIO（與 EEPROM_test() 共用同一個 TOML 配置）
      2. 匯出 GPIO（如果尚未匯出）
      3. 設定 GPIO 為輸出模式並拉 HIGH
      4. 檢查 GPIO 是否成功拉 HIGH
      5. 測試 EEPROM 是否可以寫入並讀回驗證（使用 i2cset 寫入 0x00 地址為 0x42，再用 i2cget 讀回確認）
      6. 釋放 GPIO（拉 LOW 並 unexport）
    
    回傳：(ok: bool, msg: str)
    """
    lines = []
    fail = False

    # ===== 基本環境變數 =====
    system_sn = os.environ.get("SYSTEM_SN", "").strip() or "UNKNOWN_SN"
    mode = os.environ.get("MODE", "RD").strip().upper()
    eeprom_trace_log = f"{system_sn}_trace.log"

    # --- 小工具：寫 log（同時記在 lines 方便回傳） ---
    def log(msg: str):
        lines.append(msg)
        try:
            with open(eeprom_trace_log, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            # trace.log 寫失敗不要讓測項中斷, 只記錄在 lines 方便回傳錯誤訊息
            pass

    # ===== 讀取 [EEPROM] 的設定 =====
    i2c_bus = toml_get("EEPROM", "eeprom_i2c_bus", None)
    i2c_addr = toml_get("EEPROM", "eeprom_i2c_addr", None)
    gpio_num = toml_get("EEPROM", "eeprom_gpio_write_num", None)
    gpio_pin = toml_get("EEPROM", "eeprom_gpio_write_pin", None)

    # 檢查必要欄位
    if not i2c_bus or not i2c_addr or not gpio_num or not gpio_pin:
        log("[FAIL] [EEPROM] 未設定必要欄位（eeprom_i2c_bus, eeprom_i2c_addr, eeprom_gpio_write_num, eeprom_gpio_write_pin）")
        return False, "\n".join(lines)

    # 轉換格式
    try:
        i2c_bus = str(int(i2c_bus, 0)) if isinstance(i2c_bus, str) else str(int(i2c_bus))
        # i2c_addr 保留原始格式（可能是 "0x50" 或 "80"），i2cset/i2cget 都能接受
        if isinstance(i2c_addr, str):
            i2c_addr = i2c_addr.strip()
        else:
            i2c_addr = str(i2c_addr)
        gpio_num = int(gpio_num, 0) if isinstance(gpio_num, str) else int(gpio_num)
        gpio_pin = str(gpio_pin).strip()
    except Exception as e:
        log(f"[FAIL] [EEPROM] 設定值格式錯誤: {e}")
        return False, "\n".join(lines)

    # ===== GPIO 相關路徑 =====
    # 同 EEPROM_test：實際操作 sysfs 以 gpio_num 為準，避免 gpio_pin 不是 sysfs 目錄名（例如 PEE.06）時直接失敗。
    use_pin_dir = bool(re.match(r"^gpio\d+$", gpio_pin or "", re.I))
    gpio_dir = Path("/sys/class/gpio") / (gpio_pin if use_pin_dir else f"gpio{gpio_num}")
    gpio_value = gpio_dir / "value"
    gpio_direction = gpio_dir / "direction"
    export_path = Path("/sys/class/gpio/export")
    unexport_path = Path("/sys/class/gpio/unexport")

    def gpio_release():
        """把 GPIO 拉 LOW 並 unexport，失敗只記 log 不中斷"""
        try:
            if gpio_value.exists():
                try:
                    gpio_value.write_text("0")
                except Exception as e:
                    log(f"[GPIO] 拉 LOW 失敗: {e}")
            if gpio_num and unexport_path.exists():
                try:
                    # gpio_num 在上方已轉成 int，直接寫即可
                    unexport_path.write_text(str(gpio_num))
                except Exception as e:
                    log(f"[GPIO] unexport 失敗: {e}")
        except Exception as exc:
            log(f"[GPIO] 釋放 GPIO 失敗: {exc}")

    # ===== 建立 GPIO 輸出 =====
    if not gpio_dir.exists():
        log(f"{time.strftime('%Y%m%d%H%M%S')} ===== GPIO拉HIGH 開始 =====")
        log(f"[GPIO] 匯出 GPIO: {gpio_num}")
        try:
            if export_path.exists():
                export_path.write_text(str(gpio_num))
                # 等待 sysfs 節點出現（避免 export 後 race）
                for _ in range(20):
                    if gpio_dir.exists():
                        break
                    time.sleep(0.05)
            else:
                log(f"[GPIO] export 失敗: {export_path} 不存在")
                fail = True
                return False, "\n".join(lines)
        except Exception as e:
            log(f"[GPIO] export 失敗: {e}")
            fail = True
            return False, "\n".join(lines)

        log(f"[GPIO] 設定 GPIO 為輸出模式: {gpio_direction}")
        try:
            gpio_direction.write_text("out")
            gpio_value.write_text("1")  # 設定 GPIO 為高電位
        except Exception as e:
            log(f"[GPIO] 設定 GPIO 輸出模式或 HIGH 失敗: {e}")
            fail = True
            gpio_release()
            return False, "\n".join(lines)

    # 確保每次都拉 HIGH
    try:
        gpio_value.write_text("1")
    except Exception as e:
        log(f"[GPIO] 拉 HIGH 失敗: {e}")
        fail = True
        gpio_release()
        return False, "\n".join(lines)

    # ===== 檢查 GPIO 是否成功設定為高電位 =====
    if not gpio_value.exists():
        log(f"[GPIO] 無法讀取 GPIO 值，{gpio_value} 不存在")
        fail = True
        gpio_release()
        return False, "\n".join(lines)

    try:
        gpio_state = gpio_value.read_text().strip()
        if gpio_state != "1":
            log(f"[GPIO] GPIO 拉 HIGH 失敗，當前值為 {gpio_state}")
            fail = True
            gpio_release()
            return False, "\n".join(lines)
    except Exception as e:
        log(f"[GPIO] 無法讀取 GPIO 值: {e}")
        fail = True
        gpio_release()
        return False, "\n".join(lines)

    log("[GPIO] 已拉 HIGH 開始允許寫入 (value=1)")

    # ===== 測試 EEPROM 是否可以寫入並讀回驗證 =====
    log("[TEST] 嘗試以 i2cset 寫入 EEPROM 地址 0x00 為 'B' (0x42)")
    try:
        result = subprocess.run(
            ["i2cset", "-y", i2c_bus, i2c_addr, "0x00", "0x42"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=True,
        )
        log("[PASS] i2cset 寫入成功")
    except FileNotFoundError:
        log("[ERROR] 找不到 i2cset 指令，請確認是否已安裝 i2c-tools")
        fail = True
        gpio_release()
        return False, "\n".join(lines)
    except subprocess.CalledProcessError as e:
        log(f"[ERROR] i2cset 寫入失敗: {e.stderr.strip()}")
        fail = True
        gpio_release()
        return False, "\n".join(lines)
    except Exception as e:
        log(f"[ERROR] i2cset 執行例外: {e}")
        fail = True
        gpio_release()
        return False, "\n".join(lines)

    # ===== 讀回驗證 =====
    log("[TEST] 嘗試以 i2cget 讀回 EEPROM 地址 0x00 驗證")
    try:
        result = subprocess.run(
            ["i2cget", "-y", i2c_bus, i2c_addr, "0x00"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=True,
        )
        read_val = result.stdout.strip()
        if read_val == "0x42":
            log(f"[PASS] i2cget 讀回成功，值為 {read_val}，與寫入值一致")
        else:
            log(f"[FAIL] i2cget 讀回值 {read_val} 與寫入值 0x42 不符")
            fail = True
    except FileNotFoundError:
        log("[ERROR] 找不到 i2cget 指令，請確認是否已安裝 i2c-tools")
        fail = True
    except subprocess.CalledProcessError as e:
        log(f"[ERROR] i2cget 讀取失敗: {e.stderr.strip()}")
        fail = True
    except Exception as e:
        log(f"[ERROR] i2cget 執行例外: {e}")
        fail = True

    # ===== GPIO 收尾 =====
    gpio_release()

    # ===== 最後依 fail 決定 PASS / FAIL =====
    if not fail:
        log("[PASS] EEPROM RD TEST 測試通過")
        return True, "\n".join(lines)
    else:
        log("[FAIL] EEPROM RD TEST 測試未通過")
        return False, "\n".join(lines)
    # return (not fail), "\n".join(lines)

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
        return False, f"[GPIO][FAIL] Toml 設定數量: {expected_pairs} 組，路徑設定 {len(pairs)} 組；請調整 [GPIO].expect 或 pairs 使數量一致。"

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

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[GPIO][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[GPIO][FAIL] 測試未通過")
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

def SD_test():
    """
    Micro SD 測試（只算板上實體 SD/MMC）
    
    測試目標：
      - 掃描 SD/MMC 裝置（mmcblk*）
      - 檢查與 TOML expect 是否相符

    TOML：
      [Micro SD Card]
      expect = 1
    """
    lines = []
    fail = False

    # === 讀 TOML section 一次搞定 ===
    cfg = toml_get("Micro SD Card", None, {}) or {}

    # 期望數量
    try:
        expect = int(cfg.get("expect", 0))
    except Exception:
        expect = 0

    # === 掃描 SD/MMC 裝置 ===
    disks = _list_mmc_disks_only()

    lines.append(f"[SD] 系統上偵測到 {len(disks)} 個 SD 裝置，Toml 設定 {expect} 個 SD 裝置")

    # === 數量檢查 ===
    if expect > 0 and len(disks) != expect:
        fail = True
        lines.append(f"[SD][FAIL] 數量不符：系統上偵測到 {len(disks)} 個 SD 裝置，Toml 設定 {expect} 個 SD 裝置")

    # === 檢查是否有裝置 ===
    if not disks:
        lines.append("[SD][FAIL] 無 SD 裝置")
        fail = True

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[SD][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[SD][FAIL] 測試未通過")
        return False, "\n".join(lines)

#================= SD CARD TEST =================

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

# 下層：只負責通訊與結果彙整
def serial_loopback_test(expect: int, nodes: list[str]):
    # import serial, time
    lines, bad_nodes = [], []
    ok_count = 0
    fail = False
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
    if not count_ok:
        fail = True
        lines.append(f"[RS232][FAIL] 數量不符：系統上偵測到 {ok_count} 個裝置，Toml 設定 {expect} 個裝置")
    if bad_nodes:
        fail = True
        lines.append(f"[RS232][FAIL] 失敗節點：{', '.join(bad_nodes)}")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append(f"[RS232][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append(f"[RS232][FAIL] 測試未通過")
        return False, "\n".join(lines)


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
    
    lines.append(f"[UART] 指定數量: {len(nodes)} / Toml 設定: {expect}")

    # === 數量檢查 ===
    if expect is not None and expect > 0:
        if len(nodes) != expect:
            fail = True
            lines.append(f"[UART][FAIL] 數量不符：系統上偵測到 {len(nodes)} 個 UART 介面，Toml 設定 {expect} 個")

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

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[UART][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[UART][FAIL] 測試未通過")
        return False, "\n".join(lines)

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
    lines.append(f"[SPI] 指定數量: {len(spi_paths)} / Toml 設定: {expect}")

    # ===== 4) 數量檢查 =====
    if expect > 0 and len(spi_paths) != expect:
        fail = True
        lines.append(f"[SPI][FAIL] 數量不符：路徑寫 {len(spi_paths)} 個 SPI 裝置，Toml 設定 {expect} 個")

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

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[SPI][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[SPI][FAIL] 測試未通過")
        return False, "\n".join(lines)

# ===== SPI TEST =====

# ===== CPU TEST =====
def CPU_test():
    """
    CPU 測試：
    - 讀取 [CPU] 的:
        * expect: 期望 CPU 顆數（socket 數，必須 > 0）
        * CPU_MODEL_1: 預期 CPU 型號字串
    - 驗證流程：
        1) expect 必須 > 0
        2) 使用 dmidecode -t processor 取得實際 CPU 顆數並比對
        3) 從 /proc/cpuinfo 取得實際 CPU model name
        4) 若實際型號字串中有包含 CPU_MODEL_1，則 PASS，否則 FAIL
    - 回傳：(ok: bool, msg: str)
    """


    lines = [] # 用來存放測試結果
    fail = False # 用來存放測試是否失敗

    cfg = toml_get("CPU", None, {}) or {} # 用來存放 TOML 的設定

    # ===== 1. 顆數比對 =====
    try:
        expect = int(cfg.get("expect", 0)) # 用來存放期望的 CPU 顆數
    except Exception:
        expect = 0 # 如果無法轉換為整數，則預設為 0

    lines.append(f"[CPU] Toml 設定: {expect} 顆 CPU") # 用來存放期望的 CPU 顆數

    if expect <= 0:
        lines.append(f"[CPU][FAIL] Toml 設定: {expect} 顆 CPU，必須大於 0") # 如果期望的 CPU 顆數小於或等於 0，則當成 FAIL
        return False, "\n".join(lines)

    # --- 使用 dmidecode 取得實際 CPU 顆數 ---
    actual_count = 0 # 用來存放實際的 CPU 顆數
    exe = shutil.which("dmidecode") # 用來存放 dmidecode 的執行檔

    if exe:
        try:
            env = os.environ.copy() # 用來存放環境變數
            env["LANG"] = "C" # 用來存放語言
            env["LC_ALL"] = "C" # 用來存放語言

            out = subprocess.check_output(
                [exe, "-t", "processor"], # 用來執行 dmidecode -t processor 
                text=True, # 用來存放輸出
                stderr=subprocess.DEVNULL, # 用來存放錯誤
                env=env, # 用來存放環境變數
                timeout=5.0, # 用來存放逾時
            )

            for line in out.splitlines():
                if line.strip().startswith("Processor Information"): # 如果行開頭是 "Processor Information"，則實際顆數加 1
                    actual_count += 1

        except Exception as e:
            lines.append(f"[CPU][WARN] dmidecode 執行失敗：{e}")

    if actual_count <= 0:
        actual_count = 1 # 如果無法取得 CPU 顆數，則預設為 1
        lines.append("[CPU][INFO] 無法由 dmidecode 取得 CPU 顆數，預設為 1") # 用來存放無法取得 CPU 顆數的訊息

    lines.append(f"[CPU] 系統上偵測到 {actual_count} 顆 CPU，Toml 設定 {expect} 顆 CPU") # 用來存放實際顆數和預期顆數

    if actual_count != expect: # actual_count 是實際顆數，expect 是預期顆數
        fail = True # 如果實際顆數和預期顆數不相等，則當成 FAIL
        lines.append(f"[CPU][FAIL] 數量不符：系統上偵測到 {actual_count} 顆 CPU，Toml 設定 {expect} 顆 CPU") # 用來存放實際顆數和預期顆數不相等的訊息
    else:
        lines.append(f"[CPU][PASS] 數量相符：系統上偵測到 {actual_count} 顆 CPU，Toml 設定 {expect} 顆 CPU") # 如果實際顆數和預期顆數相等，則當成 PASS

    # ===== 2. 預期 CPU 型號 =====
    expect_cpu = str(cfg.get("CPU_MODEL_1", "")).strip() # 讀取 UI 存進 TOML 的字串，用來存放預期 CPU 型號

    if expect_cpu:
        lines.append(f"[CPU] Toml 設定型號：{expect_cpu}") # 用來存放預期 CPU 型號
    else:
        lines.append("[CPU] 未在 Toml 設定 CPU 型號") # 用來存放未設定 CPU 型號的訊息

    # ===== 3. 取得實際 CPU 型號 =====
    system_cpu = "" # 用來存放系統讀到的 CPU 型號字串
    try:
        with open("/proc/cpuinfo") as f: # 用來讀取 /proc/cpuinfo 檔案
            for line in f:
                if "model name" in line.lower(): # 如果行包含 "model name"，則將行分割為兩部分，第一部分為 "model name"，第二部分為 CPU 型號
                    system_cpu = line.strip().split(":", 1)[1].strip() # 將行分割為兩部分，第一部分為 "model name"，第二部分為 CPU 型號
                    break
    except Exception as e:
        lines.append(f"[CPU][WARN] 讀取 /proc/cpuinfo 失敗：{e}") # 用來存放讀取 /proc/cpuinfo 失敗的訊息

    if system_cpu:
        lines.append(f"[CPU] 系統上偵測到型號：{system_cpu}") # 用來存放實際 CPU 型號
    else:
        lines.append("[CPU][WARN] 無法取得系統上偵測到的型號") # 用來存放無法取得實際型號的訊息

    # ===== 4. 型號比對 =====
    if expect_cpu and system_cpu: # 如果預期型號和實際型號都不為空，則比對
        if expect_cpu in system_cpu: # 如果預期型號在實際型號中，則當成 PASS
            lines.append(f"[CPU][PASS] 型號相符：系統上偵測到型號 {system_cpu}，Toml 設定型號 {expect_cpu}") # 用來存放型號相符的訊息
        else:
            lines.append(f"[CPU][FAIL] 型號不符：系統上偵測到型號 {system_cpu}，Toml 設定型號 {expect_cpu}") # 用來存放型號不符的訊息
            fail = True # 如果型號不符，則當成 FAIL
    else:
        # 如果預期型號或實際型號為空，則當成 FAIL
        lines.append("[CPU][FAIL] 未在 Toml 設定型號或無法取得系統上偵測到的型號") # 用來存放未設定型號或無法取得實際型號的訊息
        fail = True # 如果未設定型號或無法取得實際型號，則當成 FAIL

    # ===== 5. 決定 PASS / FAIL =====
    if not fail:
        lines.append("[CPU][PASS] 測試通過") # 用來存放測試通過的訊息
        return True, "\n".join(lines) # 用來存放測試通過的訊息
    else:
        lines.append("[CPU][FAIL] 測試未通過") # 用來存放測試未通過的訊息
        return False, "\n".join(lines) # 用來返回測試未通過的訊息


def MEMORY_test():
    """
    MEMORY 測試：
      - TOML 期望值：
          * expect           -> toml_mem_expect  (期望數量)
          * MEMORY_SIZE_1..N -> toml_mem_sizes   (每條期望容量 GiB)
      - 實際值（由 dmidecode 抓）：
          * sys_mem_expect    -> 實際數量
          * sys_mem_sizes    -> 每條實際容量 GiB
      - 第三步會做：
          * 數量比對
          * 每條容量比對
    """
    lines = []
    cfg = toml_get("MEMORY", None, {}) or {}
    fail = False

    # ===== 1. 讀取 TOML 期望條數 =====
    try:
        toml_mem_expect = int(cfg.get("expect", 0))
    except Exception:
        toml_mem_expect = 0

    lines.append(f"[MEMORY] Toml 設定：{toml_mem_expect} 條記憶體")

    # ===== 2. 讀取 MEMORY_SIZE_1..N：每條期望容量 =====
    toml_mem_sizes = [] # 這個陣列用來存放 TOML 的期望容量
    idx = 1 # 用來存放索引
    while True:
        key = f"MEMORY_SIZE_{idx}" # 用來存放 KEY, 例如 MEMORY_SIZE_1, MEMORY_SIZE_2, ..., idx 是索引用來索引 MEMORY_SIZE_1, MEMORY_SIZE_2, ...
        if key not in cfg: # 如果 KEY 不在 TOML 中，則跳出迴圈
            break

        raw = cfg.get(key) # 用來存放 VALUE, 例如 8, 16, ..., idx 是索引用來索引 MEMORY_SIZE_1, MEMORY_SIZE_2, ...
        try:
            size_gib = int(raw) # 用來存放 VALUE 轉換為整數
            toml_mem_sizes.append(size_gib)
        except Exception:
            lines.append(f"[MEMORY][WARN] {key} 無法解析為整數：{raw!r}") # 用來存放無法解析為整數的訊息

        idx += 1

    lines.append(f"[MEMORY] Toml 設定每條期望容量(GiB)：{toml_mem_sizes}") # 用來存放 TOML 的期望容量

    # ===== 3. 用 dmidecode 抓實際記憶體資訊 =====
    exe = shutil.which("dmidecode") # 用來存放 dmidecode 的執行檔
    if not exe:
        lines.append("[MEMORY][FAIL] 找不到 dmidecode") # 用來存放找不到 dmidecode 的訊息
        return False, "\n".join(lines)

    try:
        env = os.environ.copy() # 用來存放環境變數
        env["LANG"] = "C" # 用來存放語言
        env["LC_ALL"] = "C" # 用來存放語言

        out = subprocess.check_output(
            [exe, "-t", "memory"], # 用來執行 dmidecode -t memory
            text=True,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=5.0,
        )
    except Exception as e:
        lines.append(f"[MEMORY][FAIL] dmidecode 執行失敗：{e}")
        return False, "\n".join(lines)

    # 解析實際記憶體資訊
    sys_mem_expect = 0
    sys_mem_sizes = []

    for line in out.splitlines():
        s = line.strip()

        # 只處理 "Size:" 開頭的行
        # 範例：Size: 8192 MB, Size: 16 GB, Size: No Module Installed
        if not s.startswith("Size:"):
            continue

        # 跳過空插槽
        if "No Module Installed" in s:
            continue

        parts = s.split()
        # parts 範例: ["Size:", "8192", "MB"]
        if len(parts) < 3:
            continue

        try:
            value = int(parts[1])
            unit = parts[2].upper()
        except Exception:
            continue

        # 轉換為 MB
        if unit == "MB":
            size_mb = value
        elif unit == "GB":
            size_mb = value * 1024
        else:
            # 不支援其他單位
            continue

        sys_mem_expect += 1
        size_gib = size_mb / 1024
        size_gib_int = int(round(size_gib))
        sys_mem_sizes.append(size_gib_int)

    lines.append(f"[MEMORY] 系統上偵測到 {sys_mem_expect} 條記憶體")
    lines.append(f"[MEMORY] 系統上偵測到每條記憶體容量(GiB)：{sys_mem_sizes}")

    # ===== 4. 開始比對 =====
    # 4-1. 檢查期望條數是否有設定
    if toml_mem_expect <= 0:
        lines.append(f"[MEMORY][FAIL] Toml 設定: {toml_mem_expect} 條記憶體，必須大於 0")
        fail = True
        return False, "\n".join(lines)

    # 4-2. 數量比對
    if sys_mem_expect != toml_mem_expect:
        lines.append(f"[MEMORY][FAIL] Memory 數量不符 (Toml 設定: {toml_mem_expect} 條記憶體，系統上偵測到 {sys_mem_expect} 條記憶體)")
        fail = True
    else:
        lines.append(f"[MEMORY][PASS] Memory 數量相符 (Toml 設定: {toml_mem_expect} 條記憶體，系統上偵測到 {sys_mem_expect} 條記憶體)")
    
        # 4-3. 比對容量內容（用排序比對，避免插槽順序不同）
    if len(sys_mem_sizes) != len(toml_mem_sizes):
        # 數量不一致時，排序比對會誤判，先檢查長度
        lines.append(
            f"[MEMORY][FAIL] Memory 容量數量不符 "
            f"(Toml 設定: {len(toml_mem_sizes)} 條, 系統上偵測到 {len(sys_mem_sizes)} 條)"
        )
        fail = True
    elif sorted(toml_mem_sizes) != sorted(sys_mem_sizes):
        lines.append(f"[MEMORY][FAIL] Memory 容量不符 (Toml 設定: {toml_mem_sizes}, 系統上偵測到: {sys_mem_sizes})")
        fail = True
    else:
        lines.append(f"[MEMORY][PASS] Memory 容量相符 (Toml 設定: {toml_mem_sizes}, 系統上偵測到: {sys_mem_sizes})")
    # else:
    #     lines.append("[MEMORY][INFO] 未設定 MEMORY_SIZE，跳過容量檢查")

    # ===== 5. 決定 PASS / FAIL =====
    if fail:
        lines.append("[MEMORY][FAIL] 測試未通過")
        return False, "\n".join(lines)
    else:
        lines.append("[MEMORY][PASS] 測試通過")
        return True, "\n".join(lines)



def HDMI_test():
    if ask_yes_no("HDMI 測試", "畫面是否正常顯示？"):
        return True, "[HDMI] PASS"
    return False, "[HDMI] FAIL"

def VGA_test():
    if ask_yes_no("VGA 測試", "畫面是否正常顯示？"):
        return True, "[VGA] PASS"
    return False, "[VGA] FAIL"
    
def DP_test():
    if ask_yes_no("DP 測試", "畫面是否正常顯示？"):
        return True, "[DP] PASS"
    return False, "[DP] FAIL"

def LED_test():
    if ask_yes_no("LED 測試", "LED 是否正常亮起？"):
        return True, "[LED] PASS"
    return False, "[LED] FAIL"

def POWER_BUTTON_test():
    if ask_yes_no("Power Button 測試", "Power Button 是否正常？"):
        return True, "[Power Button] PASS"
    return False, "[Power Button] FAIL"

def POWER_CONNECTOR_test():
    if ask_yes_no("Power Connector 測試", "Power Connector 是否正常？"):
        return True, "[Power Connector] PASS"
    return False, "[Power Connector] FAIL"

def POWER_SW_CONNECTOR_test():
    if ask_yes_no("Power SW Connector 測試", "Power SW Connector 是否正常？"):
        return True, "[Power SW Connector] PASS"
    return False, "[Power SW Connector] FAIL"

def RESET_BUTTON_test():
    if ask_yes_no("Reset Button 測試", "Reset Button 是否正常？"):
        return True, "[Reset Button] PASS"
    return False, "[Reset Button] FAIL"

def RECOVERY_BUTTON_test():
    if ask_yes_no("Recovery Button 測試", "Recovery Button 是否正常？"):
        return True, "[Recovery Button] PASS"
    return False, "[Recovery Button] FAIL"
    
def SMA_test():
    if ask_yes_no("SMA 測試", "SMA 是否正常？"):
        return True, "[SMA] PASS"
    return False, "[SMA] FAIL"

def SW1_test():
    if ask_yes_no("SW1 測試", "SW1 是否正常？"):
        return True, "[SW1] PASS"
    return False, "[SW1] FAIL"

def SW2_test():
    if ask_yes_no("SW2 測試", "SW2 是否正常？"):
        return True, "[SW2] PASS"
    return False, "[SW2] FAIL"
    
def MCU_CONNECTOR_test():
    if ask_yes_no("MCU Connector 測試", "MCU Connector 是否正常？"):
        return True, "[MCU Connector] PASS"
    return False, "[MCU Connector] FAIL"
    
def RTC_test():
    if ask_yes_no("RTC 測試", "RTC 是否正常？"):
        return True, "[RTC] PASS"
    return False, "[RTC] FAIL"
    
def RTC_OUT_test():
    if ask_yes_no("RTC OUT 測試", "RTC OUT 是否正常？"):
        return True, "[RTC OUT] PASS"
    return False, "[RTC OUT] FAIL"

def DC_INPUT_test():
    if ask_yes_no("DC INPUT 測試", "DC INPUT 是否正常？"):
        return True, "[DC INPUT] PASS"
    return False, "[DC INPUT] FAIL"

def DC_OUTPUT_test():
    if ask_yes_no("DC OUTPUT 測試", "DC OUTPUT 是否正常？"):
        return True, "[DC OUTPUT] PASS"
    return False, "[DC OUTPUT] FAIL"

def CASE_OPEN_test():
    if ask_yes_no("CASE OPEN 測試", "CASE OPEN 是否正常？"):
        return True, "[CASE OPEN] PASS"
    return False, "[CASE OPEN] FAIL"

def PD_POWER_INPUT_test():
    if ask_yes_no("PD POWER INPUT 測試", "PD POWER INPUT 是否正常？"):
        return True, "[PD POWER INPUT] PASS"
    return False, "[PD POWER INPUT] FAIL"

def PSE_POWER_OUTPUT_test():
    if ask_yes_no("PSE POWER OUTPUT 測試", "PSE POWER OUTPUT 是否正常？"):
        return True, "[PSE POWER OUTPUT] PASS"
    return False, "[PSE POWER OUTPUT] FAIL"

def INNOAGENT_test():
    if ask_yes_no("INNO_AGENT 測試", "INNO_AGENT 是否正常？"):
        return True, "[INNO_AGENT] PASS"
    return False, "[INNO_AGENT] FAIL"

def GPS_test():
    if ask_yes_no("GPS 測試", "GPS 是否正常？"):
        return True, "[GPS] PASS"
    return False, "[GPS] FAIL"

# def VRAIN_GPIO_test():
#     if ask_yes_no("VRAIN GPIO 測試", "VRAIN GPIO 是否正常？"):
#         return True, "[VRAIN GPIO] PASS"
#     return False, "[VRAIN GPIO] FAIL"

# ===================== FAN_test(): 無 UI 的 pwm/rpm path，手動/自動合一 =====================

DEFAULT_PWM_LO = 30
DEFAULT_PWM_HI = 100

# ---------- 通用小工具 ----------
def _sleep(sec):
    try: time.sleep(float(sec))
    except: time.sleep(1)

def _sleep_with_events(seconds):
    """
    非阻塞式延遲，期間定期處理 UI 事件，讓計時器可以更新。
    替代 time.sleep()，用於需要保持 UI 響應的場景。
    
    Args:
        seconds: 要延遲的秒數
    """
    try:
        from PyQt5.QtWidgets import QApplication
    except:
        # 如果沒有 PyQt5，回退到普通 sleep
        time.sleep(seconds)
        return
    
    start_time = time.time()
    while time.time() - start_time < seconds:
        try:
            QApplication.processEvents()
        except:
            pass
        # 短暫延遲，避免 CPU 占用過高
        time.sleep(0.05 if seconds < 1.0 else 0.1)

def _wait_for_process(proc, timeout=None, check_interval=0.1):
    """
    非阻塞式等待進程完成，期間定期處理 UI 事件，讓計時器可以更新。
    替代 proc.wait()，用於需要保持 UI 響應的場景。
    
    Args:
        proc: subprocess.Popen 物件
        timeout: 超時時間（秒），None 表示不設超時
        check_interval: 檢查間隔（秒），預設 0.1 秒
    
    Returns:
        True: 進程正常完成
        False: 超時或進程不存在
    """
    if proc is None: # 如果 proc 為 None, 則返回 False
        return False
    
    try: # 嘗試從 PyQt5 中 import QApplication
        from PyQt5.QtWidgets import QApplication
    except: # 如果沒有 PyQt5，回退到普通 wait
        if timeout: # 如果 timeout 不為 None, 則等待 timeout 秒
            try: # 嘗試等待 proc 完成
                proc.wait(timeout=timeout)
                return True # 如果 proc 完成, 則返回 True
            except: # 如果 proc 完成時間超過 timeout, 則返回 False
                return False
    start_time = time.time()
    while True:
        # 定期處理 UI 事件，讓計時器可以更新
        try:
            QApplication.processEvents()
        except:
            pass
        
        # 檢查進程是否已完成
        if proc.poll() is not None:
            return True # 如果 proc 完成, 則返回 True
        
        # 檢查是否超時
        if timeout and (time.time() - start_time) >= timeout:
            return False # 如果 proc 完成時間超過 timeout, 則返回 False
        
        # 短暫延遲，避免 CPU 占用過高
        time.sleep(check_interval) # 短暫延遲，避免 CPU 占用過高

def _within(val, target, tol):
    if target <= 0:  # 目標為 0 表示不檢查
        return True # 如果目標為 0, 則返回 True
    lo = target - target * tol / 100 # 計算低值
    hi = target + target * tol / 100 # 計算高值
    return lo <= val <= hi # 返回 lo <= val <= hi

def _read_int(path):
    try: # 嘗試讀取 path 檔案
        with open(path) as f: # 開啟 path 檔案
            s = re.sub(r"[^\d]", "", f.read()) # 將 s 中的非數字字元去除
        return int(s or "0") # 將 s 轉換為整數
    except: # 如果讀取 path 檔案失敗, 則返回 0
        return 0 # 返回 0

def _ask_human(msg):
    try: # 嘗試使用 zenity 問問題
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
      - 'acpi:/sys/class/thermal/cooling_deviceX'  ACPI cooling_device
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
    if s.startswith("acpi:"):
        return ("acpi", s[5:].strip())
    # 自動偵測 ACPI cooling_device 路徑
    if "cooling_device" in s:
        return ("acpi", s.replace("device:", "").strip())
    if s.startswith("device:"):
        s = s.split("device:",1)[1]
    return ("device", s)

# ===================== 主函式 =====================
def FAN_test():
    """
    讀 TOML：
      [FAN]
      expect = N              # 要測試的風扇數量
      [[FAN.items]]           # 風扇項目陣列（一個風扇一個項目）
        fan_path = "..."      # 風扇路徑
        manual = true/false   # 手動/自動模式
        seconds = 2~10        # 等待秒數
        low = 1000            # 自動模式：低速目標 rpm
        high = 7000           # 自動模式：高速目標 rpm
        tolerance = 10        # 容許誤差百分比
      
      說明：
      - 只要有風扇，就會在 TOML 中列出項目
      - 1 個風扇 = 1 個 [[FAN.items]] 項目
      - 多個風扇 = 多個 [[FAN.items]] 項目
    """
    fan_cfg = toml_get("FAN", "items", []) # 從 TOML 中讀取 FAN 區塊的 items 項目
    expect  = int(toml_get("FAN", "expect", 0)) # 從 TOML 中讀取 FAN 區塊的 expect 項目
    items   = fan_cfg[:expect] if expect > 0 else fan_cfg # 如果 expect 大於0, 就依序取 items 項目, 否則取 fan_cfg 項目

    if not items: # 如果 items 為空, 則跳過
        print("[FAN] 無設定，SKIP") # 印出 [FAN] 無設定，SKIP
        return True, "[SKIP]" 

    fail, results = False, [] # 初始化 fail 和 results

    for idx, it in enumerate(items, 1):
        manual   = bool(it.get("manual", False)) # 從 TOML 中讀取 items 項目的 manual 項目
        seconds  = float(it.get("seconds", 2)) # 從 TOML 中讀取 items 項目的 seconds 項目
        fanp_raw = str(it.get("fan_path") or it.get("path") or "").strip() # 從 TOML 中讀取 items 項目的 fan_path 或 path 項目
        low      = int(it.get("low", 0)) # 從 TOML 中讀取 items 項目的 low 項目
        high     = int(it.get("high", 0)) # 從 TOML 中讀取 items 項目的 high 項目
        tol      = int(it.get("tolerance", 10)) # 從 TOML 中讀取 items 項目的 tolerance 項目

        # ===== 手動：相容 test_fan() 的三種 target（device/i2c/gpio） =====
        if manual:
            # 防呆：手動不支援 eapi:N 或純數字
            if re.match(r'^(eapi:\d+|\d+)$', fanp_raw, re.I): # 如果 fanp_raw 符合 eapi:N 或純數字的格式, 則跳過
                fail = True
                results.append(f"[{idx}] 手動模式不支援 EAPI：{fanp_raw}") # 將錯誤訊息加入 results 列表
                continue

            kind, *args = _parse_manual_target(fanp_raw) # 解析 fanp_raw 的格式
            print(f"[FAN-{idx}] 手動模式 target={kind} path={fanp_raw}") # 印出 [FAN-{idx}] 手動模式 target={kind} path={fanp_raw}

            if kind == "device": # 如果 kind 為 device, 則跳過
                devpath = args[0]
                if _is_rk(): # 如果 _is_rk() 為 True, 則跳過
                    # 依原 shell 在 RK 的序列（pwmchip export→pwm0...）
                    try:
                        os.chdir(devpath) # 進入 devpath 目錄
                        with open("export","w") as f: f.write("0")
                        os.chdir("pwm0")
                        with open("period","w") as f: f.write("10000") # 寫入 10000
                        with open("duty_cycle","w") as f: f.write("10000")  # 100%
                        with open("polarity","w") as f: f.write("normal") # 寫入 normal
                        with open("enable","w") as f: f.write("1") # 寫入 1
                        _sleep(2)
                        with open("duty_cycle","w") as f: f.write("5000")   # 50%
                        with open("polarity","w") as f: f.write("normal") # 寫入 normal
                        with open("enable","w") as f: f.write("1") # 寫入 1
                        _sleep(2)
                        with open("duty_cycle","w") as f: f.write("0")      # 0%
                        with open("polarity","w") as f: f.write("normal")
                        with open("enable","w") as f: f.write("1")
                        os.chdir("..")
                        with open("unexport","w") as f: f.write("0")
                    except Exception as e:
                        fail = True; results.append(f"[{idx}] RK 手動序列失敗：{e}") # 將錯誤訊息加入 results 列表
                else:
                    # 一般 sysfs：找 pwm1 切換 50%→100%→0%
                    pwm_path = _find_pwm1_under(devpath) # 找 pwm1
                    if not pwm_path:
                        fail = True; results.append(f"[{idx}] 找不到 pwm1：{devpath}") # 將錯誤訊息加入 results 列表
                    else:
                        _write_pwm_sysfs(pwm_path, 50);  _sleep(2) # 寫入 50%
                        _write_pwm_sysfs(pwm_path, 100); _sleep(2) # 寫入 100%
                        _write_pwm_sysfs(pwm_path, 0);   _sleep(0.3) # 寫入 0%

            elif kind == "i2c":
                bus, addr, reg = args # 解析 args 的格式
                for v in (30, 100, 0):
                    try:
                        subprocess.check_call(["i2cset","-f","-y",str(bus), hex(addr), hex(reg), str(v)], # 執行 i2cset 命令
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as e:
                        fail = True; results.append(f"[{idx}] i2cset 失敗：{e}") # 將錯誤訊息加入 results 列表
                    _sleep(2)

            elif kind == "gpio":
                export_num, gpio_name = args # 解析 args 的格式
                try:
                    with open("/sys/class/gpio/export","w") as f: f.write(str(export_num)) # 寫入 export_num
                    name = str(gpio_name) # 將 gpio_name 轉換為字串 並賦值給 name
                    if name.isdigit(): name = f"gpio{name}" # 如果 name 為數字, 則在 name 前面加上 gpio
                    base = f"/sys/class/gpio/{name}" # 將 base 設為 /sys/class/gpio/{name}
                    with open(os.path.join(base,"direction"),"w") as f: f.write("out") # 寫入 out
                    with open(os.path.join(base,"value"),"w") as f: f.write("1") # 寫入 1
                    _sleep(2) # 等待 2 秒
                    with open(os.path.join(base,"value"),"w") as f: f.write("0") # 寫入 0
                    _sleep(0.3)
                    with open("/sys/class/gpio/unexport","w") as f: f.write(str(export_num))
                except Exception as e:
                    fail = True; results.append(f"[{idx}] GPIO 切換失敗：{e}") # 將錯誤訊息加入 results 列表

            elif kind == "acpi":
                # ACPI cooling_device：只能 0/1 切換（開/關）
                acpi_path = args[0] # 解析 args 的格式
                cur_state = os.path.join(acpi_path, "cur_state")
                if not os.path.exists(cur_state):
                    fail = True; results.append(f"[{idx}] ACPI 路徑不存在：{cur_state}") # 將錯誤訊息加入 results 列表
                else:
                    print(f"[FAN-{idx}] ACPI cooling_device：{acpi_path}") # 印出 [FAN-{idx}] ACPI cooling_device：{acpi_path}
                    try:
                        # 切換 1 → 0 → 1 讓風扇有變化
                        for v in ("1", "0", "1"):
                            with open(cur_state, "w") as f: f.write(v)
                            print(f"  -> cur_state = {v}") # 印出 cur_state = {v}
                            _sleep(2)
                    except PermissionError:
                        print(f"[FAN-{idx}] 需要 root 權限，嘗試 sudo...") # 印出 [FAN-{idx}] 需要 root 權限，嘗試 sudo...
                        try:
                            for v in ("1", "0", "1"):
                                subprocess.run(["sudo", "tee", cur_state], input=v.encode(),
                                               stdout=subprocess.DEVNULL, check=True)
                                print(f"  -> cur_state = {v} (sudo)") # 印出 cur_state = {v} (sudo)
                                _sleep(2)
                        except Exception as e:
                            fail = True; results.append(f"[{idx}] ACPI 控制失敗：{e}") # 將錯誤訊息加入 results 列表
                    except Exception as e:
                        fail = True; results.append(f"[{idx}] ACPI 控制失敗：{e}") # 將錯誤訊息加入 results 列表

            # 人工確認
            ok = _ask_human(f"[FAN-{idx}] 風扇是否有快慢變化？") # 問 user 風扇是否有快慢變化
            if not ok:
                fail = True; results.append(f"[{idx}] 無轉速變化(手動)")
            continue

        # ===== 自動：EAPI（相容 test_FR68_FAN）或 sysfs（Jetson/RK/ARM） =====
        if re.match(r'^(eapi:\d+|\d+)$', fanp_raw, re.I): # 如果 fanp_raw 符合 eapi:N 或純數字的格式, 則跳過
            # --- x86 / EAPI ---
            try:
                dev = int(fanp_raw.split(":")[1]) if ":" in fanp_raw else int(fanp_raw) # 將 fanp_raw 轉換為數字
            except:
                dev = 0
            print(f"[FAN-{idx}] 自動 EAPI dev={dev} sec={seconds} low/high={low}/{high} tol={tol}") # 印出 [FAN-{idx}] 自動 EAPI dev={dev} sec={seconds} low/high={low}/{high} tol={tol}

            _set_pwm_eapi(dev, DEFAULT_PWM_LO); _sleep(2)
            rpm_lo = _read_rpm_eapi(dev) # 讀取 rpm
            if not _within(rpm_lo, low, tol):
                fail = True; results.append(f"[{idx}] 低速 {rpm_lo} 不在 {low}±{tol}%") # 將錯誤訊息加入 results 列表

            _set_pwm_eapi(dev, DEFAULT_PWM_HI); _sleep(2)
            rpm_hi = _read_rpm_eapi(dev) # 讀取 rpm
            if not _within(rpm_hi, high, tol):
                fail = True; results.append(f"[{idx}] 高速 {rpm_hi} 不在 {high}±{tol}%")

            _set_pwm_eapi(dev, 0); _sleep(0.4)
            continue

        # --- Jetson / RK / 一般 ARM：sysfs 自動 ---
        platform = "Jetson" if _is_jetson() else ("RK" if _is_rk() else "ARM")
        print(f"[FAN-{idx}] 自動 sysfs ({platform}) path={fanp_raw} sec={seconds} low/high={low}/{high} tol={tol}") # 印出 [FAN-{idx}] 自動 sysfs ({platform}) path={fanp_raw} sec={seconds} low/high={low}/{high} tol={tol}
        pwm_path = _find_pwm1_under(fanp_raw)
        if not pwm_path:
            fail = True; results.append(f"[{idx}] 找不到 pwm1：{fanp_raw}") # 將錯誤訊息加入 results 列表
            continue

        rpm_path = _find_fan_input_near(pwm_path) # 找 fan_input
        if not rpm_path:
            # 自動與手動已分離：找不到 tach 就判 FAIL
            fail = True; results.append(f"[{idx}] 找不到 fan*_input（無法自動驗證）：{fanp_raw}") # 將錯誤訊息加入 results 列表
            continue

        _write_pwm_sysfs(pwm_path, DEFAULT_PWM_LO); _sleep(2)
        rpm_lo_v = _read_rpm_sysfs(rpm_path) # 讀取 rpm
        if not _within(rpm_lo_v, low, tol):
            fail = True; results.append(f"[{idx}] 低速 {rpm_lo_v} 不在 {low}±{tol}%") # 將錯誤訊息加入 results 列表

        _write_pwm_sysfs(pwm_path, DEFAULT_PWM_HI); _sleep(2)
        rpm_hi_v = _read_rpm_sysfs(rpm_path) # 讀取 rpm
        if not _within(rpm_hi_v, high, tol):
            fail = True; results.append(f"[{idx}] 高速 {rpm_hi_v} 不在 {high}±{tol}%") # 將錯誤訊息加入 results 列表

        _write_pwm_sysfs(pwm_path, 0); _sleep(0.3)

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    lines = results # 將 results 賦值給 lines
    if not fail:
        lines.append("[FAN][PASS] 測試通過") # 將 [FAN][PASS] 測試通過加入 lines 列表
        return True, "\n".join(lines)
    else:
        lines.append("[FAN][FAIL] 測試未通過") # 將 [FAN][FAIL] 測試未通過加入 lines 列表
        return False, "\n".join(lines)


def MIC_test():
    """
    自動偵測可用 MIC/喇叭裝置；若你想固定，改 MIC_DEVICES/PLAYBACK 即可。
    """

    # 讀取期望數量
    expect = int(toml_get("MIC", "expect", 0) or 0)
    
    # 自動偵測
    auto_caps, auto_play = pick_mic_devices()
    
    # 比對數量
    if expect > 0 and len(auto_caps) != expect:
        return False, f"[MIC] 期望 {expect} 個，實際偵測到 {len(auto_caps)} 個"

    # ===== 可以改這裡做「固定指定」；設成 None 代表用自動偵測 =====
    MIC_DEVICES = auto_caps     # 使用上面偵測的結果
    PLAYBACK    = auto_play or (auto_caps[0] if auto_caps else None)
    RATE = 32000
    FORMAT = "cd"
    # ===============================================================

    if not MIC_DEVICES or not PLAYBACK:
        return False, "找不到可用的錄音/播放裝置（arecord/aplay -L）"

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

        # 等待 1 秒，期間定期處理 UI 事件，讓計時器可以更新
        _sleep_with_events(1.0)
        
        heard = ask_yes_no("MIC 測試", f"裝置 {dev}\n是否聽到錄製的聲音？")

        # 收尾：安全終止 arecord|aplay
        try: os.killpg(proc.pid, signal.SIGTERM)
        except Exception: pass
        
        # 等待進程結束，期間定期處理 UI 事件
        if not _wait_for_process(proc, timeout=1.0):
            # 超時，強制終止
            try: os.killpg(proc.pid, signal.SIGKILL)
            except Exception: pass

        if not heard:
            return False, f"MIC 錄音播放無聲音 (dev={dev}, play={PLAYBACK})"

        # 等待 0.3 秒，期間定期處理 UI 事件
        _sleep_with_events(0.3)

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

    # 3) 引導動作：接線
    ask_info("LINE-IN 測試", "請「移除耳機」，並用連接線把 LINE_IN 與 Headphone/Speaker 連接完成，然後按「繼續測試」。")

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
    # 使用非阻塞等待，以便在等待期間定期處理 UI 事件，讓計時器可以更新
    max_wait = 8  # 最多等待 8 秒
    
    # 等待播放進程完成
    if not _wait_for_process(play_proc, timeout=max_wait):
        try: 
            os.killpg(play_proc.pid, signal.SIGKILL)
        except Exception: 
            pass
    
    # 等待錄音進程完成
    if not _wait_for_process(rec_proc, timeout=max_wait):
        try: 
            os.killpg(rec_proc.pid, signal.SIGKILL)
        except Exception: 
            pass

    # 5) 引導動作：復原
    ask_info("LINE-IN 測試", "請「移除連接線」，並把耳機插回去，然後按「繼續測試」。")

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
    except Exception:
        pass  # 播放失敗也會交由人工判定
        pb = None
    
    # 等待播放完成，使用非阻塞等待，以便在等待期間定期處理 UI 事件
    if pb is not None:
        _wait_for_process(pb, timeout=10)

    heard = ask_yes_no("LINE-IN 測試", "是否聽到剛才錄下的聲音？")

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

    ask_info("SPEAKER 測試", "將進行左右聲道單獨播音（各 1 次）。\n請注意聽左聲道與右聲道是否正確。")

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
    # 使用非阻塞等待，以便在等待期間定期處理 UI 事件，讓計時器可以更新
    max_wait = 20  # 最多等待 20 秒
    
    if not _wait_for_process(proc, timeout=max_wait):
        # 超時，先嘗試溫和終止
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        
        # 再等待 2 秒，期間繼續處理事件
        if not _wait_for_process(proc, timeout=2.0):
            # 還是超時，強制終止
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
            return False, "speaker-test 未正常結束"

    # 3) 讓使用者判斷
    test_results = ask_yes_no("SPEAKER 測試", "左右聲道是否正確播音？")

    if not test_results:
        return False, f"SPEAKER 測試失敗（播放裝置：{play_dev}）"
    return True, "SPEAKER test passed."


def CAMERA_test(width=1280, height=720, fps=30, seconds=1, snapshot_dir="snapshots"):
    """
    相機測試：偵測 → 預覽 → 拍照（一次完成）
    支援：CSI (libcamera) / MIPI (Jetson v4l2) / USB (UVC)
    規則：有成功拍到 JPG 才 PASS
    """
    # 讀取期望數量
    try:
        expect = int(toml_get("CAMERA", "expect", 0) or 0)
    except Exception:
        expect = 0

    # ===== 工具函式 =====
    _cmd_cache = {} # 快取 has_cmd 結果
    def has_cmd(cmd): # 檢查系統中是否可呼叫某個指令（有快取）
        if cmd not in _cmd_cache: # 如果 cmd 不在快取中，則執行 subprocess.call 檢查是否可呼叫某個指令
            _cmd_cache[cmd] = subprocess.call( # 執行 subprocess.call 檢查是否可呼叫某個指令
                ["bash", "-lc", f"command -v {shlex.quote(cmd)} >/dev/null 2>&1"]
            ) == 0 # 如果 subprocess.call 返回 0，則將 cmd 加入快取
        return _cmd_cache[cmd]

    def run(cmd, timeout=None): # 執行系統命令並回傳 stdout
        return subprocess.check_output(
            ["bash", "-lc", cmd], text=True, stderr=subprocess.STDOUT, timeout=timeout
        )

    def snap_path(name):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S") # 目前時間
        safe = re.sub(r"[^a-zA-Z0-9_]+", "_", name)
        return os.path.join(snapshot_dir, f"{safe}_{ts}.jpg") # 回傳完整路徑

    def save_jpg(tmp, final):
        try:
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0: # 確認暫存檔存在且大小 > 0
                shutil.move(tmp, final) # 搬移成最終檔名
                return True
        finally:
            if os.path.exists(tmp): # 無論成功與否，確保暫存檔被清掉
                os.remove(tmp)
        return False

    def is_capture_node(dev):
        if not HAS_V4L2: # 若無 v4l2-ctl，就放行（避免誤砍）
            return True
        try:
            out = run(f"v4l2-ctl -d {shlex.quote(dev)} --all 2>/dev/null || true") # 查詢裝置能力
            return "Video Capture" in out # 只要能力有 Video Capture 即可
        except Exception:
            return False # 如果查詢裝置能力失敗，則回傳 False

    def is_jetson():
        try:
            if run("uname -m || true").strip().lower() != "aarch64": # 確認 CPU 架構是否為 aarch64
                return False
            if os.path.exists("/sys/devices/platform/host1x"): # 確認是否有 tegra 相關裝置
                return True
            if HAS_V4L2 and "tegra" in run("v4l2-ctl --list-devices 2>/dev/null || true").lower(): # 確認是否有 tegra 相關裝置
                return True
        except Exception:
            pass
        return False # 如果確認 CPU 架構、tegra 相關裝置失敗，則回傳 False

    # 快取
    HAS_V4L2 = has_cmd("v4l2-ctl") # 快取 v4l2-ctl 結果
    HAS_GST = has_cmd("gst-launch-1.0") # 快取 gst-launch-1.0 結果
    HAS_FFMPEG = has_cmd("ffmpeg") # 快取 ffmpeg 結果
    IS_JETSON = is_jetson() # 快取 is_jetson 結果
    
    pathlib.Path(snapshot_dir).mkdir(parents=True, exist_ok=True) # 確保快照目錄存在

    # ===== 偵測 + 預覽 + 拍照（合併） =====
    results = []  # [{name, bus, result, reason, snapshot}] # 用來存放所有測試結果
    tested_groups = set()  # 避免同組重複測試

    def preview_and_capture_gst(dev, name, bus): # 用 GStreamer 預覽 1 秒後拍照
        """用 GStreamer 預覽 1 秒後拍照"""
        if not HAS_GST:
            return False, "gst-launch-1.0 不可用", None # 如果 gst-launch-1.0 不可用，則回傳 False
        
        # 預覽 1 秒
        try:
            preview_cmd = (f"timeout 2 gst-launch-1.0 -e v4l2src device={dev} num-buffers=30 ! " # 預覽 1 秒
                          f"videoconvert ! xvimagesink sync=false 2>&1 || true")
            run(preview_cmd, timeout=3) # 執行預覽命令
        except Exception:
            pass
        
        # 拍照
        final = snap_path(name) # 產生最終檔名
        tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg") # 產生暫存檔名
        cmd = (f"gst-launch-1.0 -e v4l2src device={dev} num-buffers=1 ! " # 拍照
               f"videoconvert ! video/x-raw,width={width},height={height} ! " # 轉換格式
               f"jpegenc ! filesink location={shlex.quote(tmp)} -q") # 拍照命令
        try:
            run(cmd, timeout=8) # 執行拍照命令
            if save_jpg(tmp, final): # 如果拍照成功，則回傳 True
                return True, "OK", final # 如果拍照成功，則回傳 True
            return False, "未產生影像", None # 如果拍照失敗，則回傳 False
        except Exception as e:
            return False, f"拍照失敗：{str(e).splitlines()[-1][:100]}", None # 如果拍照失敗，則回傳 False

    def preview_and_capture_csi(sid, name): # 用 libcamera 預覽 1 秒後拍照
        """用 libcamera 預覽 1 秒後拍照"""
        if not has_cmd("libcamera-still"):
            return False, "libcamera-still 不可用", None # 如果 libcamera-still 不可用，則回傳 False
        
        # 預覽 1 秒
        try:
            run(f"timeout 2 libcamera-hello -t 1000 --camera {sid} 2>&1 || true", timeout=3) # 預覽 1 秒
        except Exception:
            pass
        
        # 拍照
        final = snap_path(name) # 產生最終檔名
        tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg") # 產生暫存檔名
        cmd = (f"libcamera-still -n -t {int(seconds*1000)} -o {shlex.quote(tmp)} " # 拍照
               f"--width {width} --height {height} --camera {sid} 2>&1") # 拍照命令
        try:
            run(cmd, timeout=max(6, seconds+4)) # 執行拍照命令
            if save_jpg(tmp, final): # 如果拍照成功，則回傳 True
                return True, "OK", final # 如果拍照成功，則回傳 True
            return False, "未產生影像", None # 如果拍照失敗，則回傳 False
        except Exception as e:
            return False, f"拍照失敗：{str(e).splitlines()[-1][:100]}", None # 如果拍照失敗，則回傳 False

    def preview_and_capture_usb(dev, name): # 用 ffmpeg/gst 預覽 1 秒後拍照
        """用 ffmpeg/gst 預覽 1 秒後拍照"""
        # 預覽 1 秒
        if HAS_GST:
            try:
                preview_cmd = (f"timeout 2 gst-launch-1.0 -e v4l2src device={dev} num-buffers=30 ! " # 預覽 1 秒
                              f"videoconvert ! xvimagesink sync=false 2>&1 || true")
                run(preview_cmd, timeout=3) # 執行預覽命令
            except Exception:
                pass
        
        # 拍照（先試 ffmpeg）
        if HAS_FFMPEG:
            for fmt in ["mjpeg", "yuyv422"]:
                final = snap_path(name) # 產生最終檔名
                tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg") # 產生暫存檔名
                cmd = (f"ffmpeg -y -hide_banner -loglevel error "
                       f"-f video4linux2 -input_format {fmt} -framerate {fps} -video_size {width}x{height} "
                       f"-i {shlex.quote(dev)} -frames:v 1 {shlex.quote(tmp)}") # 拍照命令
                try:
                    run(cmd, timeout=8) # 執行拍照命令
                    if save_jpg(tmp, final): # 如果拍照成功，則回傳 True
                        return True, f"OK(ffmpeg {fmt})", final # 如果拍照成功，則回傳 True
                except Exception:
                    pass # 如果拍照失敗，則回傳 False
        
        # 再試 gstreamer # 如果 ffmpeg 失敗，則再試 gstreamer
        if HAS_GST:
            final = snap_path(name)
            tmp = os.path.join(snapshot_dir, f".tmp_{uuid.uuid4().hex}.jpg") # 產生暫存檔名
            cmd = (f"gst-launch-1.0 -e v4l2src device={dev} num-buffers=1 ! " # 拍照
                   f"videoconvert ! jpegenc ! filesink location={shlex.quote(tmp)} -q")
            try:
                run(cmd, timeout=8) # 執行拍照命令
                if save_jpg(tmp, final): # 如果拍照成功，則回傳 True
                    return True, "OK(gst)", final # 如果拍照成功，則回傳 True
            except Exception:
                pass # 如果拍照失敗，則回傳 False
        
        return False, "無法拍照", None # 如果拍照失敗，則回傳 False

    # ----- 1. CSI 相機 (libcamera) -----
    if has_cmd("libcamera-hello"): # 如果 libcamera-hello 可用，則進行 CSI 相機測試
        try:
            out = run("libcamera-hello --list-cameras 2>&1 || true") # 查詢相機列表
            if "Available cameras" in out:
                blocks = re.split(r"\n\s*\d+\s*:", out) # 分割相機列表
                for i, b in enumerate(blocks[1:]):
                    name = f"CSI{i}"
                    group = f"CSI-{i}" # 相機組
                    if group in tested_groups:
                        continue
                    tested_groups.add(group) # 加入已測試組
                    ok, reason, snap = preview_and_capture_csi(i, name) # 拍照
                    results.append({"name": name, "bus": "CSI", "result": "PASS" if ok else "FAIL",
                                   "reason": reason, "snapshot": snap}) # 加入測試結果
        except Exception:
            pass # 如果查詢相機列表失敗，則回傳 False

    # ----- 2. USB 相機 -----
    if HAS_V4L2:
        try:
            out = run("v4l2-ctl --list-devices 2>/dev/null || true") # 查詢裝置列表
            blocks = re.split(r"\n\s*\n", out.strip()) # 分割裝置列表
            for b in blocks:
                lines = [l for l in b.splitlines() if l.strip()] # 去除空白字元後再分割裝置列表
                if not lines:
                    continue
                header = lines[0].lower() # 轉換為小寫
                # 跳過 platform（MIPI）裝置
                if "platform:" in header or "tegra" in header:
                    continue
                devs = [l.strip() for l in lines[1:] if l.strip().startswith("/dev/video")] # 去除空白字元後再分割裝置列表
                for dev in devs:
                    if not os.path.exists(dev) or not is_capture_node(dev):
                        continue
                    # 用裝置路徑當 group（簡化）
                    group = f"USB-{dev}" # 裝置組
                    if group in tested_groups:
                        continue
                    tested_groups.add(group) # 加入已測試組
                    name = f"USB({dev})" # 裝置名稱
                    ok, reason, snap = preview_and_capture_usb(dev, name) # 拍照，並回傳結果
                    results.append({"name": name, "bus": "USB", "result": "PASS" if ok else "FAIL",
                                   "reason": reason, "snapshot": snap}) # 加入測試結果
                    break  # 每組只測一個節點
        except Exception:
            pass # 如果拍照失敗，則回傳 False

    # ----- 3. MIPI 相機 (Jetson) -----
    if IS_JETSON and HAS_GST:
        consecutive_missing = 0 # 連續缺失次數
        for vid_idx in range(256):
            if consecutive_missing >= 5: # 如果連續缺失次數 >= 5，則跳出
                break
            dev = f"/dev/video{vid_idx}" # 裝置路徑
            if not os.path.exists(dev): # 確認裝置是否存在
                consecutive_missing += 1 # 連續缺失次數 +1
                continue
            if not is_capture_node(dev):
                consecutive_missing += 1 # 連續缺失次數 +1
                continue
            group = f"MIPI-{vid_idx}" # 裝置組
            if group in tested_groups:
                consecutive_missing = 0 # 連續缺失次數歸零
                continue
            tested_groups.add(group) # 加入已測試組
            name = f"MIPI({dev})"
            ok, reason, snap = preview_and_capture_gst(dev, name, "MIPI") # 拍照
            results.append({"name": name, "bus": "MIPI", "result": "PASS" if ok else "FAIL",
                           "reason": reason, "snapshot": snap}) # 加入測試結果
            consecutive_missing = 0

    # ===== 結果判斷 =====
    if not results:
        return False, "[CAMERA][FAIL] 找不到任何相機裝置" # 如果找不到任何相機裝置，則回傳 False

    # 數量檢查
    actual_count = len(results)
    if expect > 0 and actual_count != expect:
        return False, f"[CAMERA][FAIL] 數量不符：偵測到 {actual_count} 組，期望 {expect} 組" # 如果數量不符，則回傳 False

    # 組合訊息
    lines = [] # 組合訊息
    all_pass = True
    for r in results:
        status = r["result"] # 狀態
        lines.append(f"[CAMERA] {r['name']} ({r['bus']}) {status}: {r['reason']}")
        if status != "PASS":
            all_pass = False # 如果狀態不是 PASS，則設為 False

    if all_pass:
        lines.append("[CAMERA][PASS] 測試通過")
        return True, "\n".join(lines) # 如果測試通過，則回傳 True
    else:
        lines.append("[CAMERA][FAIL] 測試未通過")
        return False, "\n".join(lines) # 如果測試未通過，則回傳 False

# ===== CAN BUS TEST =====
def CANBUS_test():
    """
    [CANBUS]
    expect = 1 或 2
    CANBUS_items = ["can0", "can1", ...]

    expect = 1：
        - 使用 CANBUS_items[0] 當 item
        - ip link set item up type can bitrate 1000000
        - receive = timeout 3 candump item | head -n1
        - 判斷是否等於 "  item  123   [4]  AB CD AB CD"

    expect = 2：
        - 使用 CANBUS_items[0] 當 item1（TX）
        - 使用 CANBUS_items[1] 當 item2（RX）
        - ip link set item1 / item2 up type can bitrate 1000000
        - (sleep 1; cansend item1 "123#ABCDABCD") &
        - receive = timeout 3 candump item2 | head -n1
        - 判斷是否等於 "  item2  123   [4]  AB CD AB CD"

    expect 其他值：
        - 視為「不支援3個以上的裝置」
    """

    # ===== 讀 TOML 設定 =====
    sec = toml_get("CANBUS", None, {}) or {}

    try:
        expect = int(sec.get("expect", 0) or 0)
    except Exception:
        expect = 0

    devs = sec.get("CANBUS_items", []) or [] # CANBUS_items 是 list，需要轉換成 str
    devs = [str(d).strip() for d in devs if str(d).strip()] # 這裡是去除空白字元還有轉換成 str

    fail = False      # 對應 shell 裡的 fail=0/1
    lines = []        # 累積的訊息
    used_ifaces = []  # 最後關掉介面用
    
    # ===== 檢查基本設定 =====
    if not devs:
        return False, "[CANBUS] CANBUS_items 是空的，請在 TOML 填入介面名稱（例如 can0, can1）"

    if expect not in (1, 2):
        return False, "不支援3個以上的裝置，請把 [CANBUS].expect 設成 1 或 2"

    if len(devs) < expect:
        return False, (
            f"[CANBUS] 設定錯誤：expect={expect}，但 CANBUS_items 只有 {len(devs)} 個：{devs}"
        )

    # 只取前 expect 個（和 shell 一樣只看 test config 指定的那組）
    devs = devs[:expect]

    # ===== 小工具：跑 shell 指令 =====
    def sh(cmd, timeout=5, check=True, capture=False):
        """
        簡單包 subprocess.run
        - cmd 可為字串或 list
        - check=True：非 0 回傳碼會丟例外
        - capture=True：回傳 stdout
        """
        try:
            result = subprocess.run(
                cmd if isinstance(cmd, list) else shlex.split(cmd),
                timeout=timeout,
                check=check,
                text=True,
                capture_output=capture,
            )
            return result.stdout if capture else ""
        except subprocess.CalledProcessError as e:
            if capture:
                return (e.stdout or "") + (e.stderr or "")
            raise

    # ===== 先 modprobe 必要模組 =====
    for mod in ("can", "can_raw", "mttcan"):
        try:
            sh(f"modprobe {mod}", timeout=3, check=False)
        except Exception as e:
            # 不直接 fail，先記警告
            lines.append(f"[CANBUS] modprobe {mod} 失敗（可忽略）：{e}")

    try:
        # ======================
        #  expect = 1：單一介面（等治具回傳）
        # ======================
        if expect == 1:
            item = devs[0]
            used_ifaces.append(item)

            # ip link set $item up type can bitrate 1000000
            try:
                sh(f"ip link set {item} up type can bitrate 1000000", timeout=3, check=True)
            except Exception as e:
                fail = True
                lines.append(f"[CANBUS] 無法啟用介面 {item}: {e}")

            if not fail:
                # receive=$(timeout 3 candump $item | head -n1)
                proc = subprocess.Popen(
                    ["bash", "-lc", f"timeout 3 candump {item} | head -n1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    line = proc.stdout.readline()
                finally:
                    proc.kill()

                receive = (line or "").rstrip("\n")
                expected = f"  {item}  123   [4]  AB CD AB CD"

                if receive == expected:
                    # shell：fail=False，不用動
                    lines.append(f"[CANBUS] {item} loopback OK")
                else:
                    fail = True
                    lines.append(
                        f"[CANBUS] Fail: Unable to read from device {item}; "
                        f"expected '{expected}', got '{receive or '<<no data>>'}'"
                    )

        # ======================
        #  expect = 2：item1 傳，item2 收
        # ======================
        elif expect == 2:
            item1, item2 = devs[0], devs[1]
            used_ifaces.extend([item1, item2])

            # ip link set item1 / item2 up type can bitrate 1000000
            for it in (item1, item2):
                try:
                    sh(f"ip link set {it} up type can bitrate 1000000", timeout=3, check=True)
                except Exception as e:
                    fail = True
                    lines.append(f"[CANBUS] 無法啟用介面 {it}: {e}")

            if not fail:
                # 先啟動發送端（後台執行，sleep 1 後發送）
                # (sleep 1;cansend $item1 "123#ABCDABCD") &
                sender = subprocess.Popen(
                    ["bash", "-lc", f"sleep 1; cansend {item1} '123#ABCDABCD'"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                
                # 立即啟動接收端（candump）
                # receive=$(timeout 3 candump $item2 | head -n1)
                proc = subprocess.Popen(
                    ["bash", "-lc", f"timeout 3 candump {item2} | head -n1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

                try:
                    line = proc.stdout.readline()
                    sender.wait(timeout=2)  # 等待發送完成
                finally:
                    proc.kill()
                    if sender.poll() is None:  # 如果還在運行就終止
                        sender.kill()

                receive = (line or "").rstrip("\n")
                expected = f"  {item2}  123   [4]  AB CD AB CD"

                if receive == expected:
                    lines.append(f"[CANBUS] {item1} -> {item2} OK")
                else:
                    fail = True
                    lines.append(
                        f"[CANBUS] Fail: Unable to read from device {item2}; "
                        f"expected '{expected}', got '{receive or '<<no data>>'}'"
                    )

    finally:
        # ===== 和 shell 一樣：把用過的介面 ifconfig down =====
        for it in set(used_ifaces):
            try:
                sh(f"ifconfig {it} down", timeout=3, check=False)
            except Exception:
                pass

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    if not fail:
        lines.append("[CAN BUS][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[CAN BUS][FAIL] 測試未通過")
        return False, "\n".join(lines)


# ================= CAN BUS TEST =================

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
    fail = False

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
            fail = True
            break

        bus, addr, offset = parts[0], parts[1], parts[2]

        # ===== 寫 0x55 =====
        cmd_set_55 = ["i2cset", "-f", "-y", bus, addr, offset, "0x55"]
        res = subprocess.run(cmd_set_55, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            fail = True
            logs.append(f"[I2C] 第 {idx} 組 i2cset 0x55 失敗：{res.stderr.strip()}")
            continue

        # ===== 讀回驗證 0x55 =====
        cmd_get = ["i2cget", "-f", "-y", bus, addr, offset]
        res = subprocess.run(cmd_get, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            fail = True
            logs.append(f"[I2C] 第 {idx} 組 i2cget 失敗：{res.stderr.strip()}")
            continue

        val = res.stdout.strip()
        if val != "0x55":
            fail = True
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
            fail = True
            logs.append(f"[I2C] 第 {idx} 組 i2cset 0xAA 失敗：{res.stderr.strip()}")
            continue

        # ===== 讀回驗證 0xAA =====
        res = subprocess.run(cmd_get, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            fail = True
            logs.append(f"[I2C] 第 {idx} 組 i2cget 失敗：{res.stderr.strip()}")
            continue

        val = res.stdout.strip()
        if val != "0xAA":
            fail = True
            logs.append(
                f"[I2C] 第 {idx} 組：寫 0xAA 但讀到 {val} "
                f"(bus={bus}, addr={addr}, offset={offset})"
            )
            continue

        logs.append(f"[I2C] 第 {idx} 組 PASS (bus={bus}, addr={addr}, offset={offset})")

    # ===== 最後依 fail 決定 PASS / FAIL（同 shell）=====
    lines = logs
    if not fail:
        lines.append("[I2C][PASS] 測試通過")
        return True, "\n".join(lines)
    else:
        lines.append("[I2C][FAIL] 測試未通過")
        return False, "\n".join(lines)


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

        # 檢查是否為 SKIP 狀態（test_results 為字串 "SKIP"）
        if isinstance(test_results, str) and test_results.upper() == "SKIP":
            self.skipTest(self._last_msg)  # 使用 unittest 的 skipTest 方法
        elif test_results:
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

    def test_BKEY(self):
        self.run_item(BKEY_test)

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
    
    def test_FIBER(self):
        self.run_item(FIBER_test)
    
    def test_CPU(self):
        self.run_item(CPU_test)

    def test_MEMORY(self):
        self.run_item(MEMORY_test)

#----------手動確認項目----------

    def test_HDMI(self): # test_HDMI 會呼叫 run_item(HDMI_test) 執行 HDMI_test() 函式
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

    def test_CASE_OPEN(self):
        self.run_item(CASE_OPEN_test)

    def test_PD_POWER_INPUT(self):
        self.run_item(PD_POWER_INPUT_test)

    def test_PSE_POWER_OUTPUT(self):
        self.run_item(PSE_POWER_OUTPUT_test)

    def test_INNOAGENT(self):
        self.run_item(INNOAGENT_test)

    def test_GPS(self):
        self.run_item(GPS_test)

    # def test_VRAIN_GPIO(self):
    #     self.run_item(VRAIN_GPIO_test)


# 要新增測項：新增一個 test_XXX，裡面呼叫 check_xxx() 方法, 並在 UI 的 checkbox 上顯示對應的顯示名稱
# ===== unittest：把每個測項包成 test_* 方法 =====

# ===== 顯示名稱 ↔ 測試方法名（給 GUI 用的選單名稱）=====
# ===== 單一命名表：所有自動測項定義在這裡 =====
# 每一筆資料： (顯示名稱, Tests 的方法名, UI checkbox 的物件名稱)
# 單一命名表：顯示名稱、Tests 方法名、UI checkbox 名稱
TEST_ITEMS = [
    # ===== 自動測試項目 =====
    #UI上的顯示名稱        測試項目的方法名稱             UI checkbox 的物件名稱
    ("USB2.0",           "test_USB2",               "checkBox_USB2"), # USB2.0 測試項目UI上的名稱對應ui_name, test_USB2 方法對應fun_name, checkBox_USB2 物件名稱對應checkbox_name
    ("USB3.0",           "test_USB3",               "checkBox_USB3"),
    ("NetWork",          "test_NETWORK",            "checkBox_NETWORK"),
    ("Micro SD Card",    "test_Micro_SD",           "checkBox_MICROSD"),
    ("M-Key",            "test_MKEY",               "checkBox_MKEY"),
    ("B-Key",            "test_BKEY",               "checkBox_BKEY"),
    ("E-Key",            "test_EKEY",               "checkBox_EKEY"),
    ("RS232",            "test_RS232",              "checkBox_RS232"),
    ("RS422",            "test_RS422",              "checkBox_RS422"),
    ("RS485",            "test_RS485",              "checkBox_RS485"),
    ("UART",             "test_UART",               "checkBox_UART"),
    ("SPI",              "test_SPI",                "checkBox_SPI"),
    ("GPIO",             "test_GPIO",               "checkBox_GPIO"),
    ("FAN",              "test_FAN",                "checkBox_FAN"),
    ("EEPROM",           "test_EEPROM",             "checkBox_EEPROM"),
    ("EEPROM (RD Test)", "test_EEPROM_RD",          "checkBox_EEPROM_RD"),
    ("Camera",           "test_CAMERA",             "checkBox_CAMERA"),
    ("CAN BUS",          "test_CANBUS",             "checkBox_CANBUS"),
    ("I2C",              "test_I2C",                "checkBox_I2C"),
    ("Optical Fiber",    "test_FIBER",              "checkBox_FIBER"),
    ("CPU NAME",         "test_CPU",                "checkBox_CPU"),          # 名稱請照 .ui 實際物件名改
    ("MEMORY",           "test_MEMORY",             "checkBox_MEM"),

    # ===== 手動測試項目（一樣有 checkbox，可以變色）=====
    ("MIC",              "test_MIC",                "checkBox_MIC"),
    ("LINE IN",          "test_LINE_IN",            "checkBox_LINEIN"),
    ("SPEAKER",          "test_SPEAKER",            "checkBox_SPEAKER"),
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
    ("CASE OPEN",        "test_CASE_OPEN",          "checkBox_CASE_OPEN"),
    ("PD POWER INPUT",   "test_PD_POWER_INPUT",     "checkBox_PD_POWER_INPUT"),
    ("PSE POWER OUTPUT", "test_PSE_POWER_OUTPUT",   "checkBox_PSE_POWER_OUTPUT"),
    ("InnoAgent",        "test_INNOAGENT",          "checkBox_INNOAGENT"),
    ("GPS",              "test_GPS",                "checkBox_GPS"),
    # ("VRAIN GPIO",       "test_VRAIN_GPIO",         "checkBox_VRAIN_GPIO"),
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
EXPECT_FROM_TOML = { # 這裡是將 UI 顯示名稱映射到 TOML 區塊名稱和鍵名稱, 例如 "USB2.0" 映射到 ("USB2", "expect"), 以此類推
    "USB2.0":           ("USB2", "expect"),
    "USB3.0":           ("USB3", "expect"),
    "NetWork":          ("Network", "expect"),
    "Micro SD Card":    ("Micro SD Card", "expect"),
    "GPIO":             ("GPIO", "expect"),
    "M-Key":            ("M-Key", "expect"),
    "FAN":              ("FAN", "expect"),
    "EEPROM":           ("EEPROM", "expect"),
    "EEPROM (RD Test)": ("EEPROM RD TEST", "expect"),
    "Camera":           ("CAMERA", "expect"),
    "CAN BUS":          ("CANBUS", "expect"),
    "RS232":            ("RS232", "expect"),
    "RS422":            ("RS422", "expect"),
    "RS485":            ("RS485", "expect"),
    "UART":             ("UART", "expect"),
    "I2C":              ("I2C", "expect"),
    "SPI":              ("SPI", "expect"),
    "Optical Fiber":    ("OPTICAL FIBER", "expect"),
    "MIC":              ("MIC", "expect"),
    "LINE IN":          ("LINE IN", "expect"),
    "SPEAKER":          ("SPEAKER", "expect"),
    "E-Key":            ("E-Key", "expect"),
    "CPU NAME":         ("CPU", "expect"),
    "MEMORY":           ("MEMORY", "expect"),
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
SELECTED_ITEMS_THIS_RUN = set()  # 記錄這次被勾選的測試項目（顯示名稱）

# 全域反查（method → display name）
_METHOD_TO_DISPLAY = {v: k for k, v in DISPLAY_NAME_MAP.items()}
def method_to_display_name(method: str) -> str:
    return _METHOD_TO_DISPLAY.get(method, method)

def _write_table_logs(out_dir, file_base, times, final_test_result, records, persisted_status, method_to_display, meta, mac_addresses=None):
    """
    產生 CSV 表格格式的 log 檔（命名規則與 log 檔相同）
    mac_addresses: MAC Address 清單，格式：[(iface, MAC), ...]
    """
    
    # 取得 MAC Address（如果未提供）
    if mac_addresses is None:
        mac_addresses = get_mac_addresses()
    mac_str = format_mac_addresses_for_log(mac_addresses)
    
    # 準備表格資料
    table_data = []
    order = ALL_ITEMS_ORDER or sorted(persisted_status.keys())
    
    for name in order:
        if name in persisted_status:
            status = persisted_status[name]
            # 從 records 找對應的詳細訊息
            method = DISPLAY_NAME_MAP.get(name)
            detail_msg = ""
            duration_ms = ""
            timestamp = ""
            if method:
                for r in records:
                    if r["name"] == method:
                        detail_msg = r.get("message", "").split("\n")[0][:100]  # 取第一行，最多100字
                        duration_ms = r.get("duration_ms", "")
                        timestamp = r.get("timestamp", "")
                        break
            table_data.append({
                "項目名稱": name,
                "狀態": status,
                "詳細訊息": detail_msg,
                "耗時(ms)": duration_ms if duration_ms else "",
                "時間戳記": timestamp
            })
    
    # 補上落網之魚
    for k in persisted_status.keys(): # persisted_status 是全域變數，包含了所有測試項目的最終狀態
        if k not in order:
            table_data.append({
                "項目名稱": k,
                "狀態": persisted_status[k],
                "詳細訊息": "",
                "耗時(ms)": "",
                "時間戳記": ""
            })
    
    # === CSV 表格（命名規則與 log 檔相同）===
    try:
        csv_name = f"{file_base}_{times}_{final_test_result}.csv" # file_base 是 SN，ts 是時間，final_test_result 是pass或fail
        csv_path = os.path.join(out_dir, csv_name)
        _write_csv_file(csv_path, table_data, mac_addresses)
    except Exception:
        pass

def _write_csv_file(csv_path, table_data, mac_addresses):
    """實際寫入 CSV 檔案的函式"""
    # 使用 utf-8-sig 編碼（帶 BOM），讓 Windows Excel 可以正確識別 UTF-8
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["項目名稱", "狀態", "詳細訊息", "耗時(ms)", "時間戳記", "MAC Address"])
        writer.writeheader()
        # 只在第一筆資料顯示 MAC Address，其他行留空
        # MAC Address 每個介面顯示在下一行（使用換行符號）
        mac_str_multiline = ""
        if mac_addresses:
            mac_lines = [f"{iface}: {mac}" for iface, mac in mac_addresses]
            mac_str_multiline = "\n".join(mac_lines)
        else:
            mac_str_multiline = "N/A"
        
        for idx, row in enumerate(table_data):
            if idx == 0:
                # 第一行顯示 MAC Address（多行格式）
                row["MAC Address"] = mac_str_multiline
            else:
                # 其他行留空
                row["MAC Address"] = ""
            writer.writerow(row)

def _write_table_logs_with_path(csv_path, records, persisted_status, method_to_display, meta, mac_addresses=None):
    """
    產生 CSV 表格格式的 log 檔（直接指定 csv_path）
    用於覆寫模式，三個檔案（.log, .csv, .json）使用相同邏輯
    """
    # 取得 MAC Address（如果未提供）
    if mac_addresses is None:
        mac_addresses = get_mac_addresses()
    
    # 準備表格資料
    table_data = []
    order = ALL_ITEMS_ORDER or sorted(persisted_status.keys())
    
    for name in order:
        if name in persisted_status:
            status = persisted_status[name]
            # 從 records 找對應的詳細訊息
            method = DISPLAY_NAME_MAP.get(name)
            detail_msg = ""
            duration_ms = ""
            timestamp = ""
            if method:
                for r in records:
                    if r["name"] == method:
                        detail_msg = r.get("message", "").split("\n")[0][:100]  # 取第一行，最多100字
                        duration_ms = r.get("duration_ms", "")
                        timestamp = r.get("timestamp", "")
                        break
            table_data.append({
                "項目名稱": name,
                "狀態": status,
                "詳細訊息": detail_msg,
                "耗時(ms)": duration_ms if duration_ms else "",
                "時間戳記": timestamp
            })
    
    # 補上落網之魚
    for k in persisted_status.keys():
        if k not in order:
            table_data.append({
                "項目名稱": k,
                "狀態": persisted_status[k],
                "詳細訊息": "",
                "耗時(ms)": "",
                "時間戳記": ""
            })
    
    # 寫入 CSV
    _write_csv_file(csv_path, table_data, mac_addresses)

# ===== 給 GUI 呼叫的 API =====
def run_selected_tests(selected_display_names, log_dir=None, sn=None, mes_info_meta=None, log_path=None, window=None):

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
    buf = io.StringIO() # 用於儲存測試結果的緩衝區
    runner = unittest.TextTestRunner( # 用於執行測試套件的 runner
        stream=buf,
        verbosity=0,
        resultclass=CollectingResult # 用於收集測試結果的 resultclass
    )
    result = runner.run(suite) # 執行測試套件，並返回結果

    # 3) 用 _records 組乾淨輸出（本輪）
    records = getattr(result, "_records", []) # 取得本輪測試項目詳細結果
    lines_run = [
        f"{r['name']}: {r['status']}" + (f" - {r.get('message')}" if r.get('message') else "") # 組成每個測試項目的狀態和詳細訊息
        for r in records
    ]
    text_out = "\n".join(lines_run) if lines_run else "No tests executed." # 組成本輪測試項目詳細結果

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
    global PERSISTED_STATUS, ALL_ITEMS_ORDER, SELECTED_ITEMS_THIS_RUN
    # 注意：不要用 PERSISTED_STATUS = {} 重新賦值，會導致其他模組 import 的 reference 失效
    # 直接用 update() 更新現有的 dict
    PERSISTED_STATUS.update(run_status)
    # 更新這次被選中的項目列表（供 EEPROM_test 使用）
    SELECTED_ITEMS_THIS_RUN = set(selected_display_names)

    # 6) 整體標籤（只要有 FAIL 或 ERROR 就算 fail）
    def _overall_tag(d: dict) -> str:
        if not d:
            return "FAIL"
        # 將 ERROR 也視為 fail；SKIP 不影響總結
        has_bad = any(v in ("FAIL", "ERROR") for v in d.values())
        return "FAIL" if has_bad else "PASS"

    final_test_result = _overall_tag(PERSISTED_STATUS)

    # 7) 取得 MAC Address
    mac_addresses = get_mac_addresses() # 取得 MAC Address
    mac_str = format_mac_addresses_for_log(mac_addresses) # 格式化 MAC Address 為字串

    # 8) 寫檔：檔名 <SN>_<YYYYMMDD_HHMMSS>_<pass|fail>.log
    out_dir = log_dir or "test_logs"        # 這裡把 log_dir 視為「WO 目錄名」
    os.makedirs(out_dir, exist_ok=True)
    times = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 檔名使用 SN，優先使用 sn 參數，其次用 meta 中的 SYSTEM_SN，都沒有則用預設值
    file_base = sn or (mes_info_meta.get("SYSTEM_SN") if mes_info_meta else None) or "UNKNOWN_SN"
    out_name = f"{file_base}_{times}_{final_test_result}.log"
    out_path = os.path.join(out_dir, out_name)

    # 內容：Header（可選）+ MAC Address + This Run（本輪）+ Current Status（所有最終狀態）
    lines = []
    if mes_info_meta and mes_info_meta.get("header"): # 如果 mes_info_meta 中有 header，就加入 header, 否則不加入
        lines.append(mes_info_meta["header"]); lines.append("") # 加入 header 後再加入空行
    
    # 加入 MAC Address 資訊（每個 MAC 顯示在下一行）
    lines.append("MAC Address:") # 格式：MAC Address:
    if mac_addresses: # 如果 mac_addresses 不為空，則加入 MAC Address
        for iface, mac in mac_addresses: # 每個 MAC 顯示在下一行
            lines.append(f"  {iface}: {mac}") # 格式：介面: MAC Address
    else:
        lines.append("  N/A") # 如果 mac_addresses 為空，則加入 N/A
    lines.append("") # 加入空行

    lines.append("---- This Run  錯誤原因 ----") # 本輪測試項目詳細結果
    lines.append(text_out) # 加入本輪測試項目詳細結果

    lines.append("") # 加入空行
    lines.append("---- Current Status 測試結果 ----") # 所有最終測試項目狀態
    order = ALL_ITEMS_ORDER or sorted(PERSISTED_STATUS.keys()) # 所有最終測試項目狀態排序
    for name in order:
        if name in PERSISTED_STATUS:
            lines.append(f"{name}: {PERSISTED_STATUS[name]}") # 加入所有最終測試項目狀態
    # 落網之魚補上（若有）
    for k in PERSISTED_STATUS.keys():
        if k not in order:
            lines.append(f"{k}: {PERSISTED_STATUS[k]}")

    # 若外界指定 log_path，就覆寫那個路徑；否則寫我們的 out_path
    # 同時從 log_path 推導出 json_path 和 csv_path（三個檔案使用相同邏輯）
    if log_path:
        # 從 log_path 推導出基礎路徑（去掉 _PASS.log 或 _FAIL.log）
        log_dir_from_path = os.path.dirname(log_path) # 取得 log_path 的目錄
        log_basename = os.path.basename(log_path) # 取得 log_path 的檔名
        # 移除 _PASS.log 或 _FAIL.log 後綴，取得基礎檔名
        base_without_ext = re.sub(r'_(PASS|FAIL)\.log$', '', log_basename) # 移除 _PASS.log 或 _FAIL.log 後綴，取得基礎檔名
        # 產生新的檔名（使用當前測試結果）
        target_path = os.path.join(log_dir_from_path, f"{base_without_ext}_{final_test_result}.log") # 產生新的檔名（使用當前測試結果）
        json_path = os.path.join(log_dir_from_path, f"{base_without_ext}_{final_test_result}.json") # 產生新的檔名（使用當前測試結果）
        csv_path = os.path.join(log_dir_from_path, f"{base_without_ext}_{final_test_result}.csv") # 產生新的檔名（使用當前測試結果）
    else:
        target_path = out_path
        json_path = os.path.join(out_dir, f"{file_base}_{times}_{final_test_result}.json") # 產生新的檔名（使用當前測試結果）
        csv_path = os.path.join(out_dir, f"{file_base}_{times}_{final_test_result}.csv") # 產生新的檔名（使用當前測試結果）
    
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

    # 9) 同時覆寫一份 JSON 摘要（命名規則與 log 檔相同）
    try:
        # json_path 已在上面計算好
        # 將 MAC Address 格式化為字典格式
        mac_dict = {iface: mac for iface, mac in mac_addresses} if mac_addresses else {}
        runcard = mes_info_meta.get("RUNCARD", "") if mes_info_meta else "" # meta.get("RUNCARD", "") 從 meta 中取得 runcard 值, 如果沒有就返回空字串
        workorder = mes_info_meta.get("WORKORDER", "") if mes_info_meta else ""
        system_sn = mes_info_meta.get("SYSTEM_SN", "") if mes_info_meta else ""
        operator = mes_info_meta.get("OPERATOR", "") if mes_info_meta else ""
        mode = mes_info_meta.get("MES_MODE", "") if mes_info_meta else ""
        header = mes_info_meta.get("header", "") if mes_info_meta else ""  # header 保持小寫（字串內容）
        process_name = mes_info_meta.get("PROCESS_NAME", "") if mes_info_meta else ""
        tool_version = (mes_info_meta.get("TOOL_VERSION", "") if mes_info_meta else None) # 測試工具版本
        test_tool_config = (mes_info_meta.get("TEST_TOOL_CONFIG", "") if mes_info_meta else None) # 測試工具配置
        date = mes_info_meta.get("date", "") if mes_info_meta else ""
        inputdate = mes_info_meta.get("inputdate", "") if mes_info_meta else ""
        # 使用 build_item_list() 產生實際的 item_list（MES 格式）
        # item_list 使用 PERSISTED_STATUS（累積所有測過的項目），與 .log 和 .csv 行為一致
        item_list = build_item_list(list(PERSISTED_STATUS.keys()), PERSISTED_STATUS)
        
        # 計算累積的 PASS/FAIL 數量（基於 PERSISTED_STATUS）
        total_passes = sum(1 for v in PERSISTED_STATUS.values() if v == "PASS")
        total_failures = sum(1 for v in PERSISTED_STATUS.values() if v == "FAIL")
        
        summary = { # summary 是字典，包含了所有測試結果的資訊, 提供給 MES 使用的 JSON 格式
            "Timestamp": datetime.now().isoformat(timespec="seconds"),
            "Header": header,
            "Process Name": process_name,
            "Tool Version": tool_version,
            # "Test Tool Config": test_tool_config,
            "Test Item List": item_list, # 累積的測試項目清單（MES 格式）
            "MAC Addresses": mac_dict,                # MAC Address 字典 {iface: MAC, ...}
            "This Run Selected": selected_display_names, # 本輪選擇的測試項目清單
            "This Run Results": records,              # 本輪測試項目詳細結果
            "Total": len(PERSISTED_STATUS), # 累積測試項目總數
            "Passes": total_passes, # 累積測試項目通過數
            "Failures": total_failures, # 累積測試項目失敗數
            "Current Status": PERSISTED_STATUS,     # 全部最終測試項目狀態（與 .log 的 Current Status 一致）
            "Final Result": final_test_result, # 整體測試結果
            "Meta": (mes_info_meta or {}), # 測試工具配置, 這裡是 mes_info_meta 字典, mes_info_meta 字典是在TestTool2.0.py中設定
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 9.5) 產生 CSV 表格格式的 log（命名規則與 log 檔相同）
    try:
        # csv_path 已在上面計算好，直接傳遞給 _write_table_logs
        _write_table_logs_with_path(csv_path, records, PERSISTED_STATUS, method_to_display, mes_info_meta, mac_addresses)
    except Exception:
        pass

    # 9) 回傳：維持原本介面（第三個是本輪的 item_status，第四個是 log 檔案路徑）
    # target_path 就是實際寫入的 log 檔案路徑（如果 log_path 為 None，就是 out_path；否則就是 log_path）
    return result, text_out, run_status, target_path

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
