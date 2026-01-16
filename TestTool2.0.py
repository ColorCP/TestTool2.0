# main.py — 母板測試登入（多重繼承，依 .ui 運作）
import os
import sys
import subprocess
import shutil

# ============================================================
# 環境檢查與自動安裝（不需要外部 shell 腳本）
# ============================================================

def detect_os():
    """偵測作業系統類型"""
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=")[1].strip('"').lower()
    return "unknown"

def run_cmd(cmd, check=True):
    """執行命令並回傳是否成功"""
    try:
        result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False

# ===== 檢查 Python 套件 , pip 的套件名稱, apt 的套件名稱, 以及安裝python套件的名稱=====
def check_python_packages():
    """檢查 Python 套件，回傳缺少的套件清單"""
    missing = []
    package_checks = [
        ("PyQt5", "python3-pyqt5", "PyQt5"),# PyQt5 是 PyQt5 的套件名稱, python3-pyqt5 是 apt 的套件名稱, PyQt5 是 pip 的套件名稱,
        ("toml", "python3-toml", "toml"),
        ("serial", "python3-serial", "pyserial"),
        ("requests", "python3-requests", "requests"),
        ("yaml", "python3-yaml", "pyyaml"),
        ("pytest", "python3-pytest", "pytest"),  # unitest.py 需要
    ]
    
    for module_name, apt_name, pip_name in package_checks:
        try:
            __import__(module_name)
        except ImportError:
            missing.append((module_name, apt_name, pip_name))
    
    return missing

# ===== 檢查系統工具 , 系統工具名稱, 以及安裝的系統套件名稱=====
def check_system_tools():
    """檢查系統工具，回傳缺少的工具清單"""
    missing = []
    tool_checks = [
        ("dmidecode", "dmidecode"), # dmidecode 是系統工具名稱, dmidecode 是 apt 的套件名稱, dmidecode 是 pip 的套件名稱,
        ("sensors", "lm-sensors"),
        ("v4l2-ctl", "v4l-utils"),
        ("arecord", "alsa-utils"),
        ("candump", "can-utils"),
        ("i2cdetect", "i2c-tools"),
    ]
    
    for cmd, pkg in tool_checks:
        if not shutil.which(cmd):
            missing.append((cmd, pkg))
    
    return missing

def install_packages_apt(python_missing, tools_missing):
    """使用 apt 安裝套件 (Ubuntu/Debian)"""
    packages = []
    
    # Python 套件 (apt 版本)
    for _, apt_name, _ in python_missing:
        packages.append(apt_name)
    
    # 系統工具
    for _, pkg in tools_missing:
        packages.append(pkg)
    
    # 額外的 PyQt5 模組
    if any(m[0] == "PyQt5" for m in python_missing):
        packages.append("python3-pyqt5.qtmultimedia")
    
    if not packages:
        return True
    
    print(f"\n[安裝] 使用 apt 安裝：{', '.join(packages)}")
    
    # 更新套件列表
    subprocess.run(["sudo", "apt", "update"], check=False)
    
    # 安裝套件
    result = subprocess.run(["sudo", "apt", "install", "-y"] + packages)
    return result.returncode == 0

def install_packages_pip(python_missing):
    """使用 pip 安裝 Python 套件（備用方案）"""
    packages = [pip_name for _, _, pip_name in python_missing]
    
    if not packages:
        return True
    
    print(f"\n[安裝] 使用 pip 安裝：{', '.join(packages)}")
    
    # 檢查是否需要 --break-system-packages (PEP 668)
    pip_help = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--help"],
        capture_output=True, text=True
    )
    
    cmd = [sys.executable, "-m", "pip", "install"]
    if "break-system-packages" in pip_help.stdout:
        cmd.append("--break-system-packages")
    
    cmd.extend(packages)
    result = subprocess.run(cmd)
    return result.returncode == 0

def check_and_install_dependencies():
    """檢查必要套件，缺少時詢問是否安裝"""
    
    # 檢查缺少的套件
    python_missing = check_python_packages()
    tools_missing = check_system_tools()
    
    # 如果沒有缺少任何套件，直接返回
    if not python_missing and not tools_missing:
        return True
    
    # 顯示缺少的套件
    print("=" * 50)
    print("  TestTool 2.0 環境檢查")
    print("=" * 50)
    
    if python_missing:
        print("\n[警告] 缺少以下 Python 套件：")
        for module_name, _, _ in python_missing:
            print(f"  - {module_name}")
    
    if tools_missing:
        print("\n[警告] 缺少以下系統工具：")
        for cmd, pkg in tools_missing:
            print(f"  - {cmd} ({pkg})")
    
    print("")
    
    # 詢問是否安裝
    try:
        response = input("是否自動安裝缺少的套件？(Y/n) ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        sys.exit(0)
    
    if response not in ('', 'y', 'yes'):
        print("\n[警告] 跳過安裝，程式可能無法正常運作")
        sys.exit(1)
    
    # 偵測作業系統並安裝
    os_type = detect_os()
    print(f"\n[INFO] 偵測到作業系統：{os_type}")
    
    success = False
    
    if os_type in ("ubuntu", "debian", "linuxmint", "pop"):
        # Ubuntu/Debian 系統：優先使用 apt
        success = install_packages_apt(python_missing, tools_missing)
        
        # 如果 apt 安裝 Python 套件失敗，嘗試用 pip 作為備用
        if not success and python_missing:
            print("\n[INFO] apt 安裝失敗，嘗試使用 pip 作為備用方案...")
            success = install_packages_pip(python_missing)
    
    elif os_type in ("rhel", "centos", "fedora", "rocky", "almalinux"):
        # RHEL 系統：系統工具用 dnf/yum，Python 用 pip
        if tools_missing:
            pkg_mgr = "dnf" if shutil.which("dnf") else "yum"
            pkgs = [pkg for _, pkg in tools_missing]
            print(f"\n[安裝] 使用 {pkg_mgr} 安裝系統工具：{', '.join(pkgs)}")
            subprocess.run(["sudo", pkg_mgr, "install", "-y"] + pkgs)
        
        if python_missing:
            success = install_packages_pip(python_missing)
        else:
            success = True
    
    else:
        # 其他系統：只能用 pip 安裝 Python 套件
        print("\n[警告] 未知的作業系統，系統工具需要手動安裝")
        if tools_missing:
            print("請手動安裝：")
            for cmd, pkg in tools_missing:
                print(f"  - {pkg}")
        
        if python_missing:
            success = install_packages_pip(python_missing)
        else:
            success = True
    
    if success:
        print("\n[OK] 安裝完成！正在重新啟動程式...\n")
        # 重新執行自己
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("\n[錯誤] 安裝失敗，請檢查錯誤訊息")
        sys.exit(1)

# 在 import 其他模組前先檢查環境
check_and_install_dependencies()

# ============================================================
# 正常 import（環境檢查通過後才會執行到這裡）
# ============================================================
from PyQt5 import QtWidgets, QtCore, uic
from PyQt5.QtWidgets import QMessageBox
from ui_testtool import Ui_meslogin_Dialog   # 你的 .ui 轉出的檔
import json, logging
from datetime import datetime

from mes_api import MESClient  # 匯入 MES API 主程式
from MB_Test import mbtest_run as MB_Test # 匯入主板測試主程式

# ===== 共用：建立使用者 log（避免重複 handler）=====
def setup_useing_logger(wo, sn):
    log_dir = wo or "logs"
    os.makedirs(log_dir, exist_ok=True)

    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(log_dir, f"{(sn or 'RD')}_{time_str}.log") # SN 為空就 RD

    logger = logging.getLogger("useing")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in logger.handlers[:]:
        logger.removeHandler(h)
        try:
            h.close()
        except:
            pass

    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(fh)
    return logger, path

# ===== 參數（母板工具：SN 長度維持 11 碼；若將來要調整，改這裡）=====
SN_LEN_MES = 11
SN_LEN_OFFLINE = 11

class LoginDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)
        self.ui = Ui_meslogin_Dialog()
        self.ui.setupUi(self)
        self.setWindowTitle("Mother Board Test MES 登入")

        # 狀態
        self.mode = "OFFLINE"
        self.useing_logger = None
        self.log_file = None
        self.mes = None
        self.result_cfg = None   # ← 新增：給主程式帶出參數

        # 綁事件：即時控制，不等按鈕
        self.ui.RunCard_lineEdit.textChanged.connect(self.on_runcard_changed)
        self.ui.WO_lineEdit.textChanged.connect(self.refresh_enter_btn)
        self.ui.SN_lineEdit.textChanged.connect(self.refresh_enter_btn)
        self.ui.OP_lineEdit.textChanged.connect(self.refresh_enter_btn)
        self.ui.mes_ent_btn.clicked.connect(self.on_enter_clicked) #定義進站按鈕, 按下去後觸發on_enter_clicked函式

        # 先套一次規則
        self.on_runcard_changed()

        # sanity check（避免 ObjectName 打錯）
        for name in ["RunCard_lineEdit","WO_lineEdit","SN_lineEdit","OP_lineEdit","mes_ent_btn"]:
            assert hasattr(self.ui, name), f"找不到 {name}（請回 Qt Designer 檢查 ObjectName）"

    # ---------- UI log sink（左側「MES資訊」文字框） ----------
    def _append_to_mes_area(self, msg):
        w = getattr(self.ui, "MES_textEdit", None)  # 你的 QTextEdit 名稱
        if w is not None:
            try:
                w.append(str(msg))
                return
            except Exception:
                pass

        for name in ("textEdit", "textBrowser", "plainTextEdit", "logBrowser", "mesText"):
            w = getattr(self, name, None)
            if w is None:
                continue
            try:
                if hasattr(w, "append") and callable(w.append):
                    w.append(str(msg)); return
                if hasattr(w, "appendPlainText") and callable(w.appendPlainText):
                    w.appendPlainText(str(msg)); return
            except Exception:
                pass
        print(msg)

    # 只顯示在 UI，不寫測試 log
    def mes_ui_only(self, msg):
        self._append_to_mes_area(msg) # 只顯示在 UI

    # 寫測試 log + 顯示 UI（測試流程摘要才用這個）
    def ui_log(self, msg):
        try:
            if self.useing_logger:
                self.useing_logger.info(msg)
        except Exception:
            pass
        self._append_to_mes_area(msg)

    # ---------- 模式判斷 ----------
    def detect_mode(self, runcard):
        r = (runcard or "").strip().upper()
        if r.startswith("RD"):           return "RD"
        if r == "0":                     return "OFFLINE"
        if r.startswith(("A","S","P")):  return "AETINA_MES"
        return "INNODISK_MES"

    # ---------- 欄位控制（獨立小工具） ----------
    def set_field_state(self, widget, enabled=None, readonly=None, clear=False, placeholder=None):
        try:
            if clear: widget.clear()
            if enabled is not None: widget.setEnabled(bool(enabled))
            if readonly is not None: widget.setReadOnly(bool(readonly))
            if placeholder is not None and hasattr(widget, "setPlaceholderText"):
                widget.setPlaceholderText(placeholder)
        except Exception:
            pass

    def set_sn_maxlen(self, n):
        try:
            self.ui.SN_lineEdit.setMaxLength(int(n))
        except Exception:
            pass

    # ---------- 依 Runcard 即時套用 UI 規則 ----------
    def on_runcard_changed(self):
        rc = (self.ui.RunCard_lineEdit.text() or "").strip().upper()
        self.mode = self.detect_mode(rc)
        self.apply_mode_ui_rules(self.mode)
        self.refresh_enter_btn()

    def apply_mode_ui_rules(self, mode): # RD / OFFLINE / AETINA_MES / INNODISK_MES, UI 規則
        if mode == "RD":
            self.set_field_state(self.ui.WO_lineEdit, enabled=False, readonly=True)
            self.ui.WO_lineEdit.setText("RD_TEST")
            self.set_field_state(self.ui.SN_lineEdit, enabled=False, readonly=True, clear=True, placeholder="RD 模式不需 SN")
            self.set_field_state(self.ui.OP_lineEdit, enabled=False, readonly=True, clear=True, placeholder="RD 模式不需工號")
            self.set_sn_maxlen(0)

        elif mode == "OFFLINE":
            self.set_field_state(self.ui.WO_lineEdit, enabled=True, readonly=False, placeholder="請輸入工單號碼")
            self.set_field_state(self.ui.SN_lineEdit, enabled=True, readonly=False, placeholder=f"限 {SN_LEN_OFFLINE} 碼")
            self.set_field_state(self.ui.OP_lineEdit, enabled=True, readonly=False, placeholder="請輸入人員工號")
            self.set_sn_maxlen(SN_LEN_OFFLINE)

        else:
            self.set_field_state(self.ui.WO_lineEdit, enabled=True, readonly=False, placeholder="請輸入工單號碼")
            self.set_field_state(self.ui.SN_lineEdit, enabled=True, readonly=False, placeholder=f"限 {SN_LEN_MES} 碼")
            self.set_field_state(self.ui.OP_lineEdit, enabled=True, readonly=False, placeholder="請輸入人員工號")
            self.set_sn_maxlen(SN_LEN_MES)

    # ---------- 依模式決定是否可按『進站』 ----------
    def refresh_enter_btn(self):
        rc = (self.ui.RunCard_lineEdit.text() or "").strip().upper()
        wo = (self.ui.WO_lineEdit.text() or "").strip()
        sn = (self.ui.SN_lineEdit.text() or "").strip()
        op = (self.ui.OP_lineEdit.text() or "").strip()

        mode = self.detect_mode(rc)

        if mode == "RD":
            ok = bool(rc.startswith("RD"))
        elif mode == "OFFLINE":
            ok = bool(rc == "0" and wo and op and len(sn) == SN_LEN_OFFLINE)
        else:
            ok = bool(rc and wo and op and len(sn) == SN_LEN_MES)

        self.ui.mes_ent_btn.setEnabled(ok)

    # ---------- UI：顯示 MES 查詢摘要（不寫測試 log） ----------
    def _show_mes_query_summary(self, res, runcard):
        self.mes_ui_only("=== MES查詢結果（摘要） ===")
        self.mes_ui_only(f"流程卡: {runcard}")
        self.mes_ui_only(f"工單  : {res.get('wo','')}")
        self.mes_ui_only(f"品號  : {res.get('pn','')}")
        self.mes_ui_only(f"站別  : {res.get('process_name','')}")
        self.mes_ui_only(f"數量  : {res.get('qty','')}")
        self.mes_ui_only(f"狀態  : {res.get('status','')}")
        self.mes_ui_only(f"MSG   : {res.get('msg','')}")
        self.mes_ui_only("==========================")

        # 如需在 UI 顯示完整 JSON（仍不寫測試 log）
        raw = res.get("raw")
        if raw is not None:
            try:
                pretty = json.dumps(raw, indent=2, ensure_ascii=False) # 美化 JSON
            except Exception:
                pretty = str(raw)
            self.mes_ui_only("【MES查詢結果 JSON】")
            self.mes_ui_only(pretty)

    # ---------- 進站邏輯（按下按鈕） ----------
    def on_enter_clicked(self):
        rc  = self.ui.RunCard_lineEdit.text().strip().upper()
        wo  = self.ui.WO_lineEdit.text().strip()
        sn  = self.ui.SN_lineEdit.text().strip()
        op  = self.ui.OP_lineEdit.text().strip()

        self.mode = self.detect_mode(rc)

        # 準備 log 目錄（但不立即建立 log 檔案，等開始測試時再建立）
        if self.mode == "RD":
            log_dir = "RD_TEST"
        elif wo:
            log_dir = wo
        else:
            log_dir = "logs"

        # 不立即建立 log 檔案，只準備參數
        # log 檔案將在開始測試時與 JSON/CSV 一起產生
        self.useing_logger = None
        self.log_file = None
        
        # 測試 log 的首行摘要（只顯示在 UI，不寫入檔案）
        header = f"流程卡：{rc} | 工單：{wo or ('RD_TEST' if self.mode=='RD' else wo)} | SN: {sn or 'NA'} | 工號：{op or 'NA'} | 模式：{self.mode}"
        self.mes_ui_only(header)  # 改為只顯示在 UI，不寫入 log
        tool_version = "v2.0" # 測試工具版本

        # 把 log_dir / sn 傳給主視窗
        # self.result_cfg = {"log_dir": log_dir, "sn": sn or "NA"}
        # 傳給主視窗（RD 沒 SN 就用 'RD'）, 這裡是記錄流程卡等資訊的字典, 後續會傳給主視窗用
        # 注意：user_log_path 設為 None，讓 run_selected_tests 在開始測試時才建立 log 檔案
        # 這裡是記錄流程卡等資訊的字典, 後續會傳給主視窗用, 提供給MB_Test.py使用, 提供給Test_item.py使用
        self.result_cfg = {
            "log_dir": log_dir,
            "sn": sn or "RD",
            "user_log_path": None,  # 不預先建立 log 檔案，等開始測試時再建立
            "mes_info_meta": {
                "runcard": rc,
                "workorder": wo or "RD_TEST",
                "sn": sn or "NA",
                "operator": op or "NA",
                "mode": self.mode,
                "header": header,
                "tool_version": tool_version,
            }
        }

        # RD：直接略過 MES
        if self.mode == "RD":
            QMessageBox.information(self, "提示", "RD 模式：略過 MES。")
            # MB_Test()
            self.accept()
            return

        # OFFLINE：資料檢查，但不打 MES
        if self.mode == "OFFLINE":
            if not (wo and op and len(sn) == SN_LEN_OFFLINE):
                QMessageBox.critical(self, "錯誤", f"0 模式需輸入：工單、SN({SN_LEN_OFFLINE}碼)、工號")
                return
            QMessageBox.information(self, "提示", "OFFLINE 模式：資料已記錄，不進 MES。")
            # MB_Test()
            self.accept()
            return

        # AETINA / INNODISK：純 API 呼叫（不碰 UI、不寫測試 log；只寫 mes.log）
        try:
            # 你要集中稽核就用預設 mes.log；要跟工單一起放可傳 mes_log_path=os.path.join(log_dir, "mes.log")
            self.mes = MESClient(mode=self.mode)  # or MESClient(mode=self.mode, mes_log_path=os.path.join(log_dir, "mes.log"))

            qry = self.mes.query_api(rc)
            if not qry.get("ok"):
                self.mes_ui_only(f"[MES 查詢失敗] {qry.get('error') or qry.get('msg')}")
                QMessageBox.critical(self, "錯誤", f"MES 查詢失敗：{qry.get('error') or qry.get('msg')}")
                return

            # 只在 UI 顯示 MES 摘要與 JSON（不寫測試 log）
            self._show_mes_query_summary(qry, rc) # 顯示在 UI, qry 是查詢結果, rc 是流程卡

            process_name = qry.get("process_name", "")
            ent = self.mes.enter_api(rc, sn, process_name, op)
            if ent.get("ok"):
                # 不寫測試 log；只顯示 UI
                self.mes_ui_only(f"[進站成功] 流程卡：{rc}, SN: {sn}, 站別: {process_name}, 員工號: {op}")
                QMessageBox.information(self, "成功", "進站成功")
                # MB_Test()

                # ★ 把站別帶給主程式（MB_Test.py 需要用它來離站）
                self.result_cfg["mes_info_meta"]["process_name"] = process_name
                self.accept()
            else:
                self.mes_ui_only(f"[進站失敗] RESULT={ent.get('result') or ent.get('error')}")
                QMessageBox.critical(self, "錯誤", "進站失敗")

        except Exception as e:
            self.mes_ui_only(f"[MES 例外] {e}")
            QMessageBox.critical(self, "例外", f"MES 發生錯誤：\n{e}")

# ===== 進入點 =====
if __name__ == "__main__":
    import sys
    # app = QtWidgets.QApplication(sys.argv) # 建立應用程式
    # dlg = LoginDialog() # 建立對話框
    # dlg.exec_() # 顯示對話框
    app = QtWidgets.QApplication(sys.argv)
    dlg = LoginDialog()

    if dlg.exec_() == QtWidgets.QDialog.Accepted:           # ← 1) 只在按下「進站成功」時
        cfg = dlg.result_cfg or {}                          # ← 2) 取出對話框準備好的參數
        win = MB_Test(cfg)                                  # ← 3) 建立你的主視窗（mbtest_run）
        # 如果 MB_Test() 裡面沒有呼叫 show()，就手動補一行：
        # win.show()
        sys.exit(app.exec_())                               # ← 4) 進入主事件圈
    else:
        sys.exit(0)
