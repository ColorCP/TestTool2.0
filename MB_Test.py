# # from PyQt5 import QtWidgets, QtCore
# # from PyQt5.QtWidgets import QMessageBox
# # # from ui_testtool import Ui_meslogin_Dialog   # 你的 .ui 轉出的檔案
# # from ui_mbtest import Ui_MBWindow
# # import os, json, logging
# # from datetime import datetime

# # def mbtest_run():
# #     print("MB Test is running...")

# # # ===== 進入點 =====
# # if __name__ == "__main__":
# #     mbtest_run()

# MB_Test.py
from PyQt5 import QtWidgets, uic
from ui_mbtest import Ui_MBWindow
from ui_Manual_test import Ui_Manual_Test_iTem_Dialog
# from ui_other_setting import Ui_Other_Setting_Dialog
from PyQt5.QtCore import QTimer, QTime
import json, subprocess, re, os, glob, pathlib, time, configparser
from PyQt5.QtWidgets import QMessageBox, QDialog, QCheckBox, QLCDNumber
from Test_item import run_selected_tests, build_mes_testlog, mes_post, set_current_window, TEST_ITEMS
# from pathlib import Path
import logging
import resources_rc # 這行是為了讓 Qt 資源檔生效
from PyQt5.QtGui import QPixmap, QIntValidator, QRegExpValidator
from PyQt5.QtCore import Qt, QRegExp
from datetime import datetime, date
from ftplib import FTP, error_perm
from mes_api import MESClient
import shutil
import yaml
import toml


# from urllib.parse import urlparse, unquote

# --- 手動項目對話框 ---
class ManualItemsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Manual_Test_iTem_Dialog()
        self.ui.setupUi(self)  # 一定要呼叫 setupUi()
        # uic.loadUi("ui_Manual_test.ui", self)
        if hasattr(self.ui, "buttonBox"):
            self.ui.buttonBox.accepted.connect(self.accept)
            self.ui.buttonBox.rejected.connect(self.reject)

    def _all_cbs(self):
        return self.findChildren(QCheckBox)

    def checked_items(self):
        return [cb.text() for cb in self._all_cbs() if cb.isChecked()]

    def set_checked(self, names):
        want = set(names or [])
        for cb in self._all_cbs():
            cb.setChecked(cb.text() in want)
            
class MBTestWindow(QtWidgets.QMainWindow):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        # uic.loadUi("ui_mbtest.ui", self)   # ← 用檔名載入
        self.ui = Ui_MBWindow()  # ← 用類別載入
        self.ui.setupUi(self)    # ← 一定要呼叫 setupUi()
        # print([(w.objectName(), w.text()) for w in self.findChildren(QCheckBox)]) # 印出所有 checkbox 的名稱和文字 debug use
        # self.setupUi(self)

        self.cfg = cfg or {} # 設定檔

        # 跟 TestTool2.0.py 一樣：不指定 mes_log_path，預設寫 ./mes.log
        self.mes = MESClient(mode=self.cfg.get("meta", {}).get("mode", "RD"))

        # 把自己丟給 Test_item
        set_current_window(self)

        self.wo = (self.cfg.get("meta", {}).get("workorder") or self.cfg.get("wo") or "").strip()
        if self.wo and hasattr(self.ui, "WO_lineEdit"):
            self.ui.WO_lineEdit.setText(self.wo)
            self.ui.WO_lineEdit.setEnabled(False)

        # 讓程式知道目前選了哪些手動項目
        self.manual_selected = [] # 這裡存放對話框勾選的名字，例如 ["USB","Network"]

        self.setWindowTitle("MB Test Tool v2.0")
        self.setFixedSize(self.size())  # 固定視窗大小

        pm = QPixmap(":/img/aetina.png")
        if pm.isNull():
            print("Pixmap is NULL – 檢查 resources_rc、qrc 路徑、大小寫")
        else:
            self.ui.logo_label.setPixmap(
                pm.scaled(self.ui.logo_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        # Button connections
        self.ui.Button_Start_Test.clicked.connect(self.start_test)
        self.ui.Button_Upload.clicked.connect(self.log_upload)
        # self.ui.Button_Manual_Test.clicked.connect(self.manual_test)
        # 只全選/全清『自動測項』
        self.ui.Button_iTem_Select.clicked.connect(lambda: self.select_all_items(False))
        self.ui.Button_iTem_Clean.clicked.connect(lambda: self.clean_all_items(False))
        # 在這裡綁定 ToolButton 點擊事件, 按下combobox 旁的按鈕會彈出對話框
        self.ui.gpio_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.GPIO_setting_groupBox, "GPIO 設定")
        )
        self.ui.eeprom_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.EEPROM_setting_groupBox, "EEPROM 設定")
        )
        self.ui.fan_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.Fan_setting_groupBox, "FAN 設定")
        )
        self.ui.network_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.IP_setting_groupBox, "Network 設定")
        )
        self.ui.rs232_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.RS232_setting_groupBox, "RS232 設定")
        )
        self.ui.rs422_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.RS422_setting_groupBox, "RS422 設定")
        )
        self.ui.rs485_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.RS485_setting_groupBox, "RS485 設定")
        )
        self.ui.ekey_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.Ekey_setting_groupBox, "E-Key 設定")
        )
        self.ui.i2c_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.i2c_setting_groupBox, "I2C 設定")
        )
        self.ui.uart_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.UART_setting_groupBox, "UART 設定")
        )
        self.ui.spi_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.SPI_setting_groupBox, "SPI 設定")
        )

        # 如果想另外提供「同時包含人工判斷項目」的版本，可以再加兩顆或用右鍵選單：
        # self.Button_Select_All_Both.clicked.connect(lambda: self.select_all_items(True))
        # self.Button_Clean_All_Both.clicked.connect(lambda: self.clean_all_items(True))

        # ① 一次性填靜態資訊
        info = self.board_info()
        # 直接用屬性（objectName 要對）
        self.ui.valBoardVendor.setText(info["vendor"] or "-")
        self.ui.valBoardName.setText(info["name"] or "-")
        self.ui.valBoardSerial.setText(info["serial"] or "-")
        self.ui.valBiosVersion.setText(info["bios_version"] or "-")
        self.ui.valBiosVendor.setText(info["bios_vendor"] or "-")
        self.ui.valCPUName.setText(next((ln.split(":",1)[1].strip() for ln in subprocess.check_output(["lscpu"], text=True).splitlines() if ln.lower().startswith(("model name","hardware"))), "-"))
        mem = self.mem_slot_sizes_for_ui(4) # 取前 4 個
        self.ui.valMEM1.setText(mem[0])
        self.ui.valMEM2.setText(mem[1])
        self.ui.valMEM3.setText(mem[2])
        self.ui.valMEM4.setText(mem[3])
        self.all_mac_addresses()  # 填 MAC1..MAC6

        # ② 每秒更新動態資訊
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_dynamic)
        self._timer.start(1000)


        # === FTP 目標：預設值 + 綁定 radio 事件 ===
        self.cfg.setdefault("ftp_target", "")  # "", "PD1", "PD2", "PD3"

        rb1 = getattr(self.ui, "PD1_FTP_radioButton", None) # 避免屬性不存在報錯
        rb2 = getattr(self.ui, "PD2_FTP_radioButton", None)
        rb3 = getattr(self.ui, "PD3_FTP_radioButton", None)
        if rb1: rb1.toggled.connect(lambda checked: checked and self.set_ftp_target("PD1")) # 只在config變更時觸發, 避免無限迴圈
        if rb2: rb2.toggled.connect(lambda checked: checked and self.set_ftp_target("PD2"))
        if rb3: rb3.toggled.connect(lambda checked: checked and self.set_ftp_target("PD3"))


        # 先載入三種設定檔，把 self.cfg 填滿
        # self.load_ini_into_cfg()   # ./mb_test_config.ini
        # self.load_yaml_cfg()       # ./mb_test_config.yaml
        self.load_toml_cfg()       # ./mb_test_config.toml

        # 接著設定輸入限制（驗證器）
        self.init_config_tab_validators()

        # 把 self.cfg 的值回填到 UI
        self.apply_tomlcfg_to_ui()

        # # 最後才綁定各勾選開關，並依目前勾選狀態更新 UI
        # self.bind_all_feature_toggles()

        # === 綁定「儲存設定」按鈕 ===
        if hasattr(self.ui, "config_save_buttonBox"):
            self.ui.config_save_buttonBox.accepted.connect(self.on_config_save)
            self.ui.config_save_buttonBox.rejected.connect(self.on_config_cancel)

    # ===== Control Setting Tab 按下 Combobox 旁邊的按鈕就會跳出要設定的視窗 =====
    def popout_group_as_dialog(self, group: QtWidgets.QGroupBox, title="設定"):
        """把分頁裡的 groupBox 暫時搬出成 Dialog"""
        orig_parent = group.parentWidget() # 記住原本的父元件
        orig_layout = orig_parent.layout() # 記住原本的 layout
        idx = orig_layout.indexOf(group) #  記住原本的位置

        placeholder = QtWidgets.QWidget(orig_parent) # 放一個空的 placeholder 佔位
        placeholder.setFixedSize(group.size()) # 設定大小跟 group 一樣
        orig_layout.replaceWidget(group, placeholder) # 把 group 換掉

        group.setParent(None) # 暫時把 group 從原本的父元件拿掉, 不然會報錯
        dlg = QtWidgets.QDialog(self) # 創建對話框
        dlg.setWindowTitle(title) # 設定標題
        v = QtWidgets.QVBoxLayout(dlg) # 設定對話框的 layout
        v.addWidget(group) # 把 group 加進對話框

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        ) # 加上 OK/Cancel 按鈕
        v.addWidget(btns) # 把按鈕加進 layout
        btns.accepted.connect(dlg.accept) # 連接按鈕事件
        btns.rejected.connect(dlg.reject) # 連接按鈕事件

        try:
            dlg.exec_() # 執行對話框
        finally:
            group.setParent(orig_parent) # 把 group 放回原本的父元件
            orig_layout.replaceWidget(placeholder, group) # 把 placeholder 換回 group
            placeholder.deleteLater() # 刪除 placeholder
            group.show() # 顯示 group
    # ===== Control Setting Tab =====

    # 設定 Config 分頁, 限制欄位輸入的內容
    def init_config_tab_validators(self):

        # FAN
        for i in range(1, 6):
            t = getattr(self.ui, f"FAN{i}_Time_lineEdit", None)
            # p = getattr(self.ui, f"FAN{i}_PWM_lineEdit", None)
            low = getattr(self.ui, f"FAN{i}_LOW_speed_lineEdit", None)
            high = getattr(self.ui, f"FAN{i}_HIGH_speed_lineEdit", None)
            tol = getattr(self.ui, f"FAN{i}_Tolerance_lineEdit", None)
            # rpm = getattr(self.ui, f"FAN{i}_RPM_Path_lineEdit", None)
            fanp= getattr(self.ui, f"FAN{i}_FAN_Path_lineEdit", None)

            if t:   t.setValidator(QIntValidator(1, 600, self))
            # if p:   p.setValidator(QIntValidator(0, 100, self))
            if low: low.setValidator(QIntValidator(0, 100000, self))
            if high:high.setValidator(QIntValidator(0, 100000, self))
            if tol: tol.setValidator(QIntValidator(0, 100, self))
            # if rpm: rpm.setPlaceholderText("沒輸入RPM則為手動測試") # 顯示在輸入框內的提示文字
            if fanp:fanp.setPlaceholderText("/sys/class/hwmon/hwmonX/pwmY") # 顯示在輸入框內的提示文字

        # EEPROM
        if hasattr(self.ui, "BUS_lineEdit"):
            self.ui.BUS_lineEdit.setValidator(QIntValidator(0, 32, self)) # 0~32
        if hasattr(self.ui, "Addre_lineEdit"):
            self.ui.Addre_lineEdit.setValidator(QRegExpValidator(QRegExp(r"^(0x)?[0-9a-fA-F]{1,2}$"), self)) # 0x00~0xFF
        if hasattr(self.ui, "GPIO_NUM_lineEdit"):
            self.ui.GPIO_NUM_lineEdit.setValidator(QIntValidator(0, 1000, self)) # 0~1000
        if hasattr(self.ui, "GPIO_PIN_lineEdit"):
            self.ui.GPIO_PIN_lineEdit.setValidator(QRegExpValidator(QRegExp(r"^[A-Z]{1,3}\.\d{1,2}$"), self))  # 例如 PEE.06

    def read_combo_int(self, *widget_names, default=0):
        """依序嘗試以 objectName 取得 combobox，讀取 currentText 並轉 int。"""
        for name in widget_names:
            w = getattr(self.ui, name, None)
            if w and hasattr(w, "currentText"):
                try:
                    return int(w.currentText()) # 嘗試轉 int
                except Exception:
                    pass
        return default

    def save_serial_section(self, data: dict, prefix: str, count: int):
        """
        儲存 RS232/RS422/RS485 等combobox 類型設定。
        prefix: "RS232" / "RS422" / "RS485"
        count:  下拉選單的期望數量
        """
        cfg = {"expect": count}

        # 若 count > 0，依序取 UI 欄位
        if count > 0:
            for i in range(1, count + 1): # 從 1 開始到 count
                le = getattr(self.ui, f"{prefix.lower()}_{i}_lineEdit", None) # 例如 rs232_1_lineEdit
                if not le: # 找不到元件就跳過
                    continue # 繼續下一個迴圈
                val = (le.text() or "").strip() # 取得文字並去除空白
                if val: # 有填值才加入 cfg
                    cfg[f"{prefix}_port_{i}"] = val # 例如 RS232_port_1

        # 只有有資料時才寫入，否則刪掉舊資料
        if count > 0 and len(cfg) > 1:
            data[prefix] = cfg
        else:
            data.pop(prefix, None)

    def save_ekey_section(self, data: dict, prefix: str, count: int):
        """
        存 [E-Key] 區段，欄位名稱用 EKEY_PATH_#
        prefix 目前其實用不到，但保留參數方便之後改
        """
        # 如果 combobox 選 0，就直接把舊的 E-Key 刪掉，不寫入
        if count <= 0:
            data.pop("E-Key", None)
            return

        sec = {"expect": count}
        has_item = False

        for i in range(1, count + 1):
            le = getattr(self.ui, f"ekey_{i}_lineEdit", None)
            if not le:
                continue
            txt = le.text().strip()
            if txt:
                sec[f"EKEY_PATH_{i}"] = txt
                has_item = True

        # 只有當有至少一個 PATH 時才寫入，否則也刪掉
        if has_item:
            data["E-Key"] = sec
        else:
            data.pop("E-Key", None)

    def save_multi_port_section(self, data, toml_func_name, ui_name, toml_func_path_name, count):
        """
        通用版本：
        專門給 E-Key / RS232 / RS422 / RS485 / UART 用
        - UI 物件： <ui_name>_<i>_lineEdit
        - TOML Key：<toml_func_path_name>_<i>
        例如：
        RS232 → ui_name="rs232" 後續程式會帶入組合名稱出來, toml_func_path_name="RS232_port"
        E-Key → ui_name="ekey" 後續程式會帶入組合名稱出來, toml_func_path_name="EKEY_PATH"
        """
        if count <= 0:
            data.pop(toml_func_name, None)
            return

        sec = {"expect": count}
        has_item = False

        for i in range(1, count + 1):
            # UI 物件名稱（通常小寫）
            le = getattr(self.ui, f"{ui_name}_{i}_lineEdit", None)
            if not le:
                continue
            txt = (le.text() or "").strip()
            if txt:
                # TOML 欄位名稱（通常大寫 + _port or _PATH）
                sec[f"{toml_func_path_name}_{i}"] = txt
                has_item = True

        if has_item:
            data[toml_func_name] = sec
        else:
            data.pop(toml_func_name, None)

    def save_toml_cfg(self, path="./mb_test_config.toml"):
        """
        直接從 UI 抓所有設定，組成 dict 並：
        1) 清空並更新 self.cfg
        2) 寫入 TOML 檔案
        3) 回傳 data（給呼叫端顯示/調用）
        """
        # import toml, re  # ← 需要 re 給 parse_hex 用

        def parse_hex(s, default=0x55):
            s = (s or "").strip()
            try:
                if s.lower().startswith("0x"):
                    return int(s, 16)
                elif re.fullmatch(r"[0-9a-fA-F]{1,2}", s):
                    return int(s, 16)
                else:
                    return int(s)
            except Exception:
                return default

        data = {} # 最終要寫入 toml 的 dict, 裡面存著toml 各區段的設定

        # ===== USB2 =====  (與測項 toml_get("USB2", ...) 對齊)
        usb2_expect = self.read_combo_int("usb2_comboBox", default=0)
        if usb2_expect > 0:
            data["USB2"] = {"expect": usb2_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== USB3 =====  (與測項 toml_get("USB3", ...) 對齊)
        usb3_expect = self.read_combo_int("usb3_comboBox", default=0)
        if usb3_expect > 0:
            data["USB3"] = {"expect": usb3_expect}

        # ===== M-Key =====
        mkey_expect = self.read_combo_int("MKEY_comboBox", default=0)
        if mkey_expect > 0:
            data["M-Key"] = {"expect": mkey_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== E-Key =====
        ekey_expect = self.read_combo_int("EKEY_comboBox", default=0)
        self.save_multi_port_section(data, "E-Key", "ekey", "EKEY_PATH", ekey_expect)

        # ===== Network =====
        network_expect = self.read_combo_int("network_comboBox", default=0)
        if network_expect > 0:
            ip = (getattr(self.ui, "IP_lineEdit", None).text() or "").strip()
            data["Network"] = {"expect": network_expect}
            if ip:
                data["Network"]["ping_ip"] = ip
        else:
            data.pop("Network", None)

        # ===== Micro SD =====
        microsd_expect = self.read_combo_int("microsd_comboBox", default=0)
        if microsd_expect > 0:
            data["Micro SD Card"] = {"expect": microsd_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== RS232 =====
        rs232_expect = self.read_combo_int("RS232_comboBox", default=0)
        self.save_multi_port_section(data, "RS232", "rs232", "RS232_port", rs232_expect)

        # ===== RS422 =====
        rs422_expect = self.read_combo_int("RS422_comboBox", default=0) # 這行的功能是讀取 combobox 的值並轉成 int
        self.save_multi_port_section(data, "RS422", "rs422", "RS422_port", rs422_expect) # 如果期望數量大於0, 就依序取 UI 欄位, 寫入 data dict 裡面, 否則刪掉舊資料, 寫入 toml 檔案, 回傳 data dict 給呼叫端顯示/調用

        # ===== RS485 =====
        rs485_expect = self.read_combo_int("RS485_comboBox", default=0)
        self.save_multi_port_section(data, "RS485", "rs485", "RS485_port", rs485_expect)

        # ===== UART =====
        uart_expect = self.read_combo_int("uart_comboBox", default=0)
        self.save_multi_port_section(data, "UART", "uart", "UART_path", uart_expect)

        # ===== SPI =====
        spi_expect = self.read_combo_int("spi_comboBox", default=0)
        self.save_multi_port_section(data, "SPI", "spi", "SPI_path", spi_expect)

        # 補上 precmd
        precmd_le = getattr(self.ui, "spi_precmd_lineEdit", None) # 從 ui 取得 precmd 元件
        if precmd_le: # 如果元件存在
            precmd = precmd_le.text().strip() # 從 ui 取得 precmd 元件上的值並去除空白
            if precmd: # 有填值才加入 cfg
                spi_cfg = data.get("SPI") # 從toml 取得 SPI 區段裡找到 precmd 的值
                if spi_cfg is None: # 如果toml 的spi 是空的
                    spi_cfg = {} # 用來建立一個新的 [SPI] 區段
                    data["SPI"] = spi_cfg # 把新的 [SPI] 區段放回 data 裡面
                spi_cfg["precmd"] = precmd # 把 precmd 寫入 toml 的 SPI 區段

        # ===== FAN =====
        fan_expect = self.read_combo_int("fan_comboBox", default=0)

        fan_items = []
        def _txt(w):
            return (w.text().strip() if w else "")

        def _int(w, default=0):
            try:
                return int(_txt(w) or default)
            except Exception:
                return default

        for i in range(1, fan_expect + 1):
            t    = getattr(self.ui, f"FAN{i}_Time_lineEdit", None)
            # p    = getattr(self.ui, f"FAN{i}_PWM_lineEdit", None)
            # rpm  = getattr(self.ui, f"FAN{i}_RPM_Path_lineEdit", None)
            fpth = getattr(self.ui, f"FAN{i}_FAN_Path_lineEdit", None)
            low  = getattr(self.ui, f"FAN{i}_LOW_speed_lineEdit", None)
            high = getattr(self.ui, f"FAN{i}_HIGH_speed_lineEdit", None)
            tol  = getattr(self.ui, f"FAN{i}_Tolerance_lineEdit", None)
            man  = getattr(self.ui, f"FAN{i}_people_checkBox", None) # 如果打勾，測試需人工確認

            item = {
                "fan_id":    i, # 從 1 開始編號
                "seconds":   _int(t, 10), # 秒數
                # "pwm":       _int(p, 50), # PWM 百分比
                # "rpm_path":  _txt(rpm), # RPM 讀取路徑
                "fan_path":  _txt(fpth), # 風扇控制路徑
                "low":       _int(low, 0), # 低速 RPM
                "high":      _int(high, 0), # 高速 RPM
                "tolerance": _int(tol, 10), # 容差
                "manual":    (man.isChecked() if man else False), # 是否人工確認
            }
            fan_items.append(item)

        if fan_expect > 0:
            data["FAN"] = {
                "expect": fan_expect,
                "items": fan_items
            }
        else:
            data.pop("FAN", None)

        # ===== EEPROM =====
        eeprom_expect = self.read_combo_int("eeprom_comboBox", default=0)
        if eeprom_expect > 0:
            data["EEPROM"] = {"expect": eeprom_expect}

        if eeprom_expect > 0:
            eeprom_bus        = int((getattr(self.ui, "BUS_lineEdit", None).text() or "7"))
            eeprom_addr       = parse_hex((getattr(self.ui, "Addre_lineEdit", None).text() or "0x55"))
            eeprom_gpio_num   = int((getattr(self.ui, "GPIO_NUM_lineEdit", None).text() or "345"))
            eeprom_gpio_pin   = (getattr(self.ui, "GPIO_PIN_lineEdit", None).text() or "PEE.06").strip()
            eeprom_pn         = (getattr(self.ui, "PN_lineEdit", None).text() or "").strip()
            eeprom_board_name = (getattr(self.ui, "Board_NAME_lineEdit", None).text() or "").strip()
            eeprom_board_rev  = (getattr(self.ui, "Board_Revision_lineEdit", None).text() or "").strip()
            data["EEPROM"] = {
                "expect": eeprom_expect,
                # "enabled": True,
                "eeprom_i2c_bus":        eeprom_bus,
                "eeprom_i2c_addr":       f"0x{eeprom_addr:02X}",
                "eeprom_gpio_write_num": eeprom_gpio_num,
                "eeprom_gpio_write_pin": eeprom_gpio_pin,
                "pn":                    eeprom_pn,
                "board_name":            eeprom_board_name,
                "board_revision":        eeprom_board_rev,
            }

        # ===== EEPROM RD Test =====
        eeprom_rd_expect = self.read_combo_int("eeprom_RD_Test_comboBox", default=0)
        if eeprom_rd_expect > 0:
            data["EEPROM RD TEST"] = {"expect": eeprom_rd_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== I2C 設定 =====
        i2c_expect = self.read_combo_int("i2c_comboBox", default=0) # 這行的功能是讀取 combobox 的值並轉成 int
        if i2c_expect > 0: # 如果期望數量大於0
            # data["I2C"] = {"expect": i2c_expect} # 這裡[]內的名稱會寫入 TOML
        
            pairs = []
            for i in range(1, i2c_expect + 1):
                bus    = getattr(self.ui, f"i2c_bus{i}_lineEdit", None)
                addr   = getattr(self.ui, f"i2c_addr{i}_lineEdit", None)
                offset = getattr(self.ui, f"i2c_offset{i}_lineEdit", None)

                bus_txt    = bus.text().strip()    if bus else ""
                addr_txt   = addr.text().strip()   if addr else ""
                offset_txt = offset.text().strip() if offset else ""

                if bus_txt or addr_txt or offset_txt:
                    pairs.append(f"{bus_txt},{addr_txt},{offset_txt}")

            # 這裡[]內的名稱會寫入 TOML 是測項名稱, 包含 expect 和 pairs會一起寫入
            data["I2C"] = {
                "expect": i2c_expect,
                "pairs": pairs,
            }

        # ===== GPIO =====
        gpio_expect = self.read_combo_int("gpio_comboBox", default=0)

        if gpio_expect > 0:

            pairs = []
            for i in range(1, gpio_expect + 1):

                gpo_num = getattr(self.ui, f"GPO_num{i}_lineEdit", None) # 這行功能是取得 GPO_numX_lineEdit 物件
                gpo_pin = getattr(self.ui, f"GPO_pin{i}_lineEdit", None)
                gpi_num = getattr(self.ui, f"GPI_num{i}_lineEdit", None)
                gpi_pin = getattr(self.ui, f"GPI_pin{i}_lineEdit", None)

                gpo_num_txt = gpo_num.text().strip() if gpo_num else "" # 這行功能是取得 GPO_numX_lineEdit 的文字並去除空白
                gpo_pin_txt = gpo_pin.text().strip() if gpo_pin else ""
                gpi_num_txt = gpi_num.text().strip() if gpi_num else ""
                gpi_pin_txt = gpi_pin.text().strip() if gpi_pin else ""

                if gpo_num_txt or gpo_pin_txt or gpi_num_txt or gpi_pin_txt:
                    pairs.append(f"{gpo_num_txt},{gpo_pin_txt},{gpi_num_txt},{gpi_pin_txt}")

            data["GPIO"] = {
                "expect": gpio_expect,
                "pairs": pairs,
            }
        else:
            data.pop("GPIO", None)

        # ===== 通用測項保存邏輯 =====
        # key: TOML 區塊名稱, value: UI comboBox 物件名稱, 此次部份僅提供手動測試comboBox項目整合, 如果comboBox的值大於0就存入 data
        combo_map = {
            "HDMI": "hdmi_comboBox",
            "VGA": "vga_comboBox",
            "DP": "dp_comboBox",
            "LED": "led_comboBox",
            "POWER CONNECTOR": "power_connector_comboBox",
            "POWER SW CONNECTOR": "power_sw_connector_comboBox",
            "POWER BUTTON": "power_button_comboBox",
            "RESET BUTTON": "reset_button_comboBox",
            "RECOVERY BUTTON": "recovery_button_comboBox",
            "SMA": "sma_comboBox",
            "SW1": "sw1_comboBox",
            "SW2": "sw2_comboBox",
            "MCU Connector": "mcu_connector_comboBox",
            "RTC": "rtc_comboBox",
            "RTC OUT": "rtc_out_comboBox",
            "DC INPUT": "dc_input_comboBox",
            "DC OUTPUT": "dc_output_comboBox"
        }

        # 依序讀取 combo 並存入 data
        for section, combo_name in combo_map.items():
            val = self.read_combo_int(combo_name, default=0)
            if val > 0:
                data[section] = {"expect": val}

        self.ui.Information_textEdit.append(f"[DEBUG] Save TOML data: {data}")


        # # ===== HDMI ===== 獨立撰寫範例
        # hdmi_expect = self.read_combo_int("hdmi_comboBox", default=0)
        # if hdmi_expect > 0:
        #     data["HDMI"] = {"expect": hdmi_expect}
        # self.ui.Information_textEdit.append(f"[DEBUG] Save TOML data: {data}")

        # ===== FTP =====
        target = self.get_ftp_target_from_ui() or self.cfg.get("ftp_target", "")
        if target:
            data["FTP"] = {"target": target}

        # ===== 同步記憶體 cfg（避免殘留舊鍵） =====
        self.cfg.clear()
        self.cfg.update(data)

        # 在這裡加上 rename 區段的轉換, 目前診針對 EKEY -> E-KEY
        if "EKEY" in data:
            data["E-Key"] = data.pop("EKEY")

        # ===== 寫入 TOML 檔 =====
        with open(path, "w", encoding="utf-8") as f:
            toml.dump(data, f)

        self.ui.Information_textEdit.append(f"[設定檔已儲存] {path}")
        return data
    
    # 把 self.cfg 的值回填到 Config 分頁
    def apply_tomlcfg_to_ui(self):
        """把 self.cfg 的值回填到 Config 分頁。"""
        item_cfg = self.cfg
        # print(f"Applying cfg to UI: {c}") # debug use
        # print(c) # debug use

        # ---- 讀取 cfg 區段 ----
        # ===== 自動測項 =====
        usb2                = item_cfg.get("USB2", {}) # 這是 TOML 的區段名稱, 功能主要是記錄預期數量, 名稱改成 USB2/USB3需要與 save_toml_cfg 對應, 名稱會存入TOML
        usb3                = item_cfg.get("USB3", {})
        mkey                = item_cfg.get("M-Key", {})
        ekey                = item_cfg.get("E-Key", {})
        network             = item_cfg.get("Network", {})
        rs232               = item_cfg.get("RS232", {})
        rs422               = item_cfg.get("RS422", {})
        rs485               = item_cfg.get("RS485", {})
        uart                = item_cfg.get("UART", {})
        fan                 = item_cfg.get("FAN", {})
        eeprom              = item_cfg.get("EEPROM", {})
        eeprom_rd           = item_cfg.get("EEPROM RD TEST", {})
        gpio                = item_cfg.get("GPIO", {})
        sdcard              = item_cfg.get("Micro SD Card", {}) # 後面名稱要與toml相同
        i2c                 = item_cfg.get("I2C", {})
        spi                 = item_cfg.get("SPI", {})
        # ===== 手動測項 =====
        hdmi                = item_cfg.get("HDMI", {})
        vga                 = item_cfg.get("VGA", {})
        dp                  = item_cfg.get("DP", {})
        led                 = item_cfg.get("LED", {})
        power_btn           = item_cfg.get("POWER BUTTON", {})
        power_connector     = item_cfg.get("POWER CONNECTOR", {})
        power_sw            = item_cfg.get("POWER SW CONNECTOR", {})
        reset_btn           = item_cfg.get("RESET BUTTON", {})
        recovery_btn        = item_cfg.get("RECOVERY BUTTON", {})
        sma                 = item_cfg.get("SMA", {})
        sw1                 = item_cfg.get("SW1", {})
        sw2                 = item_cfg.get("SW2", {})
        mcu_connector       = item_cfg.get("MCU Connector", {})
        rtc                 = item_cfg.get("RTC", {})
        rtc_out             = item_cfg.get("RTC OUT", {})
        dc_input            = item_cfg.get("DC INPUT", {})
        dc_output           = item_cfg.get("DC OUTPUT", {})

        # ---- USB ----
        check_usb2 = getattr(self.ui, "checkBox_USB2", None) # 避免屬性不存在報錯
        combo_usb2 = getattr(self.ui, "usb2_comboBox", None)
        if check_usb2 and combo_usb2:
            if usb2 and int(usb2.get("expect", 0)) > 0:
                check_usb2.setChecked(True) # 勾選checkbox
                combo_usb2.setCurrentText(str(int(usb2.get("expect", 0)))) # 讀取數量, 並設定combobox
            else:
                check_usb2.setChecked(False) # 不勾選checkbox

        check_usb3 = getattr(self.ui, "checkBox_USB3", None)
        combo_usb3 = getattr(self.ui, "usb3_comboBox", None)
        if check_usb3 and combo_usb3:
            if usb3 and int(usb3.get("expect", 0)) > 0:
                check_usb3.setChecked(True)
                combo_usb3.setCurrentText(str(int(usb3.get("expect", 0))))
            else:
                check_usb3.setChecked(False)

        # --- M-Key ---
        check_mkey = getattr(self.ui, "checkBox_MKEY", None)
        combo_mkey = getattr(self.ui, "MKEY_comboBox", None)
        if check_mkey and combo_mkey:
            if mkey and int(mkey.get("expect", 0)) > 0:
                check_mkey.setChecked(True)
                combo_mkey.setCurrentText(str(int(mkey.get("expect", 0))))
            else:
                check_mkey.setChecked(False)

        # E-Key
        check_ekey = getattr(self.ui, "checkBox_EKEY", None)
        combo_ekey = getattr(self.ui, "EKEY_comboBox", None)
        if check_ekey and combo_ekey:
            if ekey and int(ekey.get("expect", 0)) > 0:
                check_ekey.setChecked(True)
                combo_ekey.setCurrentText(str(int(ekey.get("expect", 0))))
            else:
                check_ekey.setChecked(False)
        for i in range(1, 6):
            le = getattr(self.ui, f"ekey_{i}_lineEdit", None)
            if not le:
                continue
            val = ekey.get(f"EKEY_PATH_{i}", "")
            le.setText("" if val is None else str(val))

        # Network
        check_network = getattr(self.ui, "checkBox_NETWORK", None)
        combo_network = getattr(self.ui, "network_comboBox", None)
        if check_network and combo_network:
            if network and int(network.get("expect", 0)) > 0:
                check_network.setChecked(True)
                combo_network.setCurrentText(str(int(network.get("expect", 0))))
            else:
                check_network.setChecked(False)

            # if hasattr(self.ui, "checkBox_network"):
            #     self.ui.checkBox_network.setChecked(bool(network.get("enabled", True)))
            if hasattr(self.ui, "network_comboBox"):
                self.ui.network_comboBox.setCurrentText(str(int(network.get("expect", 0))))
            if hasattr(self.ui, "IP_lineEdit"):
                # 預設顯示 8.8.8.8，如果設定檔裡有 ping_ip 就覆蓋
                self.ui.IP_lineEdit.setText(network.get("ping_ip", "8.8.8.8"))

        # Micro SD
        check_sdcard = getattr(self.ui, "checkBox_MICROSD", None)
        combo_sdcard = getattr(self.ui, "microsd_comboBox", None)
        if check_sdcard and combo_sdcard:
            if sdcard and int(sdcard.get("expect", 0)) > 0:
                check_sdcard.setChecked(True)
                combo_sdcard.setCurrentText(str(int(sdcard.get("expect", 0))))
            else:
                check_sdcard.setChecked(False)

        # RS232
        check_rs232 = getattr(self.ui, "checkBox_RS232", None)
        combo_rs232 = getattr(self.ui, "RS232_comboBox", None)
        if check_rs232 and combo_rs232:
            if rs232 and int(rs232.get("expect", 0)) > 0:
                check_rs232.setChecked(True)
                combo_rs232.setCurrentText(str(int(rs232.get("expect", 0))))
            else:
                check_rs232.setChecked(False)

        # 依序回填 10 格 RS232_port
        for i in range(1, 11):
            rs232_port = f"RS232_port_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs232 = getattr(self.ui, f"rs232_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs232:
                continue
            get_rs232.setText(str(rs232.get(rs232_port, "")))

        # RS422
        check_rs422 = getattr(self.ui, "checkBox_RS422", None)
        combo_rs422 = getattr(self.ui, "RS422_comboBox", None)
        if check_rs422 and combo_rs422:
            if rs422 and int(rs422.get("expect", 0)) > 0:
                check_rs422.setChecked(True)
                combo_rs422.setCurrentText(str(int(rs422.get("expect", 0))))
            else:
                check_rs422.setChecked(False)

        # 依序回填 10 格 RS422_port
        for i in range(1, 11):
            rs422_port = f"RS422_port_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs422 = getattr(self.ui, f"rs422_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs422:
                continue
            get_rs422.setText(str(rs422.get(rs422_port, "")))


        # RS485
        check_rs485 = getattr(self.ui, "checkBox_RS485", None)
        combo_rs485 = getattr(self.ui, "RS485_comboBox", None)
        if check_rs485 and combo_rs485:
            if rs485 and int(rs485.get("expect", 0)) > 0:
                check_rs485.setChecked(True)
                combo_rs485.setCurrentText(str(int(rs485.get("expect", 0))))
            else:
                check_rs485.setChecked(False)

        # 依序回填 10 格 RS485_port
        for i in range(1, 11):
            rs485_port = f"RS485_port_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs485 = getattr(self.ui, f"rs485_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs485:
                continue
            get_rs485.setText(str(rs485.get(rs485_port, "")))

        # UART
        check_uart = getattr(self.ui, "checkBox_UART", None)
        combo_uart = getattr(self.ui, "uart_comboBox", None)
        if check_uart and combo_uart:
            if uart and int(uart.get("expect", 0)) > 0:
                check_uart.setChecked(True)
                combo_uart.setCurrentText(str(int(uart.get("expect", 0))))
            else:
                check_uart.setChecked(False)

        # 依序回填 10 格 UART_path
        for i in range(1, 11):
            uart_path = f"UART_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10, UART_path_1 ~ UART_path_10
            get_uart = getattr(self.ui, f"uart_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI, uart_6_lineEdit
            if not get_uart:
                continue
            get_uart.setText(str(uart.get(uart_path, "")))

        # SPI
        spi = item_cfg.get("SPI", {}) or {}

        check_spi = getattr(self.ui, "checkBox_SPI", None)
        combo_spi = getattr(self.ui, "spi_comboBox", None)
        if check_spi and combo_spi:
            exp = int(spi.get("expect", 0) or 0)
            check_spi.setChecked(exp > 0)
            if combo_spi.count() == 0:
                combo_spi.addItems([str(i) for i in range(0, 6)])
            idx = combo_spi.findText(str(exp))
            combo_spi.setCurrentIndex(idx if idx >= 0 else 0)

        # Pre cmd
        precmd_le = getattr(self.ui, "spi_precmd_lineEdit", None)
        if precmd_le:
            precmd_le.setText(str(spi.get("precmd", "")))

        # 路徑 1~5
        for i in range(1, 6):
            spi_key = f"SPI_path_{i}"
            le = getattr(self.ui, f"spi_{i}_lineEdit", None)
            if not le:
                continue
            le.setText(str(spi.get(spi_key, "")))


        # # 依序回填 5 格 SPI_path
        # for i in range(1, 6):
        #     key = f"SPI_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~5, SPI_path_1 ~ SPI_path_5
        #     le = getattr(self.ui, f"spi_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI, spi_1_lineEdit ~ spi_5_lineEdit
        #     if not le:
        #         continue
        #     le.setText(str(spi.get(key, ""))) # 回填文字
        for i in range(1, 6):
            spi_path = f"SPI_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~5, SPI_path_1 ~ SPI_path_5
            get_spi = getattr(self.ui, f"spi_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI, spi_1_lineEdit ~ spi_5_lineEdit
            if not get_spi:
                continue
            get_spi.setText(str(spi.get(spi_path, "")))

        # === FAN（通用：跟 USB/SD 一樣）===
        check_fan = getattr(self.ui, "checkBox_FAN", None)
        combo_fan = getattr(self.ui, "fan_comboBox", None)
        if check_fan and combo_fan:
            exp = int(fan.get("expect", 0) or 0)   # exp 是整數
            check_fan.setChecked(exp > 0)
            if exp > 0:
                combo_fan.setCurrentText(str(exp))
        else:
            # 沒有這兩個元件就什麼都不做（不要在這裡清勾選，避免誤觸）
            pass

        fan_cfg = fan or {}
        items = list(fan_cfg.get("items") or [])

        for i in range(1, 6):
            it = items[i-1] if i-1 < len(items) else {}

            def _set(name, val):
                w = getattr(self.ui, f"FAN{i}_{name}", None)
                if w and hasattr(w, "setText"):
                    w.setText("" if val is None else str(val))

            _set("Time_lineEdit",       it.get("seconds", ""))
            _set("FAN_Path_lineEdit",   it.get("fan_path", ""))
            _set("LOW_speed_lineEdit",  it.get("low", ""))
            _set("HIGH_speed_lineEdit", it.get("high", ""))
            _set("Tolerance_lineEdit",  it.get("tolerance", ""))

            # ★ 統一名稱：和 save_toml_cfg 讀取的一樣
            cb = getattr(self.ui, f"FAN{i}_people_checkBox", None)
            if cb:
                cb.setChecked(bool(it.get("manual", False)))

        # EEPROM
        check_eeprom = getattr(self.ui, "checkBox_EEPROM", None)
        combo_eeprom = getattr(self.ui, "eeprom_comboBox", None)
        if check_eeprom and combo_eeprom:
            if eeprom and int(eeprom.get("expect", 0)) > 0:
                check_eeprom.setChecked(True)
                combo_eeprom.setCurrentText(str(int(eeprom.get("expect", 0))))
            else:
                check_eeprom.setChecked(False)
        # if hasattr(self.ui, "EEPROM_enable_checkBox"):
        #     self.ui.EEPROM_enable_checkBox.setChecked(bool(eeprom.get("enabled", False)))
        if hasattr(self.ui, "BUS_lineEdit"):
            self.ui.BUS_lineEdit.setText(str(int(eeprom.get("bus", 7))))
        if hasattr(self.ui, "Addre_lineEdit"):
            self.ui.Addre_lineEdit.setText(hex(int(eeprom.get("addr", 0x55))))
        if hasattr(self.ui, "GPIO_NUM_lineEdit"):
            self.ui.GPIO_NUM_lineEdit.setText(str(int(eeprom.get("gpio_num", 345))))
        if hasattr(self.ui, "GPIO_PIN_lineEdit"):
            self.ui.GPIO_PIN_lineEdit.setText(str(eeprom.get("gpio_pin", "PEE.06")))
        if hasattr(self.ui, "PN_lineEdit"):
            self.ui.PN_lineEdit.setText(str(eeprom.get("pn", "")))
        if hasattr(self.ui, "Board_NAME_lineEdit"):
            self.ui.Board_NAME_lineEdit.setText(str(eeprom.get("board_name", "")))
        if hasattr(self.ui, "Board_Revision_lineEdit"):
            # self.ui.Board_Revision_lineEdit.setText(str(c.get("eeprom_board_revision", "")))
            self.ui.Board_Revision_lineEdit.setText(str(eeprom.get("board_revision", "")))

        # self.apply_eeprom_enabled(self.ui.EEPROM_enable_checkBox.isChecked()
        #                         if hasattr(self.ui, "EEPROM_enable_checkBox") else False)
        
        # EEPROM RD Test
        check_eeprom_rd = getattr(self.ui, "checkBox_EEPROM_RD", None)
        combo_eeprom_rd = getattr(self.ui, "eeprom_RD_Test_comboBox", None)
        if check_eeprom_rd and combo_eeprom_rd:
            if eeprom_rd and int(eeprom_rd.get("expect", 0)) > 0:
                check_eeprom_rd.setChecked(True)
                combo_eeprom_rd.setCurrentText(str(int(eeprom_rd.get("expect", 0))))
            else:
                check_eeprom_rd.setChecked(False)

        # ===== I2C 設定（BUS / Address / Offset）=====
        i2c = item_cfg.get("I2C", {}) or {}

        check_i2c = getattr(self.ui, "checkBox_I2C", None)
        combo_i2c = getattr(self.ui, "i2c_comboBox", None)
        if check_i2c and combo_i2c:
            if i2c and int(i2c.get("expect", 0)) > 0:
                check_i2c.setChecked(True)
                combo_i2c.setCurrentText(str(int(i2c.get("expect", 0))))
            else:
                check_i2c.setChecked(False)

        pairs = i2c.get("pairs", []) or []
        
        for i, line in enumerate(pairs, start=1):
            parts = [x.strip() for x in line.split(",")] + ["", "", ""]
            bus, addr, offset = parts[:3]

            w_bus    = getattr(self.ui, f"i2c_bus{i}_lineEdit", None)
            w_addr   = getattr(self.ui, f"i2c_addr{i}_lineEdit", None)
            w_offset = getattr(self.ui, f"i2c_offset{i}_lineEdit", None)

            if w_bus:    w_bus.setText(bus)
            if w_addr:   w_addr.setText(addr)
            if w_offset: w_offset.setText(offset)

        # GPIO
        # ===== GPIO（啟用 + 期望數量 + 回填 pairs）=====
        check_gpio = getattr(self.ui, "checkBox_GPIO", None)
        combo_gpio = getattr(self.ui, "gpio_comboBox", None)
        gpio = item_cfg.get("GPIO", {}) or {}

        # --- 啟用 + combobox ---
        if check_gpio and combo_gpio:
            # 確保 combobox 有選項（例如 0~32，可自行調整）
            if combo_gpio.count() == 0:
                combo_gpio.addItems([str(i) for i in range(0, 33)])

            # 讀取期望數量
            exp = int(gpio.get("expect", 0) or 0)

            # checkbox：有設定且 > 0 才勾選
            check_gpio.setChecked(exp > 0)

            # combobox 設定當前值（如果找不到就設 0）
            idx = combo_gpio.findText(str(exp))
            combo_gpio.setCurrentIndex(idx if idx >= 0 else 0)

        # --- pairs 回填 ---
        gpio_pairs = list(gpio.get("pairs") or [])

        def _set_lineedit(name: str, val):
            w = getattr(self.ui, name, None)
            if not w:
                return
            try:
                w.setText("" if val is None else str(val))
            except Exception:
                # 保險一點，即使不是 QLineEdit 也不會炸
                pass

        row = 1
        while True:
            # 沒有這個 GPO_numX_lineEdit 就當作結束
            if not getattr(self.ui, f"GPO_num{row}_lineEdit", None):
                break

            parts = []
            if row - 1 < len(gpio_pairs):
                # 每一筆資料長得像 "12, PEE.03, 34, PEE.04"
                parts = [p.strip() for p in str(gpio_pairs[row - 1]).split(",")]

            _set_lineedit(f"GPO_num{row}_lineEdit", parts[0] if len(parts) > 0 else "")
            _set_lineedit(f"GPO_pin{row}_lineEdit", parts[1] if len(parts) > 1 else "")
            _set_lineedit(f"GPI_num{row}_lineEdit", parts[2] if len(parts) > 2 else "")
            _set_lineedit(f"GPI_pin{row}_lineEdit", parts[3] if len(parts) > 3 else "")

            row += 1

        # HDMI
        check_hdmi = getattr(self.ui, "checkBox_HDMI", None)
        combo_hdmi = getattr(self.ui, "hdmi_comboBox", None)
        if check_hdmi and combo_hdmi:
            if hdmi and int(hdmi.get("expect", 0)) > 0:
                check_hdmi.setChecked(True)
                combo_hdmi.setCurrentText(str(int(hdmi.get("expect", 0))))
            else:
                check_hdmi.setChecked(False)

        # VGA
        check_vga = getattr(self.ui, "checkBox_VGA", None)
        combo_vga = getattr(self.ui, "vga_comboBox", None)
        if check_vga and combo_vga:
            if vga and int(vga.get("expect", 0)) > 0:
                check_vga.setChecked(True)
                combo_vga.setCurrentText(str(int(vga.get("expect", 0))))
            else:
                check_vga.setChecked(False)
        
        # DP
        check_dp = getattr(self.ui, "checkBox_DP", None)
        combo_dp = getattr(self.ui, "dp_comboBox", None)
        if check_dp and combo_dp:
            if dp and int(dp.get("expect", 0)) > 0:
                check_dp.setChecked(True)
                combo_dp.setCurrentText(str(int(dp.get("expect", 0))))
            else:
                check_dp.setChecked(False)
        
        # LED
        check_led = getattr(self.ui, "checkBox_LED", None)
        combo_led = getattr(self.ui, "led_comboBox", None)
        if check_led and combo_led:
            if led and int(led.get("expect", 0)) > 0:
                check_led.setChecked(True)
                combo_led.setCurrentText(str(int(led.get("expect", 0))))
            else:
                check_led.setChecked(False)

        # POWER BUTTON
        check_POWER_BUTTON = getattr(self.ui, "checkBox_Power_Button", None)
        combo_POWER_BUTTON = getattr(self.ui, "power_button_comboBox", None)
        if check_POWER_BUTTON and combo_POWER_BUTTON:
            # power_btn = c.get("POWER BUTTON", {})
            if power_btn and int(power_btn.get("expect", 0)) > 0: # 有設定且大於0
                check_POWER_BUTTON.setChecked(True) # 勾選checkbox
                combo_POWER_BUTTON.setCurrentText(str(int(power_btn.get("expect", 0)))) # 設定combobox
            else:
                check_POWER_BUTTON.setChecked(False) # 不勾選checkbox

        # POWER CONNECTOR
        check_POWER_CONNECTOR = getattr(self.ui, "checkBox_PowerConnector", None)
        combo_POWER_CONNECTOR = getattr(self.ui, "power_connector_comboBox", None)
        if check_POWER_CONNECTOR and combo_POWER_CONNECTOR:
            # power_connector = c.get("POWER CONNECTOR", {})
            if power_connector and int(power_connector.get("expect", 0)) > 0:
                check_POWER_CONNECTOR.setChecked(True)
                combo_POWER_CONNECTOR.setCurrentText(str(int(power_connector.get("expect", 0))))
            else:
                check_POWER_CONNECTOR.setChecked(False)
        
        # POWER SW CONNECTOR
        check_POWER_SW_CONNECTOR = getattr(self.ui, "checkBox_PowerSWConnector", None)
        combo_POWER_SW_CONNECTOR = getattr(self.ui, "power_sw_connector_comboBox", None)
        if check_POWER_SW_CONNECTOR and combo_POWER_SW_CONNECTOR:
            # power_sw = c.get("POWER SW CONNECTOR", {})
            if power_sw and int(power_sw.get("expect", 0)) > 0:
                check_POWER_SW_CONNECTOR.setChecked(True)
                combo_POWER_SW_CONNECTOR.setCurrentText(str(int(power_sw.get("expect", 0))))
            else:
                check_POWER_SW_CONNECTOR.setChecked(False)

        # RESET BUTTON
        # if hasattr(self.ui, "checkBox_Reset_Button") and hasattr(self.ui, "reset_button_comboBox"):
        check_RESET_BUTTON = getattr(self.ui, "checkBox_Reset_Button", None)
        combo_RESET_BUTTON = getattr(self.ui, "reset_button_comboBox", None)
        if check_RESET_BUTTON and combo_RESET_BUTTON:
            # reset_btn = c.get("RESET BUTTON", {})
            if reset_btn and int(reset_btn.get("expect", 0)) > 0:
                check_RESET_BUTTON.setChecked(True)
                combo_RESET_BUTTON.setCurrentText(str(int(reset_btn.get("expect", 0))))
            else:
                check_RESET_BUTTON.setChecked(False)

        # RECOVERY BUTTON
        # if hasattr(self.ui, "checkBox_Recovery_Button") and hasattr(self.ui, "recovery_button_comboBox"):
            # recovery_btn = c.get("RECOVERY BUTTON", {})
        check_RECOVERY_BUTTON = getattr(self.ui, "checkBox_Recovery_Button", None)
        combo_RECOVERY_BUTTON = getattr(self.ui, "recovery_button_comboBox", None)
        if check_RECOVERY_BUTTON and combo_RECOVERY_BUTTON:
            if recovery_btn and int(recovery_btn.get("expect", 0)) > 0:
                check_RECOVERY_BUTTON.setChecked(True)
                combo_RECOVERY_BUTTON.setCurrentText(str(int(recovery_btn.get("expect", 0))))
            else:
                check_RECOVERY_BUTTON.setChecked(False)

        # SMA
        # if hasattr(self.ui, "checkBox_SMA") and hasattr(self.ui, "sma_comboBox"):
        check_SMA = getattr(self.ui, "checkBox_SMA", None)
        combo_SMA = getattr(self.ui, "sma_comboBox", None)
        if check_SMA and combo_SMA:
            # sma = c.get("SMA", {})
            if sma and int(sma.get("expect", 0)) > 0:
                check_SMA.setChecked(True)
                combo_SMA.setCurrentText(str(int(sma.get("expect", 0))))
            else:
                check_SMA.setChecked(False)

        # SW1
        # if hasattr(self.ui, "checkBox_SW1") and hasattr(self.ui, "sw1_comboBox"):
        check_SW1 = getattr(self.ui, "checkBox_SW1", None)
        combo_SW1 = getattr(self.ui, "sw1_comboBox", None)
        if check_SW1 and combo_SW1:
            # sw1 = c.get("SW1", {})
            if sw1 and int(sw1.get("expect", 0)) > 0:
                check_SW1.setChecked(True)
                combo_SW1.setCurrentText(str(int(sw1.get("expect", 0))))
            else:
                check_SW1.setChecked(False)

        # SW2
        # if hasattr(self.ui, "checkBox_SW2") and hasattr(self.ui, "sw2_comboBox"):
        check_SW2 = getattr(self.ui, "checkBox_SW2", None)
        combo_SW2 = getattr(self.ui, "sw2_comboBox", None)
        if check_SW2 and combo_SW2:
            # sw2 = c.get("SW2", {})
            if sw2 and int(sw2.get("expect", 0)) > 0:
                check_SW2.setChecked(True)
                combo_SW2.setCurrentText(str(int(sw2.get("expect", 0))))
            else:
                check_SW2.setChecked(False)

        # MCU CONNECTOR
        # if hasattr(self.ui, "checkBox_MCUConnector") and hasattr(self.ui, "mcu_connector_comboBox"):
        check_MCU_CONNECTOR = getattr(self.ui, "checkBox_MCUConnector", None)
        combo_MCU_CONNECTOR = getattr(self.ui, "mcu_connector_comboBox", None)
        if check_MCU_CONNECTOR and combo_MCU_CONNECTOR:
            # mcu_connector = c.get("MCU Connector", {})
            if mcu_connector and int(mcu_connector.get("expect", 0)) > 0:
                check_MCU_CONNECTOR.setChecked(True)
                combo_MCU_CONNECTOR.setCurrentText(str(int(mcu_connector.get("expect", 0))))
            else:
                check_MCU_CONNECTOR.setChecked(False)

        # RTC
        # if hasattr(self.ui, "checkBox_RTC") and hasattr(self.ui, "rtc_comboBox"):
        check_RTC = getattr(self.ui, "checkBox_RTC", None)
        combo_RTC = getattr(self.ui, "rtc_comboBox", None)
        if check_RTC and combo_RTC:
            # rtc = c.get("RTC", {})
            if rtc and int(rtc.get("expect", 0)) > 0:
                check_RTC.setChecked(True)
                combo_RTC.setCurrentText(str(int(rtc.get("expect", 0))))
            else:
                check_RTC.setChecked(False)

        # RTC OUT
        # if hasattr(self.ui, "checkBox_RTC_OUT") and hasattr(self.ui, "rtc_out_comboBox"):
        check_RTC_OUT = getattr(self.ui, "checkBox_RTC_OUT", None)
        combo_RTC_OUT = getattr(self.ui, "rtc_out_comboBox", None)
        if check_RTC_OUT and combo_RTC_OUT:
            # rtc_out = c.get("RTC OUT", {})
            if rtc_out and int(rtc_out.get("expect", 0)) > 0:
                check_RTC_OUT.setChecked(True)
                combo_RTC_OUT.setCurrentText(str(int(rtc_out.get("expect", 0))))
            else:
                check_RTC_OUT.setChecked(False)

        # DC INPUT
        # if hasattr(self.ui, "checkBox_DC_INPUT") and hasattr(self.ui, "dc_input_comboBox"):
        check_DC_INPUT = getattr(self.ui, "checkBox_DC_INPUT", None)
        combo_DC_INPUT = getattr(self.ui, "dc_input_comboBox", None)
        if check_DC_INPUT and combo_DC_INPUT:
            # dc_input = c.get("DC INPUT", {})
            if dc_input and int(dc_input.get("expect", 0)) > 0:
                check_DC_INPUT.setChecked(True)
                combo_DC_INPUT.setCurrentText(str(int(dc_input.get("expect", 0))))
            else:
                check_DC_INPUT.setChecked(False)

        # DC OUTPUT
        # if hasattr(self.ui, "checkBox_DC_OUTPUT") and hasattr(self.ui, "dc_output_comboBox"):
        check_DC_OUTPUT = getattr(self.ui, "checkBox_DC_OUTPUT", None)
        combo_DC_OUTPUT = getattr(self.ui, "dc_output_comboBox", None)
        if check_DC_OUTPUT and combo_DC_OUTPUT:
            # dc_output = c.get("DC OUTPUT", {})
            if dc_output and int(dc_output.get("expect", 0)) > 0:
                check_DC_OUTPUT.setChecked(True)
                combo_DC_OUTPUT.setCurrentText(str(int(dc_output.get("expect", 0))))
            else:
                check_DC_OUTPUT.setChecked(False)

        # FTP
        self.apply_ftp_target_to_ui(self.cfg.get("ftp_target", ""))

    def on_config_save(self):
        """按下『儲存設定』：收集 UI → 更新 cfg → 寫 TOML → 訊息回饋。"""
        data = self.save_toml_cfg()  # save_toml_cfg 內會同步 self.cfg，並回傳 data
        self.ui.Information_textEdit.append(f"[Config] 已儲存：{data}")
        QMessageBox.information(self, "Config設定", "Config設定已成功儲存, 請關閉程式並重新開啟, 以讀取Config")
        # 如需立刻套到畫面，可選擇：
        # self.apply_tomlcfg_to_ui(data)

    # def on_config_save(self):
    #     """按下『儲存設定』：讀分頁→更新 cfg→寫 INI/YAML/TOML→訊息區回饋。"""
    #     values = self.read_config_tab_values()
    #     self.cfg.update(values)
    #     # 寫入三種格式（你原本就有的）
    #     # self.save_cfg_to_ini()
    #     # self.save_yaml_cfg()
    #     self.save_toml_cfg()
    #     self.ui.Information_textEdit.append(f"[Config] 已更新：{values}")
    #     QMessageBox.information(self, "Config設定", "Config設定已成功儲存, 請關閉程式並重新開啟, 以讀取Config")

    def on_config_cancel(self):
        """按下『取消』：不做任何事就關閉對話框。"""
        QMessageBox.information(self, "Config設定", "已取消設定變更。")
        # 切換到第一個分頁（index=0）
        tab_widget = getattr(self.ui, "tabWidget", None)
        if tab_widget is not None:
            tab_widget.setCurrentIndex(0)
        # 不需要特別處理，對話框會自動關閉

    def set_ftp_target(self, target: str):
        self.cfg["ftp_target"] = (target or "").upper()

    def get_ftp_target_from_ui(self) -> str:
        if getattr(self.ui, "PD1_FTP_radioButton", None) and self.ui.PD1_FTP_radioButton.isChecked():
            return "PD1"
        if getattr(self.ui, "PD2_FTP_radioButton", None) and self.ui.PD2_FTP_radioButton.isChecked():
            return "PD2"
        if getattr(self.ui, "PD3_FTP_radioButton", None) and self.ui.PD3_FTP_radioButton.isChecked():
            return "PD3"
        return ""  # ← 沒選要回傳空字串
    
    def apply_ftp_target_to_ui(self, target: str):
        target = (target or "").upper()
        name = {
            "PD1": "PD1_FTP_radioButton",
            "PD2": "PD2_FTP_radioButton",
            "PD3": "PD3_FTP_radioButton",
        }.get(target)
        if not name:
            return
        rb = getattr(self.ui, name, None)
        if rb:
            rb.setChecked(True)
    
    def load_toml_cfg(self, path="./mb_test_config.toml"):
        if not os.path.exists(path):
            self.ui.Information_textEdit.append("未找到設定檔，使用預設值。")
            self.ui.config_read_TextLabel.setText("未找到設定檔，使用預設值。")
            self.ui.config_read_TextLabel.setStyleSheet("color: red;")
            return
        # if tomllib is None:
        #     self.ui.Information_textEdit.append("[警告] 目前 Python 沒有 tomllib（需要 3.11+），無法讀 TOML。")
        #     return
        # with open(path, "rb") as f:
        #     data = tomllib.load(f) or {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = toml.load(f) or {}

            # --- 標準化 E-Key 區段名稱 ---
            # # 目的：不管是 [EKEY]、[E-KEY]、[E-Key] 都統一成 "E-Key"
            # ekey_sec = None
            # for key in ("E-KEY", "EKEY", "EKey", "E-Key"):
            #     if key in data:
            #         ekey_sec = data.pop(key)
            #         break
            # if ekey_sec is not None:
            #     data["E-Key"] = ekey_sec

            self.cfg.update(data)
            self.ui.Information_textEdit.append(f"載入設定檔：{path}")
            self.ui.config_read_TextLabel.setText("已讀取 TOML 設定檔")
            self.ui.config_read_TextLabel.setStyleSheet("color: green;")
        except Exception as e:
            self.ui.Information_textEdit.append(f"[警告] 讀取設定檔失敗：{e}")
            QMessageBox.warning(self, "設定檔錯誤", f"讀取 TOML 設定檔失敗：{e}")
            return

        # 用分段表格 → 攤平成 self.cfg 你現有的鍵
        # （沒提供就用既有 self.cfg 的預設）
        # g  = data.get("GENERAL", {})
        fan = data.get("FAN", {})
        eeprom = data.get("EEPROM", {})

        self.cfg.update({
            # "log_dir":                g.get("log_dir",              self.cfg.get("log_dir", "")),
            # "sn":                     g.get("sn",                   self.cfg.get("sn", "")),

            "fan_enabled":            bool(fan.get("enabled",                self.cfg.get("fan_enabled", False))),
            "fan_seconds":            int(fan.get("fan_seconds",             self.cfg.get("fan_seconds", 10))),
            "fan_pwm":                int(fan.get("fan_pwm",                 self.cfg.get("fan_pwm", 50))),

            "eeprom_enabled":         bool(eeprom.get("enabled",                self.cfg.get("eeprom_enabled", False))),
            "eeprom_bus":             int(eeprom.get("eeprom_i2c_bus",          self.cfg.get("eeprom_bus", 7))),
            # addr 允許 0xXX 或十進位
            "eeprom_addr":            (int(eeprom.get("eeprom_i2c_addr"), 16) if isinstance(eeprom.get("eeprom_i2c_addr"), str) and str(eeprom.get("eeprom_i2c_addr")).lower().startswith("0x")
                                    else int(eeprom.get("eeprom_i2c_addr",      self.cfg.get("eeprom_addr", 0x55)))),
            "eeprom_gpio_num":        int(eeprom.get("eeprom_gpio_write_num",   self.cfg.get("eeprom_gpio_num", 345))),
            "eeprom_gpio_pin":        str(eeprom.get("eeprom_gpio_write_pin",   self.cfg.get("eeprom_gpio_pin", "PEE.06"))),
            "eeprom_pn":              str(eeprom.get("pn",                      self.cfg.get("eeprom_pn", ""))),
            "eeprom_board_name":      str(eeprom.get("board_name",              self.cfg.get("eeprom_board_name", ""))),
            "eeprom_board_revision":  str(eeprom.get("board_revision",          self.cfg.get("eeprom_board_revision", ""))),
        })

        ftp = data.get("FTP", {})
        if isinstance(ftp, dict):
            t = str(ftp.get("target", "")).upper()
            if t in ("PD1", "PD2", "PD3"):
                self.cfg["ftp_target"] = t

        # self.ui.Information_textEdit.append(f"載入設定檔：{path}")

    # ---- 讀檔小工具 ----
    def read_text(self, path, default="-"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                s = f.read().strip()
                return s if s else default
        except Exception:
            return default

    # ---- 取資料（功能一個函式）----
    def board_info(self):
        return {
            "vendor":       self.read_text("/sys/class/dmi/id/board_vendor"),
            "name":         self.read_text("/sys/class/dmi/id/board_name"),
            "serial":       self.read_text("/sys/class/dmi/id/board_serial"),
            "bios_version": self.read_text("/sys/class/dmi/id/bios_version"),
            "bios_vendor":  self.read_text("/sys/class/dmi/id/bios_vendor"),
        }

    def cpu_temp(self):
        for p in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
            v = self.read_text(p, "")
            if v.isdigit():
                iv = int(v)
                if iv > 0:
                    return f"{iv/1000:.1f}"
        return "-"

    def cpu_fan_rpms(self):
        try:
            out = subprocess.check_output(
                ["bash", "-lc", "sensors -A 2>/dev/null | grep -i 'fan'"],
                text=True, timeout=1.5
            )
            return [m.group(1) for m in re.finditer(r"(\d+)\s*RPM", out)]
        except Exception:
            return []

    def mem_slot_sizes_for_ui(self, max_slots=4):
        """
        回傳長度=max_slots 的清單，每格為 '16.0 GiB' 或 '---'
        1) 先讀 EDAC（/sys/devices/system/edac/mc/mc*/dimm*/size, MB）
        2) 再讀 dmidecode -t 17（強制 LANG=C）
        """
        # # --- 1) EDAC ---
        # paths = sorted(glob.glob("/sys/devices/system/edac/mc/mc*/dimm*/size"))
        # sizes = []
        # for p in paths:
        #     try:
        #         mb = int(open(p).read().strip())
        #     except Exception:
        #         mb = 0
        #     sizes.append(f"{mb/1024:.1f} GiB" if mb > 0 else "---")
        # if sizes:
        #     return (sizes + ["---"] * max_slots)[:max_slots]

        # --- 2) dmidecode ---
        exe = shutil.which("dmidecode")
        if not exe:
            self.ui.Information_textEdit.append("[MEM] 找不到 dmidecode：請先安裝（例如 sudo apt install dmidecode）")
            return ["---"] * max_slots

        env = os.environ.copy()
        env["LANG"] = "C"; env["LC_ALL"] = "C"

        try:
            out = subprocess.check_output(
                [exe, "-t", "17"],
                text=True, stderr=subprocess.STDOUT, env=env, timeout=6.0
            )
        except subprocess.CalledProcessError as e:
            msg = e.output.strip() if isinstance(e.output, str) else str(e)
            if "Permission denied" in msg or "permission" in msg.lower():
                self.ui.Information_textEdit.append(
                    "[MEM] dmidecode 權限不足：請執行\n"
                    "  sudo setcap cap_sys_rawio=ep $(which dmidecode)\n"
                    "或用 sudo 跑一次程式。"
                )
            else:
                self.ui.Information_textEdit.append(f"[MEM] dmidecode 失敗：{msg}")
            return ["---"] * max_slots
        except subprocess.TimeoutExpired:
            self.ui.Information_textEdit.append("[MEM] dmidecode 逾時（已超過 6 秒），請再試一次或用 sudo 執行。")
            return ["---"] * max_slots
        except Exception as e:
            self.ui.Information_textEdit.append(f"[MEM] 執行 dmidecode 失敗：{e}")
            return ["---"] * max_slots

        # 解析 Size
        sizes = []
        blocks = re.split(r"\n\s*Memory Device\s*\n", "\n"+out)
        for b in blocks[1:]:
            m = re.search(r"\n\s*Size:\s*(.+)", b)
            if not m:
                continue
            val = m.group(1).strip()
            if re.search(r"(?i)no module installed|not installed|unknown", val):
                sizes.append("---"); continue
            m2 = re.match(r"(?i)\s*(\d+(?:\.\d+)?)\s*(GB|MB)\s*$", val)
            if m2:
                num = float(m2.group(1)); unit = m2.group(2).upper()
                sizes.append(f"{(num if unit=='GB' else num/1024):.1f} GiB")
            else:
                sizes.append(val)

        if not sizes:
            self.ui.Information_textEdit.append("[MEM] dmidecode 正常執行，但沒有解析到任何 DIMM 容量。")
            return ["---"] * max_slots

        return (sizes + ["---"]*max_slots)[:max_slots]

    def mac_address(self):
        """回傳 [(iface, MAC), ...]，只收實體介面、排除 lo / 00:00:..."""
        macs = [] # (iface, MAC), 這是 list
        base = "/sys/class/net/" # Linux 專用, 基礎路徑, 這裡有各網卡的資料夾, 其他 OS 不適用
        try:
            for iface in sorted(os.listdir(base)): # 介面名稱排序
                if iface == "lo": # 排除 lo
                    continue # lo 介面不需要, 直接跳過
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
    
    def all_mac_addresses(self):
        """把找到的 MAC 依序填到 valMAC1..valMAC6，多餘的補 '-'"""
        macs_only = [mac for iface, mac in self.mac_address()] # 只取 MAC
        for i in range(6): # 填 6 個欄位
            label = getattr(self.ui, f"valMAC{i+1}", None) # valMAC1..valMAC6
            if label: # 找到這個屬性
                if i < len(macs_only): # 有對應的 MAC
                    label.setText(macs_only[i]) # 填 MAC
                else: # 沒有對應的 MAC
                    label.setText("-") # 補 '-'
    
    def validate_test_config(self) -> bool:
        """
        通用檢查：
        - 走遍 BTN_MAP 裡的自動測項
        - 若 checkbox 有勾，且找得到對應的 combobox
        就要求 combobox 的數量 > 0
        - 找不到 combobox 的項目視為「不需要數量」，直接略過
        """

        for display_name, cb in getattr(self, "BTN_MAP", {}).items(): # 走訪 BTN_MAP 所有測項
            if not cb:
                continue

            # 只檢查「有勾選」的項目
            if not cb.isChecked():
                continue

            obj_name = cb.objectName() or ""
            if not obj_name.startswith("checkBox_"):
                continue

            # 由 checkbox 名稱推 combobox 名稱
            base = obj_name[len("checkBox_"):]   # 例如 "USB2" / "MICROSD" / "MKEY" / "GPIO"

            candidate_names = [
                f"{base}_comboBox",          # USB2_comboBox / MKEY_comboBox / EKEY_comboBox ...
                f"{base.lower()}_comboBox",  # usb2_comboBox / microsd_comboBox / gpio_comboBox ...
                f"{base.capitalize()}_comboBox",  # MicroSD_comboBox 之類，保險用
            ]

            combo = None
            for name in candidate_names:
                w = getattr(self.ui, name, None)
                if w is not None:
                    combo = w
                    break

            # 沒有找到 combobox → 視為這個測項不需要「數量」，直接跳過
            if combo is None:
                continue

            # 讀 combobox 裡的數字
            text = (combo.currentText() or "").strip()
            try:
                exp = int(text)
            except Exception:
                exp = 0

            if exp <= 0:
                QMessageBox.warning(
                    self,
                    "設定錯誤",
                    f"{display_name} 有勾選但數量是 0，請先在 Config 設定 {display_name} 數量。",
                )
                combo.setFocus()
                return False

        return True

        # ---- 週期更新（直接改屬性）----
    def update_dynamic(self):
        temp = self.cpu_temp()
        self.ui.valCpuTemp.setText(f"{temp} °C" if temp != "-" else "-")

        rpms = self.cpu_fan_rpms()
        self.ui.valCpuFanRpm.setText(rpms[0] if rpms else "0")   # 或 f"{rpms[0]} RPM"

        # 顯示名稱 → UI 按鈕物件，用來改顏色與提示
        # 從 Test_item.TEST_ITEMS 自動產生，避免重複維護
        self.BTN_MAP = {
            ui_name: getattr(self.ui, checkbox_name, None) # 從 ui 取物件, 可能找不到就給 None, 不會報錯
            for ui_name, _method, checkbox_name in TEST_ITEMS # 來自 test_item.py, TEST_ITEMS, 第一欄是UI顯示名稱, 第三欄是 checkbox 物件名稱
        }

    def color_change(self, display_name: str, status: str, tip: str = ""):
        cb = self.BTN_MAP.get(display_name)
        if not cb:
            return

        cb.setAttribute(Qt.WA_StyledBackground, True)

        colors = {
            "RUN":   ("#0066B3", "white"),
            "PASS":  ("#16a34a", "white"),
            "FAIL":  ("#dc2626", "white"),
            "ERROR": ("#dc2626", "white"),
            "SKIP":  ("#6b7280", "white"),
            "IDLE":  (None, None),
        }
        bg, fg = colors.get(status, (None, None))

        if bg is None:
            cb.setStyleSheet("")  # 還原
        else:
            # 只改 QCheckBox 本體，不覆蓋 indicator；並留出左邊 28px 放小方框
            cb.setStyleSheet(
                f"""
                QCheckBox {{
                    background-color: {bg};
                    color: {fg};
                    padding: 2px 8px 2px 28px;   /* 左邊空出位置給 indicator */
                    border-radius: 6px;
                }}
                QCheckBox::indicator {{
                    margin-left: 8px;            /* 讓小方框不要貼太近 */
                }}
                """
            )

        cb.setToolTip(tip or "")
    
    def update_current_item(self, ui_name: str): # 更新目前測試項目顯示, 讓使用者知道現在正在測試什麼, 改變對應按鈕顏色
        """
        在測試過程中更新目前正在測的項目：
        - 右側 Information_textEdit 顯示『正在測試：XXX』
        - 對應的 Checkbox 變成藍色 (RUN 狀態)
        """
        # 1) 訊息視窗顯示目前項目
        te = getattr(self.ui, "Information_textEdit", None)
        if te:
            te.append(f"\n=== 正在測試：{ui_name} ===")
            te.ensureCursorVisible()

        # 2) 把對應的測項 checkbox 改成 RUN（藍色）
        try:
            self.color_change(ui_name, "RUN", f"正在測試：{ui_name}")
        except Exception:
            # 就算找不到 BTN_MAP 也不要讓整個測試中斷
            pass

        # 3) 讓畫面馬上重繪，不要等測試跑完才更新
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()


    def _set_all_in(self, container, checked: bool):
        """把某容器底下所有 QCheckBox 設為勾/不勾。"""
        for cb in container.findChildren(QCheckBox):
            cb.setChecked(checked)

    # def _all_manual_item_names(self):
    #     """取『人工判斷項目』清單（不開視窗：臨時建立對話框讀取文字）。"""
    #     dlg = ManualItemsDialog(self)
    #     return [cb.text() for cb in dlg.findChildren(QCheckBox)]

    # def _render_manual_text(self):
    #     """把 self.manual_selected 顯示到 Manual_textEdit。"""
    #     te = getattr(self.ui, "Manual_textEdit", None)
    #     if not te:
    #         return
    #     items = sorted(self.manual_selected)
    #     te.clear()
    #     if items:
    #         te.append("選擇了手動項目：")
    #         for name in items:
    #             te.append(f"✔ {name}")
    #     else:
    #         te.append("未選擇任何手動項目。")

    def select_all_items(self, include_manual: bool = False):
        # 自動測項：全勾
        self._set_all_in(self.ui.auto_test_GroupBox, True)
        self._set_all_in(self.ui.manual_test_GroupBox, True)

    def clean_all_items(self, include_manual: bool = False):
        # 自動測項：全取消
        self._set_all_in(self.ui.auto_test_GroupBox, False)
        self._set_all_in(self.ui.manual_test_GroupBox, False)

    def start_test_time(self): # 每秒更新時間 (計時器), 紀錄測試時間
        elapsed = self.start_time.secsTo(QTime.currentTime())
        time = QTime(0, 0).addSecs(elapsed) # 將經過的秒數轉成 QTime
        self.ui.timeEdit_Timer.setTime(time) # 更新顯示

    def close_test_time(self): # 停止計時器, 停止更新時間
        if hasattr(self, 'timer'):
            self.timer.stop()

    def start_test(self):
        # 初始化 timer（只初始化一次）
        if not hasattr(self, 'timer'):
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.start_test_time)
        if not self.validate_test_config():
            return  # 設定有問題，不要開跑
        
        self.start_time = QTime.currentTime()
        self.timer.start(1000)  # 每秒更新
        self.all_test_items() # 開始測試

    def log_upload(self):
        self.close_test_time()
        self.ui.timeEdit_Timer.setTime(QTime(0, 0))  # 重設時間顯示
        elapsed = self.start_time.secsTo(QTime.currentTime())
        print(f"測試結束，總共花了 {elapsed} 秒")
        self.upload_report() # 測試結束後上傳報告
        self.ui.Information_textEdit.append(f"測試結束，總共花了 {elapsed} 秒")
        QMessageBox.information(self, "測試結束", f"測試結束，總共花了 {elapsed} 秒")

    def update_current_test_items(self, name):
        """更新目前測試項目顯示欄位"""
        try:
            self.ui.Information_textEdit.append(f"目前測試項目：{name}")
            QtWidgets.QApplication.processEvents()  # 強制更新 UI
        except Exception as e:
            print(f"更新目前測試項目顯示欄位時發生錯誤: {e}")

    # 收集自動 + 手動 GroupBox 內的 CheckBox 測試項目
    def collect_checked_tests(self):
        names = []
        for box_name in ("auto_test_GroupBox", "manual_test_GroupBox"):
            gb = getattr(self.ui, box_name, None)
            if gb:
                for cb in gb.findChildren(QCheckBox):
                    if cb.isChecked():
                        names.append(cb.text().strip())

        # 去重保順序
        seen, ordered = set(), []
        for n in names:
            if n not in seen:
                seen.add(n)
                ordered.append(n)
        return ordered
    
    def all_test_items(self): # 全部測試項目
        # auto_selected = self.collect_auto_items()
        # item_name = auto_selected + list(self.manual_selected) # 合併自動和手動選的項目
        # selected_display_names = auto_selected + list(self.manual_selected)
        selected_display_names = self.collect_checked_tests() # 收集所有被選取的測試項目名稱（含自動和手動）
        self.ui.Information_textEdit.append(f"[DEBUG] 勾選：{selected_display_names}")

        if not selected_display_names:
            self.ui.Information_textEdit.append("未選擇任何測項。")
            return
        
        # 去重（保留第一次出現的順序）
        selected_display_names = list(dict.fromkeys(selected_display_names)) # 去重但保留順序

        # 依 TEST_ITEMS 的順序當作預設測試順序
        PREFERRED_ORDER = [ui_name for ui_name, _method, _cb in TEST_ITEMS] # 取出顯示名稱清單

        order_index = {n: i for i, n in enumerate(PREFERRED_ORDER)} # 建立名稱到索引的映射, 方便排序, 沒在列表中的項目會被放到最後
        selected_display_names.sort(key=lambda n: order_index.get(n, 10_000)) # 預設放最後面

        # MB_Test.py -> all_test_items()
        result, text, item_status = run_selected_tests(
            selected_display_names,
            log_dir=self.cfg.get("log_dir"),
            sn=self.cfg.get("sn"),
            meta=self.cfg.get("meta"),
            log_path=self.cfg.get("user_log_path"),  # 指向同一顆使用者 .log
            window = self,  # 傳入主視窗參考以更新目前測試項目顯示
        )
        try:
            self.ui.Information_textEdit.append(text)
        except Exception:
            print(text)

        # 變色
        for name, status in item_status.items():
            # 這裡先不放 tip；如果之後你回傳 item_message，就可以塞進來
            self.color_change(name, status) # 改顏色 name是顯示名稱, status是 'PASS'/'FAIL' 等等

        # 只依據本次有勾選的項目計算 Pass/Fail
        total_tests = result.testsRun
        total_failures = len(result.failures)
        total_errors = len(result.errors)
        total_passed = total_tests - total_failures - total_errors

        summary = (f"{total_passed}/{total_tests} passed，"
                   f"fail={total_failures}，err={total_errors}")
        self.ui.Information_textEdit.append(summary)

        passed = (total_failures == 0 and total_errors == 0)
        self.rename_log(passed)

        # 彈跳視窗：全部通過 → PASS；只要有 fail 或 error → FAIL
        if total_failures == 0 and total_errors == 0:
            QMessageBox.information(self, "測試結果", "所有測項均通過！", QMessageBox.Ok)
            self.ui.Information_textEdit.append("所有測項均通過！")
            # self.end_test() # 測試結束，停止計時器
        else:
            # QMessageBox.critical(self, "測試結果", "有測項未通過！", QMessageBox.Ok)
            # 把沒通過的測項名稱列出來
            def fail_item_name(testcase):
                # 例：<Test_item.AutoTests testMethod=USB> → USB
                return getattr(testcase, "_testMethodName", str(testcase))
            bad = [ fail_item_name(t) for t,_ in (result.failures + result.errors) ]
            QMessageBox.critical(
                self,
                "測試結果",
                "有測項未通過：\n" + "\n".join(bad)
            )
            self.ui.Information_textEdit.append("有測項未通過：\n" + "\n".join(bad))
            # self.end_test() # 測試結束，停止計時器

        # MES 出站

        mode = (self.cfg.get("meta", {}).get("mode") or "").strip()
        if mode in ("RD", "OFFLINE"):
            self.ui.Information_textEdit.append("【MES 出站略過】目前是 RD/OFFLINE 模式。")
            return

        # === MES 出站：用 TOML 的 expect 做 QTY，item_status 做 RESULT ===
        run_status = item_status                     # run_selected_tests 回傳的字典
        picked = selected_display_names[:]           # 本輪勾選的顯示名稱

        # 準備 TEST_LOG 其他欄位（BOARD/MODULE/...）
        mes_meta = {
            "BOARD":             self.cfg.get("BOARD",""),
            "MODULE":            self.cfg.get("MODULE",""),
            "BSP":               self.cfg.get("BSP",""),
            "DTS":               self.cfg.get("DTS",""),
            "WORK_ORDER":        self.cfg.get("meta",{}).get("workorder",""),
            "PART_NUMBER":       self.cfg.get("meta",{}).get("part_no",""),
            "CID":               self.cfg.get("meta",{}).get("cid",""),
            "CPU":               self.cfg.get("cpu_name",""),
            "MEMORY":            self.cfg.get("mem_info",""),
            "TEST_TOOL_VERSION": self.cfg.get("version",""),
            "TEST_TOOL_CONFIG":  self.cfg.get("config_name",""),
        }

        # 產生完整 TEST_LOG（內含 ITEM_LIST/ QTY/ RESULT）
        testlog   = build_mes_testlog(mes_meta, picked, run_status)
        item_list = testlog["ITEM_LIST"]
        extra_log = {k: v for k, v in testlog.items() if k != "ITEM_LIST"}

        # 參數
        runcard      = (self.cfg.get("meta",{}).get("runcard","") or "").strip()
        system_sn    = (self.cfg.get("sn","") or "").strip()
        employee_no  = (self.cfg.get("meta",{}).get("operator","") or "").strip()
        process_name = (self.cfg.get("meta",{}).get("process_name","") or "").strip()
        workorder    = (self.cfg.get("meta",{}).get("workorder","") or "").strip()

        if not process_name:
            self.ui.Information_textEdit.append("【MES 出站略過】缺少站別 process_name（請在登入時把 process_name 帶進 cfg.meta）")
        else:
            lev = self.mes.leave_api(
                runcard=runcard,
                sn=system_sn,
                operator=employee_no,
                wo=workorder,
                process_name=process_name,
                item_list=item_list,     # ★ 每個項目的 ITEM/QTY/RESULT
                extra_log=extra_log,     # ★ 其他 TEST_LOG 欄位
            )
            if lev.get("ok"):
                self.ui.Information_textEdit.append("[MES][出站] 成功")
                QMessageBox.information(self, "[MES][出站]", "MES 出站成功！", QMessageBox.Ok)
            else:
                self.ui.Information_textEdit.append(f"[MES][出站] 失敗：{lev.get('error') or lev.get('msg')}")
                QMessageBox.critical(self, "[MES][出站]", f"MES 出站失敗：{lev.get('error') or lev.get('msg')}", QMessageBox.Ok)


    def rename_log(self, passed: bool):
        """把 user_log_path 指向的檔案改名，結尾加 _PASS 或 _FAIL"""
        log_path = self.cfg.get("user_log_path")
        if not log_path:
            return
        
        p = pathlib.Path(log_path)
        if not p.exists():
            return

        # 先關掉 logger 的檔案 handler（避免檔案被占用）
        lg = logging.getLogger("useing")
        for h in lg.handlers[:]:
            lg.removeHandler(h)
            try:
                h.close()
            except:
                pass

        # tag = "_PASS" if passed else "_FAIL"
        # new_log = p.with_name(f"{p.stem}{tag}{p.suffix}")   # 直接改名，不做唯一性處理
        # os.replace(p, new_log)

        tag_tail_re = re.compile(r"_(PASS|FAIL)$", re.IGNORECASE)
        base_stem = tag_tail_re.sub("", p.stem) # 去掉舊的 _PASS/_FAIL
        suffix = p.suffix or ".log"
        tag = "PASS" if passed else "FAIL"

        # for old in p.parent.glob(f"{base_stem}_*{suffix}"):
        #     try:
        #         old.unlink() # 刪掉舊的
        #     except:
        #         pass

        # new_log = p.with_name(f"{base_stem}{tag}{suffix}")
        # try:
        #     os.replace(p, new_log)
        # except FileExistsError:
        #     pass # 萬一同名檔案已存在就不改名了

        # 先決定新檔名

        new_log = p.with_name(f"{base_stem}_{tag}{suffix}")

        # 若目前檔名跟新檔名不同，先把新檔（若已存在）移除，再把舊檔改名過去
        if p != new_log:
            try:
                if new_log.exists():
                    new_log.unlink()
            except Exception:
                pass
            os.replace(p, new_log)   # 這時候來源檔還在，rename 一定成功
            p = new_log              # 後續清理時把它視為「現役檔」

        # 再清掉同 base 的其他 TAG 版本，但跳過「現役檔」
        for old in p.parent.glob(f"{base_stem}_*{suffix}"):
            if old != p:
                try:
                    old.unlink()
                except Exception:
                    pass

        # 同名 JSON 一起改名（有就改、沒有就略過）
        j_old = p.with_suffix(".json")
        if j_old.exists():
            j_new = new_log.with_suffix(".json")
            os.replace(j_old, j_new)

        # 更新 cfg（若之後還要繼續寫入同一顆）
        self.cfg["user_log_path"] = str(new_log)

    def upload_report(self):
        # 1) 取得 WO 與本機要上傳的資料夾
        wo = (getattr(self, "wo", "") or # 優先用 self.wo
            self.cfg.get("meta", {}).get("workorder") or "").strip() # 再用 cfg
        if not wo and hasattr(self.ui, "WO_lineEdit"): # 再用 UI
            wo = (self.ui.WO_lineEdit.text() or "").strip() # 這裡不更新 self.wo

        base_dir = (self.cfg.get("log_dir") or "").strip() # 這是 log_dir
        candidate = base_dir if (base_dir and os.path.isdir(base_dir)) else wo # 以工單為主

        local_log_folder = candidate # 本機要上傳的資料夾
        upload_log_name = os.path.join(base_dir or ".", f"upload_log_{wo or 'NO_WO'}.log") # 上傳紀錄檔

        if not local_log_folder or not os.path.isdir(local_log_folder): # 目標資料夾不存在
            QMessageBox.warning(self, "警告", "找不到log資料夾，無法上傳測試報告")
            return

        # 2) 依勾選決定目標（此帳號登入即在正確目錄，不使用 base）
        targets = []
        if getattr(self.ui, "PD1_FTP_radioButton", None) and self.ui.PD1_FTP_radioButton.isChecked():
            targets.append({
                "name": "PD1",
                "host": "172.23.168.107",
                "user": "Aetina_PD1_Testlog",
                "pwd":  "TB*hb%nV_6vx%yYH",
            })
        if getattr(self.ui, "PD2_FTP_radioButton", None) and self.ui.PD2_FTP_radioButton.isChecked():
            targets.append({
                "name": "PD2",
                "host": "172.23.168.107",
                "user": "Aetina_testlog",
                "pwd":  "Nvidia0201",
            })
        if getattr(self.ui, "PD3_FTP_radioButton", None) and self.ui.PD3_FTP_radioButton.isChecked():
            targets.append({
                "name": "PD3",
                "host": "172.23.168.107",
                "user": "Aetina_testlog",
                "pwd":  "Nvidia0201",
            })

        if not targets:
            QMessageBox.information(self, "提示", "請至少勾選一個 FTP 目的地")
            return

        self.ui.Information_textEdit.append(f"開始上傳工單 {local_log_folder} 的測試報告...")

        # 3) 遞迴上傳（保留你的原本邏輯）
        def upload_folder(ftp, local_path, remote_path):
            try:
                ftp.mkd(remote_path)
            except Exception:
                pass  # 已存在忽略
            ftp.cwd(remote_path)

            for item in os.listdir(local_path):
                full_local_path = os.path.join(local_path, item)
                try:
                    ftp_files = [os.path.basename(f).lower() for f in ftp.nlst()]
                except Exception as e:
                    ftp_files = []
                    self.ui.Information_textEdit.append(f"[警告] 無法取得 FTP 檔案清單：{e}")

                if os.path.isfile(full_local_path):
                    if item.lower() in ftp_files:
                        msg = f"[略過] FTP 已存在檔案: {item}"
                        self.ui.Information_textEdit.append(msg)
                        with open(upload_log_name, "a", encoding="utf-8") as log:
                            log.write(f"[{current_target_name}] {msg}\n")
                        continue

                    with open(full_local_path, 'rb') as f:
                        ftp.storbinary(f'STOR {item}', f)
                        self.ui.Information_textEdit.append(f"上傳檔案: {item} 成功")

                elif os.path.isdir(full_local_path):
                    self.ui.Information_textEdit.append(f"上傳資料夾: {item} 開始")
                    upload_folder(ftp, full_local_path, item)

            ftp.cwd("..")  # 回上一層

        any_success = False
        folder_name = os.path.basename(os.path.normpath(local_log_folder))

        # 4) 對每個勾選目標依序上傳（不切 base，直接在登入目錄建 <WO>）
        for cfg in targets:
            current_target_name = cfg["name"]
            try:
                # 連線
                try:
                    ftp = FTP(cfg["host"])
                    ftp.login(user=cfg["user"], passwd=cfg["pwd"])
                except Exception as e:
                    err = f"[{current_target_name}] 連接 FTP 失敗: {e}"
                    QMessageBox.critical(self, "錯誤", err)
                    self.ui.Information_textEdit.append(err)
                    with open(upload_log_name, "a", encoding="utf-8") as log:
                        log.write(err + "\n")
                    continue

                # 直接在登入後目錄建立工單資料夾並上傳
                upload_folder(ftp, local_log_folder, folder_name)
                ftp.quit()

                ok_msg = f"[{current_target_name}] 上傳成功: {cfg['host']}/{folder_name}"
                QMessageBox.information(self, "上傳成功", ok_msg)
                self.ui.Information_textEdit.append(ok_msg)
                with open(upload_log_name, "a", encoding="utf-8") as log:
                    log.write(ok_msg + "\n")

                any_success = True

            except Exception as e:
                err = f"[{current_target_name}] 上傳測試報告時發生錯誤: {e}"
                QMessageBox.critical(self, "錯誤", err)
                self.ui.Information_textEdit.append(err)
                with open(upload_log_name, "a", encoding="utf-8") as log:
                    log.write(err + "\n")

        # 5) 任一成功就亮綠，否則亮紅
        if any_success:
            self.ui.Button_Upload.setStyleSheet("background-color: green; color: white;")
        else:
            self.ui.Button_Upload.setStyleSheet("background-color: red; color: white;")

        # 立刻去 FTP 重算 PASS/FAIL，並把結果顯示到右下角 LCD
        self.refresh_ftp_counts(only_ext=".log") # 只數 .log


    # ---- FTP 統計 _PASS/_FAIL 檔案數 ----

    def _set_pass_fail_counts(self, pass_cnt: int, fail_cnt: int):
        """把數字顯示到右下角兩個 QLCDNumber。"""
        try:
            if hasattr(self.ui, "pass_lcdNumber") and isinstance(self.ui.pass_lcdNumber, QLCDNumber):
                self.ui.pass_lcdNumber.display(int(pass_cnt))
            if hasattr(self.ui, "fail_lcdNumber") and isinstance(self.ui.fail_lcdNumber, QLCDNumber):
                self.ui.fail_lcdNumber.display(int(fail_cnt))
        except Exception:
            pass

    def pass_fail_count(self):
        """回傳 (pass_count, fail_count) – 從 LCD 讀目前顯示值"""
        p = f = 0 # 預設 0
        try:
            if hasattr(self.ui, "pass_lcdNumber") and isinstance(self.ui.pass_lcdNumber, QLCDNumber): # 檢查屬性存在且型態正確
                p = int(self.ui.pass_lcdNumber.value()) # 讀值
        except Exception:
            pass
        try:
            if hasattr(self.ui, "fail_lcdNumber") and isinstance(self.ui.fail_lcdNumber, QLCDNumber): # 檢查屬性存在且型態正確
                f = int(self.ui.fail_lcdNumber.value()) # 讀值
        except Exception:
            pass
        return p, f

    def _ftp_is_dir(self, ftp, name):
        """判斷目前目錄下的 name 是否為資料夾（不改變所在目錄）"""
        cur = ftp.pwd()
        try:
            ftp.cwd(name)
            ftp.cwd(cur)
            return True
        except Exception:
            try:
                ftp.cwd(cur)
            except Exception:
                pass
            return False

    def _ftp_count_pass_fail_in_dir(self, ftp, remote_dir, only_ext=".log"):
        """
        遞迴統計 remote_dir 底下檔名含 _PASS/_FAIL 的檔數（預設只數 .log）。
        回傳 dict: {"pass": x, "fail": y, "total": x+y}
        """
        counts = {"pass": 0, "fail": 0}

        def walk():
            try:
                names = ftp.nlst()
            except Exception as e:
                self.ui.Information_textEdit.append(f"[警告] 無法列出 FTP 目錄：{e}")
                names = []

            for name in names:
                if name in (".", ".."):
                    continue

                if self._ftp_is_dir(ftp, name):
                    try:
                        ftp.cwd(name)
                        walk()
                        ftp.cwd("..")
                    except Exception as e:
                        self.ui.Information_textEdit.append(f"[警告] 進入子目錄失敗：{name}，{e}")
                    continue

                low = name.lower()
                if only_ext and not low.endswith(only_ext):
                    continue
                if "_pass" in low:
                    counts["pass"] += 1
                elif "_fail" in low:
                    counts["fail"] += 1

        cur = ftp.pwd()
        try:
            ftp.cwd(remote_dir)
            walk()
        finally:
            try:
                ftp.cwd(cur)
            except Exception:
                pass

        counts["total"] = counts["pass"] + counts["fail"]
        return counts

    def ftp_select(self):
        # 先看 UI
        t = self.get_ftp_target_from_ui()
        # UI 沒選 → 用 cfg 後援
        if not t:
            t = (self.cfg.get("ftp_target") or "").upper()
            if t:
                self.apply_ftp_target_to_ui(t)  # 回填到 UI（可選）

        address = {
            "PD1": {"name":"PD1", "host":"172.23.168.107", "user":"Aetina_PD1_Testlog", "pwd":"TB*hb%nV_6vx%yYH"},
            "PD2": {"name":"PD2", "host":"172.23.168.107", "user":"Aetina_testlog",     "pwd":"Nvidia0201"},
            "PD3": {"name":"PD3", "host":"172.23.168.107", "user":"Aetina_testlog",     "pwd":"Nvidia0201"},
        }
        return address.get(t, None)
    
        # """
        # 依目前勾選的 PD1/PD2/PD3 *radioButton* 回傳 FTP 連線設定 dict，
        # 沒有選就回傳 None。
        # """
        # if getattr(self.ui, "PD1_FTP_radioButton", None) and self.ui.PD1_FTP_radioButton.isChecked():
        #     return {"name":"PD1", "host":"172.23.168.107", "user":"Aetina_PD1_Testlog", "pwd":"TB*hb%nV_6vx%yYH"}
        # if getattr(self.ui, "PD2_FTP_radioButton", None) and self.ui.PD2_FTP_radioButton.isChecked():
        #     return {"name":"PD2", "host":"172.23.168.107", "user":"Aetina_testlog", "pwd":"Nvidia0201"}
        # if getattr(self.ui, "PD3_FTP_radioButton", None) and self.ui.PD3_FTP_radioButton.isChecked():
        #     return {"name":"PD3", "host":"172.23.168.107", "user":"Aetina_testlog", "pwd":"Nvidia0201"}
        # return None

    def refresh_ftp_counts(self, only_ext=".log"):
        """
        依『WO 資料夾名』＋『radio 選擇的 FTP』遞迴統計 _PASS/_FAIL 檔數，
        並更新右下角 LCD。
        """
        # 取得工單資料夾名稱
        wo = (self.cfg.get("meta", {}).get("workorder") or "").strip()
        if not wo and hasattr(self.ui, "WO_lineEdit"):
            wo = (self.ui.WO_lineEdit.text() or "").strip()
        if not wo:
            self.ui.Information_textEdit.append("【FTP 統計略過】沒有工單資料夾名稱（WO）")
            return

        # 取得目標 FTP
        tgt = self.ftp_select()
        if not tgt:
            self.ui.Information_textEdit.append("【FTP 統計略過】請先選擇 PD1/PD2/PD3")
            return

        # 連線
        try:
            ftp = FTP(tgt["host"])
            ftp.login(user=tgt["user"], passwd=tgt["pwd"])
        except Exception as e:
            self.ui.Information_textEdit.append(f"[{tgt['name']}] 連線 FTP 失敗：{e}")
            return

        # 統計
        try:
            counts = self._ftp_count_pass_fail_in_dir(ftp, wo, only_ext=only_ext)
        except Exception as e:
            counts = {"pass": 0, "fail": 0, "total": 0}
            self.ui.Information_textEdit.append(f"[{tgt['name']}] 統計時發生錯誤：{e}")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        # 顯示到 UI
        self._set_pass_fail_counts(counts["pass"], counts["fail"])
        self.ui.Information_textEdit.append(
            f"[{tgt['name']}] FTP 統計（{wo}）：PASS={counts['pass']}，FAIL={counts['fail']}，TOTAL={counts['total']}"
        )
    # ====== /PASS/FAIL 顯示與 FTP 統計 ======



def mbtest_run(cfg=None):
    win = MBTestWindow(cfg)
    win.show()          # 一定要 show
    return win          # 一定要回傳，避免被回收
        
