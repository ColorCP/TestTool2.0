from PyQt5 import QtWidgets, uic
from ui_mbtest import Ui_MBWindow
# from ui_Manual_test import Ui_Manual_Test_iTem_Dialog
# from ui_other_setting import Ui_Other_Setting_Dialog
from PyQt5.QtCore import QTimer, QTime
import json, subprocess, re, os, glob, pathlib, time, configparser
from PyQt5.QtWidgets import QMessageBox, QDialog, QCheckBox, QLCDNumber, QComboBox
from Test_item import run_selected_tests, build_mes_testlog, mes_post, set_current_window, set_current_toml_path, TEST_ITEMS, PERSISTED_STATUS
# from pathlib import Path
import logging
import resources_rc # 這行是為了讓 Qt 資源檔生效，檔案在 resources_rc.py 中
from PyQt5.QtGui import QPixmap, QIntValidator, QRegExpValidator
from PyQt5.QtCore import Qt, QRegExp
from datetime import datetime, date
from ftplib import FTP, error_perm
from mes_api import MESClient
import shutil
import yaml
import toml

# 取得程式根目錄（MB_Test.py 所在目錄）
PROGRAM_ROOT = os.path.dirname(os.path.abspath(__file__))

class MBTestWindow(QtWidgets.QMainWindow):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        # uic.loadUi("ui_mbtest.ui", self)   # ← 用檔名載入
        self.ui = Ui_MBWindow()  # ← 用類別載入
        self.ui.setupUi(self)    # ← 一定要呼叫 setupUi()
        # print([(w.objectName(), w.text()) for w in self.findChildren(QCheckBox)]) # 印出所有 checkbox 的名稱和文字 debug use
        # self.setupUi(self)

        # =========================================================
        # 暫時不使用的功能, 先不顯示在ui，先隱藏起來，避免使用者誤操作
        # 目前先隱藏 case open 相關的元件，之後有需要再顯示出來
        self.ui.checkBox_CASEOPEN.setVisible(False)
        self.ui.caseopen_comboBox.setVisible(False)
        self.ui.label_138.setVisible(False) #這是case open comboBox前的label
        # =========================================================

        # =========================================================
        # 測試項目 checkbox → Config 頁面的 comboBox 映射表
        # 之後所有邏輯都只靠這張表，不再用字串推導
        # =========================================================
        self.checkbox_to_combo = { # 測項 checkbox → Config 頁面的 comboBox 映射表
            # ---- 自動測項 ----
            self.ui.checkBox_USB2:              self.ui.usb2_comboBox,
            self.ui.checkBox_USB3:              self.ui.usb3_comboBox,
            self.ui.checkBox_MKEY:              self.ui.mkey_comboBox,
            self.ui.checkBox_EKEY:              self.ui.ekey_comboBox,
            self.ui.checkBox_BKEY:              self.ui.bkey_comboBox,
            self.ui.checkBox_NETWORK:           self.ui.network_comboBox,
            self.ui.checkBox_FIBER:             self.ui.fiber_comboBox,
            self.ui.checkBox_CANBUS:            self.ui.canbus_comboBox,
            self.ui.checkBox_MICROSD:           self.ui.microsd_comboBox,
            self.ui.checkBox_RS232:             self.ui.rs232_comboBox,
            self.ui.checkBox_RS422:             self.ui.rs422_comboBox,
            self.ui.checkBox_RS485:             self.ui.rs485_comboBox,
            self.ui.checkBox_UART:              self.ui.uart_comboBox,
            self.ui.checkBox_GPIO:              self.ui.gpio_comboBox,
            self.ui.checkBox_CAMERA:            self.ui.camera_comboBox,
            self.ui.checkBox_FAN:               self.ui.fan_comboBox,
            self.ui.checkBox_I2C:               self.ui.i2c_comboBox,
            self.ui.checkBox_SPI:               self.ui.spi_comboBox,
            self.ui.checkBox_EEPROM:            self.ui.eeprom_comboBox,
            self.ui.checkBox_EEPROMRD:          self.ui.eepromrdrd_comboBox,
            self.ui.checkBox_CPU:               self.ui.cpu_comboBox,
            self.ui.checkBox_MEM:               self.ui.memory_comboBox,
            self.ui.checkBox_BIOSVER:           self.ui.biosver_comboBox,
            self.ui.checkBox_HWPRODUCTNAME:     self.ui.hwproductname_comboBox,

            # ---- 人工測項 ----
            self.ui.checkBox_MIC:               self.ui.mic_comboBox,
            self.ui.checkBox_LINEIN:            self.ui.linein_comboBox,
            self.ui.checkBox_SPEAKER:           self.ui.speaker_comboBox,
            self.ui.checkBox_HDMI:              self.ui.hdmi_comboBox,
            self.ui.checkBox_VGA:               self.ui.vga_comboBox,
            self.ui.checkBox_DP:                self.ui.dp_comboBox,
            self.ui.checkBox_LED:               self.ui.led_comboBox,
            self.ui.checkBox_POWERBUTTON:       self.ui.powerbutton_comboBox,
            self.ui.checkBox_POWERCONNECTOR:   self.ui.powerconnector_comboBox,
            self.ui.checkBox_POWERSWCONNECTOR:  self.ui.powerswconnector_comboBox,
            self.ui.checkBox_RESETBUTTON:       self.ui.resetbutton_comboBox,
            self.ui.checkBox_RECOVERYBUTTON:    self.ui.recoverybutton_comboBox,
            self.ui.checkBox_SMA:               self.ui.sma_comboBox,
            self.ui.checkBox_SW1:               self.ui.sw1_comboBox,
            self.ui.checkBox_SW2:               self.ui.sw2_comboBox,
            self.ui.checkBox_MCUCONNECTOR:      self.ui.mcuconnector_comboBox,
            self.ui.checkBox_RTC:               self.ui.rtc_comboBox,
            self.ui.checkBox_RTCOUT:            self.ui.rtcout_comboBox,
            self.ui.checkBox_DCINPUT:           self.ui.dcinput_comboBox,
            self.ui.checkBox_DCOUTPUT:          self.ui.dcoutput_comboBox,
            self.ui.checkBox_CASEOPEN:          self.ui.caseopen_comboBox,
            self.ui.checkBox_PDPOWERINPUT:      self.ui.pdpowerinput_comboBox,
            self.ui.checkBox_PSEPOWEROUTPUT:    self.ui.psepoweroutput_comboBox,
            self.ui.checkBox_INNOAGENT:         self.ui.innoagent_comboBox,
            self.ui.checkBox_GPS:               self.ui.gps_comboBox,
        }
        # checkbox 打勾時，顯示的toolButton
        self.checkbox_to_toolbutton = {
            self.ui.checkBox_NETWORK:           self.ui.network_toolButton,
            self.ui.checkBox_RS232:             self.ui.rs232_toolButton,
            self.ui.checkBox_RS422:             self.ui.rs422_toolButton,
            self.ui.checkBox_RS485:             self.ui.rs485_toolButton,
            self.ui.checkBox_GPIO:              self.ui.gpio_toolButton,
            self.ui.checkBox_SPI:               self.ui.spi_toolButton,
            self.ui.checkBox_EKEY:              self.ui.ekey_toolButton,
            self.ui.checkBox_BKEY:              self.ui.bkey_toolButton,
            self.ui.checkBox_FAN:               self.ui.fan_toolButton,
            self.ui.checkBox_EEPROM:            self.ui.eeprom_toolButton,
            self.ui.checkBox_EEPROMRD:          self.ui.eepromrd_toolButton,
            self.ui.checkBox_UART:              self.ui.uart_toolButton,
            self.ui.checkBox_I2C:               self.ui.i2c_toolButton,
            self.ui.checkBox_CANBUS:            self.ui.canbus_toolButton,
            self.ui.checkBox_CPU:               self.ui.cpu_toolButton,
            self.ui.checkBox_MEM:               self.ui.mem_toolButton,
            self.ui.checkBox_BIOSVER:           self.ui.biosver_toolButton,
            self.ui.checkBox_HWPRODUCTNAME:     self.ui.hwproductname_toolButton,
        }
        # checkbox 打勾時，顯示測試項目預覽的設定 groupBox
        self.checkbox_to_preview = {
            self.ui.checkBox_RS232:             self.ui.RS232_setting_groupBox,
            self.ui.checkBox_RS422:             self.ui.RS422_setting_groupBox,
            self.ui.checkBox_RS485:             self.ui.RS485_setting_groupBox,
            self.ui.checkBox_GPIO:              self.ui.GPIO_setting_groupBox,
            self.ui.checkBox_SPI:               self.ui.SPI_setting_groupBox,
            self.ui.checkBox_EKEY:              self.ui.EKEY_setting_groupBox,
            self.ui.checkBox_BKEY:              self.ui.BKEY_setting_groupBox,
            self.ui.checkBox_I2C:               self.ui.I2C_setting_groupBox,
            self.ui.checkBox_UART:              self.ui.UART_setting_groupBox,
            self.ui.checkBox_CANBUS:            self.ui.CANBUS_setting_groupBox,
            self.ui.checkBox_CPU:               self.ui.CPU_setting_groupBox,
            self.ui.checkBox_MEM:               self.ui.MEMORY_setting_groupBox,
            self.ui.checkBox_BIOSVER:           self.ui.BIOSVER_setting_groupBox,
            self.ui.checkBox_HWPRODUCTNAME:     self.ui.HWPRODUCTNAME_setting_groupBox,
            self.ui.checkBox_FAN:               self.ui.FAN_setting_groupBox,
            self.ui.checkBox_EEPROM:            self.ui.EEPROM_setting_groupBox,
            self.ui.checkBox_EEPROMRD:          self.ui.EEPROM_setting_groupBox,
            self.ui.checkBox_EKEY:              self.ui.EKEY_setting_groupBox,
            self.ui.checkBox_BKEY:              self.ui.BKEY_setting_groupBox,
            self.ui.checkBox_NETWORK:           self.ui.IP_setting_groupBox,
        }


        self.cfg = cfg or {} # 設定檔
        
        # 標記這次有沒有成功讀到 TOML 設定
        self.toml_loaded = False

        # mes.log 放在程式根目錄，不會被上傳
        mes_log_path = os.path.join(PROGRAM_ROOT, "mes.log")
        # 從 mes_info_meta 讀取 mode（進站時設定的）
        mes_info_init = self.cfg.get("mes_info_meta", {}) or {}
        mode = mes_info_init.get("mode", "RD")
        self.mes = MESClient(mode=mode, mes_log_path=mes_log_path)
        
        # 將 MODE 設定到環境變數，讓 Test_item.py 中的函式也能讀取到
        if mode:
            os.environ["MODE"] = mode

        # 把自己丟給 Test_item
        set_current_window(self)

        self.wo = (mes_info_init.get("workorder") or self.cfg.get("wo") or "").strip()
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

        # 初始化計時器顯示格式（24 小時制，顯示 00:00:00）
        if hasattr(self.ui, "timeEdit_Timer"):
            self.ui.timeEdit_Timer.setDisplayFormat("HH:mm:ss")
            self.ui.timeEdit_Timer.setTime(QTime(0, 0, 0))

        # Button connections
        self.ui.Button_Start_Test.clicked.connect(self.start_test)
        self.ui.Button_Upload.clicked.connect(self.log_upload)
        # self.ui.Button_Manual_Test.clicked.connect(self.manual_test)

        # 只全選/全清『自動測項』
        self.ui.Button_iTem_Select.clicked.connect(lambda: self.select_all_items(False))
        self.ui.Button_iTem_Clean.clicked.connect(lambda: self.clean_all_items(False))

        # Unlock all items
        self.ui.Button_iTem_Unlock.clicked.connect(self.unlock_all_items_from_toml)

        # 在這裡綁定 ToolButton 點擊事件, 按下combobox 旁的按鈕會彈出對話框
        self.ui.gpio_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.GPIO_setting_groupBox, "GPIO 設定")
        )
        self.ui.eeprom_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.EEPROM_setting_groupBox, "EEPROM 設定")
        )
        self.ui.eepromrd_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.EEPROM_setting_groupBox, "EEPROM RD 設定")
        )
        self.ui.fan_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.FAN_setting_groupBox, "FAN 設定")
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
            lambda: self.popout_group_as_dialog(self.ui.EKEY_setting_groupBox, "E-Key 設定")
        )
        self.ui.bkey_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.BKEY_setting_groupBox, "B-Key 設定")
        )
        self.ui.i2c_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.I2C_setting_groupBox, "I2C 設定")
        )
        self.ui.uart_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.UART_setting_groupBox, "UART 設定")
        )
        self.ui.spi_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.SPI_setting_groupBox, "SPI 設定")
        )
        self.ui.canbus_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.CANBUS_setting_groupBox, "CAN BUS 設定")
        )
        self.ui.cpu_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.CPU_setting_groupBox, "CPU 設定")
        )
        self.ui.mem_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.MEMORY_setting_groupBox, "MEM 設定")
        )
        self.ui.biosver_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.BIOSVER_setting_groupBox, "BIOS VERSION 設定")
        )
        self.ui.hwproductname_toolButton.clicked.connect(
            lambda: self.popout_group_as_dialog(self.ui.HWPRODUCTNAME_setting_groupBox, "HW PRODUCT NAME 設定")
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
        
        self.all_mem_slots()   # 填 valMEM1..valMEMN
        self.all_mac_addresses()  # 填 valMAC1..valMACN

        # 取得系統資訊並存到 cfg（BSP、DTS、BOARD、MODULE、CID、CPU、MEMORY）
        sys_info = self.get_dts_and_x86_name()
        bsp = sys_info.get("bsp", "")
        dts = sys_info.get("dts", "")
        board = sys_info.get("board", "")
        
        # 如果沒有從 BSP 解析出 BOARD，嘗試從 BSP 名稱解析
        if not board and bsp:
            board = self.get_board_from_bsp(bsp)
        
        # 如果還是沒有 BOARD，使用 board_info 的 name
        if not board:
            board = info.get("name", "")
        
        module = self.get_module(board)
        cid = self.get_cid()
        cpu_name = self.get_cpu_name()
        mem_info = self.get_memory_info()
        
        # 存到 self.cfg（如果 cfg 中沒有這些值才填入）
        if "BSP" not in self.cfg or not self.cfg.get("BSP"):
            self.cfg["BSP"] = bsp
        if "DTS" not in self.cfg or not self.cfg.get("DTS"):
            self.cfg["DTS"] = dts
        if "BOARD" not in self.cfg or not self.cfg.get("BOARD"):
            self.cfg["BOARD"] = board
        if "MODULE" not in self.cfg or not self.cfg.get("MODULE"):
            self.cfg["MODULE"] = module
        # CID 設定到 mes_info_meta 中
        if "mes_info_meta" not in self.cfg:
            self.cfg["mes_info_meta"] = {}
        if "cid" not in self.cfg.get("mes_info_meta", {}) or not self.cfg.get("mes_info_meta", {}).get("cid"):
            self.cfg["mes_info_meta"]["cid"] = cid
        if "cpu_name" not in self.cfg or not self.cfg.get("cpu_name"):
            self.cfg["cpu_name"] = cpu_name
        if "mem_info" not in self.cfg or not self.cfg.get("mem_info"):
            self.cfg["mem_info"] = mem_info

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

        # 連接風扇人工判斷 checkbox，控制輸入框啟用/禁用
        self.ui.FAN1_people_checkBox.toggled.connect(self.fan_manual_checkboxes)
        self.ui.FAN2_people_checkBox.toggled.connect(self.fan_manual_checkboxes)
        self.ui.FAN3_people_checkBox.toggled.connect(self.fan_manual_checkboxes)
        self.ui.FAN4_people_checkBox.toggled.connect(self.fan_manual_checkboxes)
        self.ui.FAN5_people_checkBox.toggled.connect(self.fan_manual_checkboxes)

        # 連接 GPIO 燈號測試模式 checkbox，控制 IN 欄位啟用/禁用
        gpio_people_cb = getattr(self.ui, "gpio_people_checkBox", None)
        if gpio_people_cb:
            gpio_people_cb.toggled.connect(self.gpio_led_mode_checkbox)

        # 先載入三種設定檔，把 self.cfg 填滿
        # self.load_ini_into_cfg()   # ./mb_test_config.ini
        # self.load_yaml_cfg()       # ./mb_test_config.yaml
        self.load_toml_cfg()       # ./mb_test_config.toml

        # 接著設定輸入限制（驗證器）
        # self.init_config_tab_validators() # 先註解掉, 避免影響 EEPROM 設定

        # 把 self.cfg 的值回填到 UI
        self.apply_tomlcfg_to_ui()
        self.lock_items_from_toml()  # ★ 新增：依照勾選狀態鎖住其它項目

        # 讀完 TOML 之後：
        #   - 有成功讀到 TOML → checkbox 只保留「被 TOML 內容」的項目，其餘灰階
        #   - 沒有 TOML → checkbox 所有項目都開放可以選
        if getattr(self, "toml_loaded", False):
            self.lock_items_from_toml() # 只保留「被 TOML 內容」的項目，其餘灰階
        else:
            self.unlock_all_items_from_toml() # checkbox 所有項目都開放可以選

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

    # ===== Fan Setting Tab =====
    def fan_manual_checkboxes(self):
        """
        勾選『人工判斷』就鎖定該顆 FAN 的欄位，
        取消勾選就解鎖。支援 FAN1~FAN5。
        """
        for fan_num in range(1, 6): # FAN1~FAN5
            # 取得 FAN1~FAN5 的 checkbox
            check = getattr(self.ui, f"FAN{fan_num}_people_checkBox", None) # 取得 FAN1~FAN5 的 checkbox
            low = getattr(self.ui, f"FAN{fan_num}_LOW_speed_lineEdit", None) # 取得 FAN1~FAN5 的 LOW_speed_lineEdit
            high = getattr(self.ui, f"FAN{fan_num}_HIGH_speed_lineEdit", None) # 取得 FAN1~FAN5 的 HIGH_speed_lineEdit
            tol = getattr(self.ui, f"FAN{fan_num}_Tolerance_lineEdit", None) # 取得 FAN1~FAN5 的 Tolerance_lineEdit

            if check.isChecked(): # 如果 checkbox 打勾則禁用 FAN1~FAN5 的輸入框
                low.setEnabled(False) # 禁用 FAN1~FAN5 的 LOW_speed_lineEdit
                high.setEnabled(False) # 禁用 FAN1~FAN5 的 HIGH_speed_lineEdit
                tol.setEnabled(False) # 禁用 FAN1~FAN5 的 Tolerance_lineEdit
            else: # 如果 checkbox 取消勾選則啟用 FAN1~FAN5 的輸入框
                low.setEnabled(True) # 啟用 FAN1~FAN5 的 LOW_speed_lineEdit
                high.setEnabled(True) # 啟用 FAN1~FAN5 的 HIGH_speed_lineEdit
                tol.setEnabled(True) # 啟用 FAN1~FAN5 的 Tolerance_lineEdit

    def gpio_led_mode_checkbox(self):
        """
        勾選『燈號測試模式』就禁用所有 GPIO IN 欄位（GPI_num, GPI_pin），
        取消勾選就啟用。因為 LED 燈號測試只需要 OUT pin，不需要 IN pin。
        """
        gpio_people_cb = getattr(self.ui, "gpio_people_checkBox", None)
        if not gpio_people_cb:
            return
        
        is_led_mode = gpio_people_cb.isChecked()
        
        # 遍歷所有可能的 GPIO pairs（通常最多 32 組）
        row = 1
        while True:
            gpi_num = getattr(self.ui, f"GPI_num{row}_lineEdit", None)
            gpi_pin = getattr(self.ui, f"GPI_pin{row}_lineEdit", None)
            
            # 如果找不到這個欄位，表示已經到最後一組了
            if not gpi_num or not gpi_pin:
                break
            
            # 根據 checkbox 狀態啟用/禁用 IN 欄位
            gpi_num.setEnabled(not is_led_mode)  # LED 模式時禁用
            gpi_pin.setEnabled(not is_led_mode)  # LED 模式時禁用
            
            row += 1

    # ===== Config Tab =====
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

    def read_combo_int(self, *widget_names, default=0): # 讀取 combobox 的 currentText 並轉 int
        """依序嘗試以 objectName 取得 combobox，讀取 currentText 並轉 int。"""
        for name in widget_names:
            w = getattr(self.ui, name, None)
            if w and hasattr(w, "currentText"):
                try:
                    return int(w.currentText()) # 嘗試轉 int
                except Exception:
                    pass
        return default

    def save_ekey_section(self, data: dict, prefix: str, count: int):
        """
        存 [E-Key] 區段，欄位名稱用 EKEY_path_#
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
                sec[f"EKEY_path_{i}"] = txt
                has_item = True

        # 只有當有至少一個 PATH 時才寫入，否則也刪掉
        if has_item:
            data["E-Key"] = sec
        else:
            data.pop("E-Key", None)

    # 當數量 + 多個 xxx_1_lineEdit～xxx_10_lineEdit」的結構，所以可以用這個函數來保存。
    def save_multi_port_section(self, data, toml_func_name, ui_name, toml_func_path_name, count):
        """
        通用版本：
        專門給 E-Key / RS232 / RS422 / RS485 / UART 用
        - UI 物件： <ui_name>_<i>_lineEdit
        - TOML Key：<toml_func_path_name>_<i>
        例如：
        RS232 → ui_name="rs232" 後續程式會帶入組合名稱出來, toml_func_path_name="RS232_path"
        E-Key → ui_name="ekey" 後續程式會帶入組合名稱出來, toml_func_path_name="EKEY_path"
        
        修改：不管 count 多少，都會檢查所有可能的路徑並保存所有有內容的路徑
        """
        if count <= 0:
            data.pop(toml_func_name, None)
            return

        sec = {"expect": count}
        has_item = False

        # 檢查所有可能的路徑（最多檢查到 10 個，涵蓋大部分情況）
        # 這樣即使 count=1，但填寫了多個路徑，也會全部保存
        max_check = 10
        for i in range(1, max_check + 1):
            # UI 物件名稱（通常小寫）
            le = getattr(self.ui, f"{ui_name}_{i}_lineEdit", None)
            if not le:
                # 如果這個 lineEdit 不存在，繼續檢查下一個
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

    def save_toml_cfg(self, toml_name=None): # 存檔時, 自動使用 DTS name 作為檔名, toml_name 的功能是提供給呼叫端可以指定要存檔的檔名
        """
        直接從 UI 抓所有設定，組成 dict 並：
        1) 清空並更新 self.cfg
        2) 寫入 TOML 檔案
        3) 回傳 data（給呼叫端顯示/調用）
        
        如果 toml_name 為 None，則自動使用 DTS name 作為檔名：
        - 如果抓取到 DTS name，使用 ./{dts_name}.toml
        - 如果沒有抓取到 DTS name，則使用 x86 name 作為檔名，使用 ./{x86_name}.toml
        - 如果沒有抓取到 x86 name，使用預設名稱 ./mb_test_config.toml
        """
        # import toml, re  # ← 需要 re 給 parse_hex 用
        
        # 如果 toml_name 為 None，自動使用 DTS name 或 OEM 名稱作為檔名
        if toml_name is None:
            sys_info = self.get_dts_and_x86_name()
            print(f"按下存檔按鈕時, 取得 DTS name: {sys_info}") # 印出 DTS name, debug用
            dts_name = sys_info.get("dts", "")
            
            # 處理 DTS name：去掉 .dts 後綴（如果有的話），並清理特殊字元
            if dts_name and dts_name != "(There is no DTS)": # Jetson/ARM 平台：使用 DTS name
                # 去掉 .dts 後綴
                if dts_name.endswith('.dts'):
                    dts_name = dts_name[:-4]
                # 清理檔名不允許的字元（保留底線、連字號、點號）
                dts_name = re.sub(r'[<>:"/\\|?*]', '_', dts_name) # 清理檔名不允許的字元（保留底線、連字號、點號）
                toml_name = f"./{dts_name}.toml" # 將 DTS name 轉換為 TOML 檔名
            else:
                # x86 平台：從系統讀取 board_name 作為 TOML 檔名（與 Jetson 使用 DTS name 的方式一致）
                x86_name = self.read_text("/sys/class/dmi/id/board_name", "")  # 直接從系統檔案讀取
                if x86_name and x86_name != "-":
                    # 清理檔名不允許的字元（保留底線、連字號、點號）
                    x86_name = re.sub(r'[<>:"/\\|?*]', '_', x86_name)
                    toml_name = f"./{x86_name}.toml"  # 將 board_name 轉換為 TOML 檔名
                else:
                    # 如果無法取得 board_name，使用預設檔名
                    toml_name = "./mb_test_config.toml"

        def parse_hex(s, default=0x55):
            """
            將字串 s 轉換為整數，如果 s 以 "0x" 開頭，則轉換為 16 進位，
            如果 s 是 16 進位格式，則轉換為 16 進位，如果 s 是 10 進位格式，
            則轉換為 10 進位，如果 s 無法轉換為整數，則返回 default
            """
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
        mkey_expect = self.read_combo_int("mkey_comboBox", default=0)
        if mkey_expect > 0:
            data["M-Key"] = {"expect": mkey_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== E-Key =====
        ekey_expect = self.read_combo_int("ekey_comboBox", default=0)
        self.save_multi_port_section(data, "E-Key", "ekey", "EKEY_path", ekey_expect) 

        # ===== B-Key =====
        bkey_expect = self.read_combo_int("bkey_comboBox", default=0)
        self.save_multi_port_section(data, "B-KEY", "bkey", "BKEY_path", bkey_expect)

        # ===== CPU =====
        cpu_expect = self.read_combo_int("cpu_comboBox", default=0)
        self.save_multi_port_section(data, "CPU", "cpu", "CPU_MODEL", cpu_expect) # 這裡是回填文字到UI, cpu_1_lineEdit ~ cpu_5_lineEdit, 如果 cpu_models 的長度小於 i, 則清空文字到UI

        # ===== MEMORY =====
        mem_expect = self.read_combo_int("memory_comboBox", default=0)
        self.save_multi_port_section(data, "MEMORY", "mem", "MEMORY_SIZE", mem_expect) # 這裡是回填文字到UI, mem_1_lineEdit ~ mem_5_lineEdit, 如果 mem_sizes 的長度小於 i, 則清空文字到UI

        # ===== BIOS VERSION =====（與 CPU、MEM 同用法：biosver_1_lineEdit → BIOSVERSION_name_1）
        biosver_expect = self.read_combo_int("biosver_comboBox", default=0)
        self.save_multi_port_section(data, "BIOS VERSION", "biosver", "BIOSVERSION_name", biosver_expect)

        # ===== HW PRODUCT NAME =====
        hwproductname_expect = self.read_combo_int("hwproductname_comboBox", default=0)
        self.save_multi_port_section(data, "HW PRODUCT NAME", "hwproductname", "HWPRODUCTNAME_name", hwproductname_expect)

        # ===== Network =====
        network_expect = self.read_combo_int("network_comboBox", default=0)
        if network_expect > 0:
            ip = (getattr(self.ui, "IP_lineEdit", None).text() or "").strip()
            data["Network"] = {"expect": network_expect}
            if ip:
                data["Network"]["ping_ip"] = ip
        else:
            data.pop("Network", None)

        # ===== FIBER =====
        fiber_expect = self.read_combo_int("fiber_comboBox", default=0)
        if fiber_expect > 0:
            data["OPTICAL FIBER"] = {"expect": fiber_expect}
            # 可選：如果 UI 中有手動指定的接口，也保存（類似 RS232）
            # 但光纖測試支援自動掃描，所以接口列表是可選的
            for i in range(1, fiber_expect + 1):
                le = getattr(self.ui, f"fiber_{i}_lineEdit", None)
                if le:
                    txt = (le.text() or "").strip()
                    if txt:
                        data["OPTICAL FIBER"][f"FIBER_path_{i}"] = txt
        else:
            data.pop("OPTICAL FIBER", None)

        # ===== MIC =====
        mic_expect = self.read_combo_int("mic_comboBox", default=0)
        if mic_expect > 0:
            data["MIC"] = {"expect": mic_expect} # 這裡[]內的名稱會寫入 TOML
        else:
            data.pop("MIC", None) # 如果 mic_expect 小於0, 則刪除 MIC 區段

        # ===== LINE IN =====
        linein_expect = self.read_combo_int("linein_comboBox", default=0)
        if linein_expect > 0:
            data["LINE IN"] = {"expect": linein_expect}
        else:
            data.pop("LINE IN", None) # 如果 linein_expect 小於0, 則刪除 LINE IN 區段

        # ===== SPEAKER =====
        speaker_expect = self.read_combo_int("speaker_comboBox", default=0)
        if speaker_expect > 0:
            data["SPEAKER"] = {"expect": speaker_expect}
        else:
            data.pop("SPEAKER", None) # 如果 speaker_expect 小於0, 則刪除 SPEAKER 區段

        # ===== CAN BUS =====
        canbus_expect = self.read_combo_int("canbus_comboBox", default=0)
        if canbus_expect > 0:
            data["CANBUS"] = {"expect": canbus_expect}
            # 可選：如果 UI 中有手動指定的介面，也保存
            canbus_items = []
            for i in range(1, canbus_expect + 1):
                le = getattr(self.ui, f"canbus_{i}_lineEdit", None)
                if le:
                    txt = (le.text() or "").strip()
                    if txt:
                        canbus_items.append(txt)
            if canbus_items:
                data["CANBUS"]["CANBUS_items"] = canbus_items
        else:
            data.pop("CANBUS", None)

        # ===== Micro SD =====
        microsd_expect = self.read_combo_int("microsd_comboBox", default=0)
        if microsd_expect > 0:
            data["Micro SD Card"] = {"expect": microsd_expect} # 這裡[]內的名稱會寫入 TOML

        # ===== RS232 =====
        rs232_expect = self.read_combo_int("rs232_comboBox", default=0)
        self.save_multi_port_section(data, "RS232", "rs232", "RS232_path", rs232_expect)

        # ===== RS422 =====
        rs422_expect = self.read_combo_int("rs422_comboBox", default=0) # 這行的功能是讀取 combobox 的值並轉成 int
        self.save_multi_port_section(data, "RS422", "rs422", "RS422_path", rs422_expect) # 如果期望數量大於0, 就依序取 UI 欄位, 寫入 data dict 裡面, 否則刪掉舊資料, 寫入 toml 檔案, 回傳 data dict 給呼叫端顯示/調用

        # ===== RS485 =====
        rs485_expect = self.read_combo_int("rs485_comboBox", default=0)
        self.save_multi_port_section(data, "RS485", "rs485", "RS485_path", rs485_expect)

        # ===== UART =====
        uart_expect = self.read_combo_int("uart_comboBox", default=0)
        self.save_multi_port_section(data, "UART", "uart", "UART_path", uart_expect)

        # ===== SPI =====
        spi_expect = self.read_combo_int("spi_comboBox", default=0)
        self.save_multi_port_section(data, "SPI", "spi", "SPI_path", spi_expect)
        # 補上 precmd（只在 spi_expect > 0 時才寫入）
        if spi_expect > 0: # 如果 spi_expect 大於0, 才寫入 precmd
            precmd_le = getattr(self.ui, "spi_precmd_lineEdit", None) # 從 ui 取得 precmd 元件
            if precmd_le: # 如果 precmd 元件存在
                precmd = precmd_le.text().strip() # 從 precmd 元件上取得值並去除空白
                if precmd: # 如果 precmd 有值
                    spi_cfg = data.get("SPI") # 從 toml 的 SPI 區段裡找到 precmd 的值
                    if spi_cfg is not None: # 如果 spi_cfg 不是空的
                        spi_cfg["precmd"] = precmd # 把 precmd 寫入 toml 的 SPI 區段

        # ===== CAMERA =====
        camera_expect = self.read_combo_int("camera_comboBox", default=0)
        if camera_expect > 0:
            data["CAMERA"] = {"expect": camera_expect}

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
            # 讀取 UI 欄位，如果為空就不寫入預設值（保持空白）
            bus_le = getattr(self.ui, "BUS_lineEdit", None)
            addr_le = getattr(self.ui, "Addre_lineEdit", None)
            gpio_num_le = getattr(self.ui, "GPIO_NUM_lineEdit", None)
            gpio_pin_le = getattr(self.ui, "GPIO_PIN_lineEdit", None)
            pn_le = getattr(self.ui, "PN_lineEdit", None)
            board_name_le = getattr(self.ui, "Board_NAME_lineEdit", None)
            board_rev_le = getattr(self.ui, "Board_Revision_lineEdit", None)
            
            # 讀取值，如果欄位為空則使用 None（不自動填入預設值）
            eeprom_bus_text = bus_le.text().strip() if bus_le else ""
            eeprom_addr_text = addr_le.text().strip() if addr_le else ""
            eeprom_gpio_num_text = gpio_num_le.text().strip() if gpio_num_le else ""
            eeprom_gpio_pin_text = gpio_pin_le.text().strip() if gpio_pin_le else ""
            
            eeprom_pn = (pn_le.text().strip() if pn_le else "")
            eeprom_board_name = (board_name_le.text().strip() if board_name_le else "")
            eeprom_board_rev = (board_rev_le.text().strip() if board_rev_le else "")
            
            # 建立 EEPROM 設定字典，只包含有值的欄位
            eeprom_data = {"expect": eeprom_expect}
            
            # 只有欄位不為空時才寫入
            if eeprom_bus_text:
                try:
                    eeprom_data["eeprom_i2c_bus"] = int(eeprom_bus_text)
                except ValueError:
                    pass  # 如果轉換失敗就跳過
            
            if eeprom_addr_text:
                try:
                    eeprom_addr = parse_hex(eeprom_addr_text)
                    eeprom_data["eeprom_i2c_addr"] = f"0x{eeprom_addr:02X}"
                except ValueError:
                    pass  # 如果轉換失敗就跳過
            
            if eeprom_gpio_num_text:
                try:
                    eeprom_data["eeprom_gpio_write_num"] = int(eeprom_gpio_num_text)
                except ValueError:
                    pass  # 如果轉換失敗就跳過
            
            if eeprom_gpio_pin_text:
                eeprom_data["eeprom_gpio_write_pin"] = eeprom_gpio_pin_text
            
            if eeprom_pn:
                eeprom_data["pn"] = eeprom_pn
            
            if eeprom_board_name:
                eeprom_data["board_name"] = eeprom_board_name
            
            if eeprom_board_rev:
                eeprom_data["board_revision"] = eeprom_board_rev
            
            data["EEPROM"] = eeprom_data

        # ===== EEPROM RD Test =====
        # 注意：EEPROM RD Test 與 EEPROM 共用同一個 [EEPROM] 區段的配置
        # 所以這裡只需要寫入 [EEPROM RD TEST] 區段的 expect，配置會從 [EEPROM] 區段讀取
        eeprom_rd_expect = self.read_combo_int("eepromrdrd_comboBox", default=0)
        if eeprom_rd_expect > 0:
            data["EEPROM RD TEST"] = {"expect": eeprom_rd_expect}
            
            # 如果 EEPROM 沒有勾選，但 EEPROM RD Test 有勾選，需要確保 [EEPROM] 區段有基本配置
            # 這樣 EEPROM_RD_test() 才能讀取到 i2c_bus, i2c_addr, gpio_write_num, gpio_write_pin
            if eeprom_expect <= 0:
                # 讀取 UI 欄位（只讀取基本配置，不包含 pn, board_name, board_revision）
                bus_le = getattr(self.ui, "BUS_lineEdit", None)
                addr_le = getattr(self.ui, "Addre_lineEdit", None)
                gpio_num_le = getattr(self.ui, "GPIO_NUM_lineEdit", None)
                gpio_pin_le = getattr(self.ui, "GPIO_PIN_lineEdit", None)
                
                eeprom_bus_text = bus_le.text().strip() if bus_le else ""
                eeprom_addr_text = addr_le.text().strip() if addr_le else ""
                eeprom_gpio_num_text = gpio_num_le.text().strip() if gpio_num_le else ""
                eeprom_gpio_pin_text = gpio_pin_le.text().strip() if gpio_pin_le else ""
                
                # 建立基本 EEPROM 設定字典（只包含基本配置）
                eeprom_rd_data = {}
                
                # 只有欄位不為空時才寫入
                if eeprom_bus_text:
                    try:
                        eeprom_rd_data["eeprom_i2c_bus"] = int(eeprom_bus_text)
                    except ValueError:
                        pass
                
                if eeprom_addr_text:
                    try:
                        eeprom_addr = parse_hex(eeprom_addr_text)
                        eeprom_rd_data["eeprom_i2c_addr"] = f"0x{eeprom_addr:02X}"
                    except ValueError:
                        pass
                
                if eeprom_gpio_num_text:
                    try:
                        eeprom_rd_data["eeprom_gpio_write_num"] = int(eeprom_gpio_num_text)
                    except ValueError:
                        pass
                
                if eeprom_gpio_pin_text:
                    eeprom_rd_data["eeprom_gpio_write_pin"] = eeprom_gpio_pin_text
                
                # 如果 [EEPROM] 區段不存在，就建立基本配置
                # 如果已存在（因為 EEPROM 有勾選），就不覆蓋，保留完整配置
                if "EEPROM" not in data and eeprom_rd_data:
                    data["EEPROM"] = eeprom_rd_data

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
            # 讀取 led_mode checkbox 狀態（燈號測試模式）
            peoplecheck_mode_cb = getattr(self.ui, "gpio_people_checkBox", None)
            people_mode = peoplecheck_mode_cb.isChecked() if peoplecheck_mode_cb else False
            
            # 找出所有實際填寫的內容（檢查範圍：1 到 100，或直到找不到 UI 物件為止）
            for i in range(1, 101):  # 檢查 1 到 100 組
                gpo_num = getattr(self.ui, f"GPO_num{i}_lineEdit", None)
                gpo_pin = getattr(self.ui, f"GPO_pin{i}_lineEdit", None)
                gpi_num = getattr(self.ui, f"GPI_num{i}_lineEdit", None)
                gpi_pin = getattr(self.ui, f"GPI_pin{i}_lineEdit", None)

                # 如果 UI 物件不存在，表示已經到最後一組了
                if not gpo_num or not gpo_pin:
                    break

                gpo_num_txt = gpo_num.text().strip() if gpo_num else "" # 這行功能是取得 GPO_numX_lineEdit 的文字並去除空白
                gpo_pin_txt = gpo_pin.text().strip() if gpo_pin else ""
                gpi_num_txt = gpi_num.text().strip() if gpi_num else ""
                gpi_pin_txt = gpi_pin.text().strip() if gpi_pin else ""

                # 檢查是否有填寫內容（至少要有 OUT 欄位）
                if gpo_num_txt or gpo_pin_txt:
                    if people_mode:
                        # 燈號測試模式：只儲存 OUT 欄位（2 欄位格式）
                        pairs.append(f"{gpo_num_txt},{gpo_pin_txt}")
                    else:
                        # Loopback 測試模式：儲存完整 4 欄位格式
                        if gpo_num_txt or gpo_pin_txt or gpi_num_txt or gpi_pin_txt:
                            pairs.append(f"{gpo_num_txt},{gpo_pin_txt},{gpi_num_txt},{gpi_pin_txt}")

            data["GPIO"] = {
                "expect": gpio_expect,
                "pairs": pairs,
                "led_mode": people_mode,  # 燈號測試模式：true=人工判斷，false=自動驗證
            }
        else:
            data.pop("GPIO", None)

        # ===== 通用測項保存邏輯 =====
        # key: TOML 區塊名稱, value: UI comboBox 物件名稱, 此次部份僅提供手動測試comboBox項目整合, 如果comboBox的值大於0就存入 data
        combo_map = {
            # "CPU": "cpu_comboBox",
            # "MEMORY": "memory_comboBox",
            "HDMI": "hdmi_comboBox",
            "VGA": "vga_comboBox",
            "DP": "dp_comboBox",
            "LED": "led_comboBox",
            "POWER CONNECTOR": "powerconnector_comboBox",
            "POWER SW CONNECTOR": "powerswconnector_comboBox",
            "POWER BUTTON": "powerbutton_comboBox",
            "RESET BUTTON": "resetbutton_comboBox",
            "RECOVERY BUTTON": "recoverybutton_comboBox",
            "SMA": "sma_comboBox",
            "SW1": "sw1_comboBox",
            "SW2": "sw2_comboBox",
            "MCU Connector": "mcuconnector_comboBox",
            "RTC": "rtc_comboBox",
            "RTC OUT": "rtcout_comboBox",
            "DC INPUT": "dcinput_comboBox",
            "DC OUTPUT": "dcoutput_comboBox",
            "CASE OPEN": "caseopen_comboBox",
            "PD POWER INPUT": "pdpowerinput_comboBox",
            "PSE POWER OUTPUT": "psepoweroutput_comboBox",
            "InnoAgent": "innoagent_comboBox",
            "GPS": "gps_comboBox",
        }

        # 依序讀取 combo 並存入 data
        for section, combo_name in combo_map.items():
            val = self.read_combo_int(combo_name, default=0)
            if val > 0:
                data[section] = {"expect": val}

        self.ui.Information_textEdit.append(f"[DEBUG] Save TOML data: {data}")

        # ===== FTP =====
        target = self.get_ftp_target_from_ui() or self.cfg.get("ftp_target", "")
        if target:
            data["FTP"] = {"target": target}

        # ===== 同步記憶體 cfg（避免殘留舊鍵） =====
        # 保存執行時設定（這些不在 TOML 中，不應該被清空）
        runtime_keys = ["sn", "log_dir", "user_log_path", "mes_info_meta", "meta", "wo", "config_name", "version"]
        saved_runtime = {k: self.cfg[k] for k in runtime_keys if k in self.cfg}
        
        self.cfg.clear()
        self.cfg.update(data)
        
        # 恢復執行時設定
        self.cfg.update(saved_runtime)

        # ===== 寫入 TOML 檔 =====
        with open(toml_name, "w", encoding="utf-8") as f:
            toml.dump(data, f)

        self.ui.Information_textEdit.append(f"[設定檔已儲存] {toml_name}")
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
        bkey                = item_cfg.get("B-KEY", {})
        network             = item_cfg.get("Network", {})
        fiber               = item_cfg.get("OPTICAL FIBER", {})
        canbus              = item_cfg.get("CANBUS", {})
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
        camera              = item_cfg.get("CAMERA", {})
        cpu                 = item_cfg.get("CPU", {})
        memory              = item_cfg.get("MEMORY", {})
        biosver             = item_cfg.get("BIOS VERSION", {})
        hwproductname       = item_cfg.get("HW PRODUCT NAME", {})
        # ===== 手動測項 =====
        mic                 = item_cfg.get("MIC", {})
        linein              = item_cfg.get("LINE IN", {})
        speaker             = item_cfg.get("SPEAKER", {})
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
        case_open           = item_cfg.get("CASE OPEN", {})
        pd_power_input      = item_cfg.get("PD POWER INPUT", {})
        pse_power_output    = item_cfg.get("PSE POWER OUTPUT", {})
        innoagent           = item_cfg.get("InnoAgent", {})
        gps                 = item_cfg.get("GPS", {})

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
        combo_mkey = getattr(self.ui, "mkey_comboBox", None)
        if check_mkey and combo_mkey:
            if mkey and int(mkey.get("expect", 0)) > 0:
                check_mkey.setChecked(True)
                combo_mkey.setCurrentText(str(int(mkey.get("expect", 0))))
            else:
                check_mkey.setChecked(False)

        # E-Key
        check_ekey = getattr(self.ui, "checkBox_EKEY", None)
        combo_ekey = getattr(self.ui, "ekey_comboBox", None)
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
            val = ekey.get(f"EKEY_path_{i}", "") # 這裡是回填文字到UI, cpu_1_lineEdit ~ cpu_5_lineEdit, 如果 cpu_models 的長度小於 i, 則清空文字到UI
            le.setText("" if val is None else str(val))

        # B-Key
        check_bkey = getattr(self.ui, "checkBox_BKEY", None)
        combo_bkey = getattr(self.ui, "bkey_comboBox", None)
        if check_bkey and combo_bkey:
            if bkey and int(bkey.get("expect", 0)) > 0:
                check_bkey.setChecked(True)
                combo_bkey.setCurrentText(str(int(bkey.get("expect", 0))))
            else:
                check_bkey.setChecked(False)
        for i in range(1, 6):
            le = getattr(self.ui, f"bkey_{i}_lineEdit", None)
            if not le:
                continue
            val = bkey.get(f"BKEY_path_{i}", "") # 這裡是回填文字到UI, bkey_1_lineEdit ~ bkey_5_lineEdit
            le.setText("" if val is None else str(val))

        # CPU
        check_cpu = getattr(self.ui, "checkBox_CPU", None)
        combo_cpu = getattr(self.ui, "cpu_comboBox", None)
        if check_cpu and combo_cpu:
            if cpu and int(cpu.get("expect", 0)) > 0:
                check_cpu.setChecked(True)
                combo_cpu.setCurrentText(str(int(cpu.get("expect", 0))))
            else:
                check_cpu.setChecked(False)
        for i in range(1, 5):
            le = getattr(self.ui, f"cpu_{i}_lineEdit", None)
            if not le:
                continue
            val = cpu.get(f"CPU_MODEL_{i}", "")
            le.setText("" if val is None else str(val))

        # MEMORY
        check_mem = getattr(self.ui, "checkBox_MEM", None)
        combo_mem = getattr(self.ui, "memory_comboBox", None)
        if check_mem and combo_mem:
            if memory and int(memory.get("expect", 0)) > 0:
                check_mem.setChecked(True)
                combo_mem.setCurrentText(str(int(memory.get("expect", 0))))
            else:
                check_mem.setChecked(False)
        for i in range(1, 5):
            le = getattr(self.ui, f"mem_{i}_lineEdit", None)
            if not le:
                continue
            val = memory.get(f"MEMORY_SIZE_{i}", "")
            le.setText("" if val is None else str(val))

        # BIOS VERSION（與 CPU、MEM 同用法：BIOSVERSION_name_1 → biosver_1_lineEdit）
        check_biosver = getattr(self.ui, "checkBox_BIOSVER", None)
        combo_biosver = getattr(self.ui, "biosver_comboBox", None)
        if check_biosver and combo_biosver:
            if biosver and int(biosver.get("expect", 0)) > 0:
                check_biosver.setChecked(True)
                combo_biosver.setCurrentText(str(int(biosver.get("expect", 0))))
            else:
                check_biosver.setChecked(False)
        for i in range(1, 11):
            le = getattr(self.ui, f"biosver_{i}_lineEdit", None)
            if not le:
                continue
            val = biosver.get(f"BIOSVERSION_name_{i}", "")
            le.setText("" if val is None else str(val))

        # HW PRODUCT NAME
        check_hwproductname = getattr(self.ui, "checkBox_HWPRODUCTNAME", None)
        combo_hwproductname = getattr(self.ui, "hwproductname_comboBox", None)
        if check_hwproductname and combo_hwproductname:
            if hwproductname and int(hwproductname.get("expect", 0)) > 0:
                check_hwproductname.setChecked(True)
                combo_hwproductname.setCurrentText(str(int(hwproductname.get("expect", 0))))
            else:
                check_hwproductname.setChecked(False)
        for i in range(1, 11):
            le = getattr(self.ui, f"hwproductname_{i}_lineEdit", None)
            if not le:
                continue
            val = hwproductname.get(f"HWPRODUCTNAME_name_{i}", "")
            le.setText("" if val is None else str(val))

        # CAMERA
        check_camera = getattr(self.ui, "checkBox_CAMERA", None)
        combo_camera = getattr(self.ui, "camera_comboBox", None)
        if check_camera and combo_camera:
            if camera and int(camera.get("expect", 0)) > 0:
                check_camera.setChecked(True) # 勾選checkbox
                combo_camera.setCurrentText(str(int(camera.get("expect", 0)))) # 讀取數量, 並設定combobox
            else:
                check_camera.setChecked(False) # 不勾選checkbox

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

        # FIBER
        check_fiber = getattr(self.ui, "checkBox_FIBER", None)
        combo_fiber = getattr(self.ui, "fiber_comboBox", None)
        if check_fiber and combo_fiber:
            if fiber and int(fiber.get("expect", 0)) > 0:
                check_fiber.setChecked(True)
                combo_fiber.setCurrentText(str(int(fiber.get("expect", 0))))
            else:
                check_fiber.setChecked(False)

        # 依序回填 10 格 FIBER_path
        for i in range(1, 11):
            fiber_path = f"FIBER_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_fiber = getattr(self.ui, f"fiber_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_fiber:
                continue
            get_fiber.setText(str(fiber.get(fiber_path, "")))

        # CAN BUS
        check_canbus = getattr(self.ui, "checkBox_CANBUS", None)
        combo_canbus = getattr(self.ui, "canbus_comboBox", None)
        if check_canbus and combo_canbus:
            if canbus and int(canbus.get("expect", 0)) > 0:
                check_canbus.setChecked(True)
                combo_canbus.setCurrentText(str(int(canbus.get("expect", 0))))
            else:
                check_canbus.setChecked(False)

        # 依序回填 CANBUS_items（最多 2 個，因為 expect 只支援 1 或 2）
        canbus_items = canbus.get("CANBUS_items", []) or []
        for i in range(1, 3):  # expect 最多為 2
            get_canbus = getattr(self.ui, f"canbus_{i}_lineEdit", None)
            if not get_canbus:
                continue
            if i <= len(canbus_items): # 這裡是檢查 canbus_items 的長度, 如果 canbus_items 的長度大於 i, 則回填文字到UI, canbus_1_lineEdit ~ canbus_2_lineEdit
                get_canbus.setText(str(canbus_items[i-1])) # 這裡是回填文字到UI, canbus_1_lineEdit ~ canbus_2_lineEdit, 如果 canbus_items 的長度小於 i, 則不回填文字到UI
            else:
                get_canbus.setText("") # 這裡是清空文字到UI, canbus_1_lineEdit ~ canbus_2_lineEdit, 如果 canbus_items 的長度小於 i, 則清空文字到UI

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
        combo_rs232 = getattr(self.ui, "rs232_comboBox", None)
        if check_rs232 and combo_rs232:
            if rs232 and int(rs232.get("expect", 0)) > 0:
                check_rs232.setChecked(True)
                combo_rs232.setCurrentText(str(int(rs232.get("expect", 0))))
            else:
                check_rs232.setChecked(False)

        # 依序回填 10 格 RS232_path
        for i in range(1, 11):
            rs232_path = f"RS232_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs232 = getattr(self.ui, f"rs232_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs232:
                continue
            get_rs232.setText(str(rs232.get(rs232_path, "")))

        # RS422
        check_rs422 = getattr(self.ui, "checkBox_RS422", None)
        combo_rs422 = getattr(self.ui, "rs422_comboBox", None)
        if check_rs422 and combo_rs422:
            if rs422 and int(rs422.get("expect", 0)) > 0:
                check_rs422.setChecked(True)
                combo_rs422.setCurrentText(str(int(rs422.get("expect", 0))))
            else:
                check_rs422.setChecked(False)

        # 依序回填 10 格 RS422_path
        for i in range(1, 11):
            rs422_path = f"RS422_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs422 = getattr(self.ui, f"rs422_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs422:
                continue
            get_rs422.setText(str(rs422.get(rs422_path, "")))


        # RS485
        check_rs485 = getattr(self.ui, "checkBox_RS485", None)
        combo_rs485 = getattr(self.ui, "rs485_comboBox", None)
        if check_rs485 and combo_rs485:
            if rs485 and int(rs485.get("expect", 0)) > 0:
                check_rs485.setChecked(True)
                combo_rs485.setCurrentText(str(int(rs485.get("expect", 0))))
            else:
                check_rs485.setChecked(False)

        # 依序回填 10 格 RS485_path
        for i in range(1, 11):
            rs485_path = f"RS485_path_{i}" # TOML 裡的名稱, 要與 save_toml_cfg 對應, i是 1~10
            get_rs485 = getattr(self.ui, f"rs485_{i}_lineEdit", None) # 主要功能是取得 lineEdit 元件然後回填文字到UI
            if not get_rs485:
                continue
            get_rs485.setText(str(rs485.get(rs485_path, "")))

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
            # 檢查是否為 RD mode，如果是則不勾選 EEPROM
            # MODE 從 mes_info_meta 讀取，與環境變數一致
            mes_info_init = self.cfg.get("mes_info_meta", {}) or {}
            mode = (mes_info_init.get("mode", "") or os.environ.get("MODE", "")).strip().upper()
            if mode == "RD":
                check_eeprom.setChecked(False)
            elif eeprom and int(eeprom.get("expect", 0)) > 0:
                check_eeprom.setChecked(True)
                combo_eeprom.setCurrentText(str(int(eeprom.get("expect", 0))))
            else:
                check_eeprom.setChecked(False)
        # if hasattr(self.ui, "EEPROM_enable_checkBox"):
        #     self.ui.EEPROM_enable_checkBox.setChecked(bool(eeprom.get("enabled", False)))
        if hasattr(self.ui, "BUS_lineEdit"):
            # 只有 TOML 中有值才自動帶入，否則保持空白（不自動填入預設值）
            bus_val = eeprom.get("eeprom_i2c_bus") or eeprom.get("bus")
            if bus_val is not None:
                self.ui.BUS_lineEdit.setText(str(int(bus_val)))
            else:
                self.ui.BUS_lineEdit.setText("")  # 保持空白
        if hasattr(self.ui, "Addre_lineEdit"):
            # 只有 TOML 中有值才自動帶入，否則保持空白（不自動填入預設值）
            addr_val = eeprom.get("eeprom_i2c_addr") or eeprom.get("addr")
            if addr_val is not None:
                if isinstance(addr_val, str) and addr_val.lower().startswith("0x"):
                    self.ui.Addre_lineEdit.setText(addr_val)
                else:
                    self.ui.Addre_lineEdit.setText(hex(int(addr_val)))
            else:
                self.ui.Addre_lineEdit.setText("")  # 保持空白
        if hasattr(self.ui, "GPIO_NUM_lineEdit"):
            # 只有 TOML 中有值才自動帶入，否則保持空白（不自動填入預設值）
            gpio_num_val = eeprom.get("eeprom_gpio_write_num") or eeprom.get("gpio_num")
            if gpio_num_val is not None:
                self.ui.GPIO_NUM_lineEdit.setText(str(int(gpio_num_val)))
            else:
                self.ui.GPIO_NUM_lineEdit.setText("")  # 保持空白
        if hasattr(self.ui, "GPIO_PIN_lineEdit"):
            # 只有 TOML 中有值才自動帶入，否則保持空白（不自動填入預設值）
            gpio_pin_val = eeprom.get("eeprom_gpio_write_pin") or eeprom.get("gpio_pin")
            if gpio_pin_val:
                self.ui.GPIO_PIN_lineEdit.setText(str(gpio_pin_val))
            else:
                self.ui.GPIO_PIN_lineEdit.setText("")  # 保持空白
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
        check_eeprom_rd = getattr(self.ui, "checkBox_EEPROMRD", None)
        combo_eeprom_rd = getattr(self.ui, "eepromrdrd_comboBox", None)
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

        # --- LED 模式 checkbox（燈號測試模式）---
        peoplecheck_mode_cb = getattr(self.ui, "gpio_people_checkBox", None)
        if peoplecheck_mode_cb:
            people_mode = bool(gpio.get("led_mode", False))
            peoplecheck_mode_cb.setChecked(people_mode)

        # MIC
        check_mic = getattr(self.ui, "checkBox_MIC", None)
        combo_mic = getattr(self.ui, "mic_comboBox", None)
        if check_mic and combo_mic: # 有勾選checkbox 且有選擇 combobox
            if mic and int(mic.get("expect", 0)) > 0:
                check_mic.setChecked(True)
                combo_mic.setCurrentText(str(int(mic.get("expect", 0))))
            else:
                check_mic.setChecked(False)

        # LINE IN
        check_linein = getattr(self.ui, "checkBox_LINEIN", None)
        combo_linein = getattr(self.ui, "linein_comboBox", None)
        if check_linein and combo_linein:
            if linein and int(linein.get("expect", 0)) > 0:
                check_linein.setChecked(True)
                combo_linein.setCurrentText(str(int(linein.get("expect", 0))))
            else:
                check_linein.setChecked(False)
        
        # SPEAKER
        check_speaker = getattr(self.ui, "checkBox_SPEAKER", None)
        combo_speaker = getattr(self.ui, "speaker_comboBox", None)
        if check_speaker and combo_speaker:
            if speaker and int(speaker.get("expect", 0)) > 0:
                check_speaker.setChecked(True)
                combo_speaker.setCurrentText(str(int(speaker.get("expect", 0))))
            else:
                check_speaker.setChecked(False)
                
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
        check_POWER_BUTTON = getattr(self.ui, "checkBox_POWERBUTTON", None)
        combo_POWER_BUTTON = getattr(self.ui, "powerbutton_comboBox", None)
        if check_POWER_BUTTON and combo_POWER_BUTTON:
            # power_btn = c.get("POWER BUTTON", {})
            if power_btn and int(power_btn.get("expect", 0)) > 0: # 有設定且大於0
                check_POWER_BUTTON.setChecked(True) # 勾選checkbox
                combo_POWER_BUTTON.setCurrentText(str(int(power_btn.get("expect", 0)))) # 設定combobox
            else:
                check_POWER_BUTTON.setChecked(False) # 不勾選checkbox

        # POWER CONNECTOR
        check_POWER_CONNECTOR = getattr(self.ui, "checkBox_POWERCONNECTOR", None)
        combo_POWER_CONNECTOR = getattr(self.ui, "powerconnector_comboBox", None)
        if check_POWER_CONNECTOR and combo_POWER_CONNECTOR:
            # power_connector = c.get("POWER CONNECTOR", {})
            if power_connector and int(power_connector.get("expect", 0)) > 0:
                check_POWER_CONNECTOR.setChecked(True)
                combo_POWER_CONNECTOR.setCurrentText(str(int(power_connector.get("expect", 0))))
            else:
                check_POWER_CONNECTOR.setChecked(False)
        
        # POWER SW CONNECTOR
        check_POWER_SW_CONNECTOR = getattr(self.ui, "checkBox_POWERSWCONNECTOR", None)
        combo_POWER_SW_CONNECTOR = getattr(self.ui, "powerswconnector_comboBox", None)
        if check_POWER_SW_CONNECTOR and combo_POWER_SW_CONNECTOR:
            # power_sw = c.get("POWER SW CONNECTOR", {})
            if power_sw and int(power_sw.get("expect", 0)) > 0:
                check_POWER_SW_CONNECTOR.setChecked(True)
                combo_POWER_SW_CONNECTOR.setCurrentText(str(int(power_sw.get("expect", 0))))
            else:
                check_POWER_SW_CONNECTOR.setChecked(False)

        # RESET BUTTON
        # if hasattr(self.ui, "checkBox_Reset_Button") and hasattr(self.ui, "reset_button_comboBox"):
        check_RESET_BUTTON = getattr(self.ui, "checkBox_RESETBUTTON", None)
        combo_RESET_BUTTON = getattr(self.ui, "resetbutton_comboBox", None)
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
        check_RECOVERY_BUTTON = getattr(self.ui, "checkBox_RECOVERYBUTTON", None)
        combo_RECOVERY_BUTTON = getattr(self.ui, "recoverybutton_comboBox", None)
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
        check_MCU_CONNECTOR = getattr(self.ui, "checkBox_MCUCONNECTOR", None)
        combo_MCU_CONNECTOR = getattr(self.ui, "mcuconnector_comboBox", None)
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
        check_RTC_OUT = getattr(self.ui, "checkBox_RTCOUT", None)
        combo_RTC_OUT = getattr(self.ui, "rtcout_comboBox", None)
        if check_RTC_OUT and combo_RTC_OUT:
            # rtc_out = c.get("RTC OUT", {})
            if rtc_out and int(rtc_out.get("expect", 0)) > 0:
                check_RTC_OUT.setChecked(True)
                combo_RTC_OUT.setCurrentText(str(int(rtc_out.get("expect", 0))))
            else:
                check_RTC_OUT.setChecked(False)

        # DC INPUT
        # if hasattr(self.ui, "checkBox_DC_INPUT") and hasattr(self.ui, "dc_input_comboBox"):
        check_DC_INPUT = getattr(self.ui, "checkBox_DCINPUT", None)
        combo_DC_INPUT = getattr(self.ui, "dcinput_comboBox", None)
        if check_DC_INPUT and combo_DC_INPUT:
            # dc_input = c.get("DC INPUT", {})
            if dc_input and int(dc_input.get("expect", 0)) > 0:
                check_DC_INPUT.setChecked(True)
                combo_DC_INPUT.setCurrentText(str(int(dc_input.get("expect", 0))))
            else:
                check_DC_INPUT.setChecked(False)

        # DC OUTPUT
        # if hasattr(self.ui, "checkBox_DC_OUTPUT") and hasattr(self.ui, "dc_output_comboBox"):
        check_DC_OUTPUT = getattr(self.ui, "checkBox_DCOUTPUT", None)
        combo_DC_OUTPUT = getattr(self.ui, "dcoutput_comboBox", None)
        if check_DC_OUTPUT and combo_DC_OUTPUT:
            # dc_output = c.get("DC OUTPUT", {})
            if dc_output and int(dc_output.get("expect", 0)) > 0:
                check_DC_OUTPUT.setChecked(True)
                combo_DC_OUTPUT.setCurrentText(str(int(dc_output.get("expect", 0))))
            else:
                check_DC_OUTPUT.setChecked(False)

        # CASE OPEN
        check_CASE_OPEN = getattr(self.ui, "checkBox_CASEOPEN", None)
        combo_CASE_OPEN = getattr(self.ui, "caseopen_comboBox", None)
        if check_CASE_OPEN and combo_CASE_OPEN:
            if case_open and int(case_open.get("expect", 0)) > 0:
                check_CASE_OPEN.setChecked(True)
                combo_CASE_OPEN.setCurrentText(str(int(case_open.get("expect", 0))))
            else:
                check_CASE_OPEN.setChecked(False)

        # PD POWER INPUT
        check_PD_POWER_INPUT = getattr(self.ui, "checkBox_PDPOWERINPUT", None)
        combo_PD_POWER_INPUT = getattr(self.ui, "pdpowerinput_comboBox", None)
        if check_PD_POWER_INPUT and combo_PD_POWER_INPUT:
            if pd_power_input and int(pd_power_input.get("expect", 0)) > 0:
                check_PD_POWER_INPUT.setChecked(True)
                combo_PD_POWER_INPUT.setCurrentText(str(int(pd_power_input.get("expect", 0))))
            else:
                check_PD_POWER_INPUT.setChecked(False)

        # PSE POWER OUTPUT
        check_PSE_POWER_OUTPUT = getattr(self.ui, "checkBox_PSEPOWEROUTPUT", None)
        combo_PSE_POWER_OUTPUT = getattr(self.ui, "psepoweroutput_comboBox", None)
        if check_PSE_POWER_OUTPUT and combo_PSE_POWER_OUTPUT:
            if pse_power_output and int(pse_power_output.get("expect", 0)) > 0:
                check_PSE_POWER_OUTPUT.setChecked(True)
                combo_PSE_POWER_OUTPUT.setCurrentText(str(int(pse_power_output.get("expect", 0))))
            else:
                check_PSE_POWER_OUTPUT.setChecked(False)

        # InnoAgent
        check_INNOAGENT = getattr(self.ui, "checkBox_INNOAGENT", None)
        combo_INNOAGENT = getattr(self.ui, "innoagent_comboBox", None)
        if check_INNOAGENT and combo_INNOAGENT:
            if innoagent and int(innoagent.get("expect", 0)) > 0:
                check_INNOAGENT.setChecked(True)
                combo_INNOAGENT.setCurrentText(str(int(innoagent.get("expect", 0))))
            else:
                check_INNOAGENT.setChecked(False)

        # GPS
        check_GPS = getattr(self.ui, "checkBox_GPS", None)
        combo_GPS = getattr(self.ui, "gps_comboBox", None)
        if check_GPS and combo_GPS:
            if gps and int(gps.get("expect", 0)) > 0:
                check_GPS.setChecked(True)
                combo_GPS.setCurrentText(str(int(gps.get("expect", 0))))
            else:
                check_GPS.setChecked(False)

        # FTP
        self.apply_ftp_target_to_ui(self.cfg.get("ftp_target", ""))

        # ===== 根據 MODE 禁用 EEPROM checkbox（RD 模式）=====
        # MODE 從 mes_info_meta 讀取，與環境變數一致
        mes_info_init = self.cfg.get("mes_info_meta", {}) or {}
        mode = (mes_info_init.get("mode", "") or os.environ.get("MODE", "")).strip().upper()
        if mode == "RD":
            # 禁用 EEPROM checkbox 及其相關的 UI 元素
            check_eeprom = getattr(self.ui, "checkBox_EEPROM", None)
            if check_eeprom:
                check_eeprom.setEnabled(False)
                check_eeprom.setChecked(False)  # 取消勾選

                # 禁用相關的 comboBox
                combo_eeprom = self.checkbox_to_combo.get(check_eeprom)
                if combo_eeprom:
                    combo_eeprom.setEnabled(False)

                # 禁用相關的 toolButton
                toolbut_eeprom = self.checkbox_to_toolbutton.get(check_eeprom)
                if toolbut_eeprom:
                    toolbut_eeprom.setEnabled(False)

                # 禁用相關的 preview groupBox
                preview_eeprom = self.checkbox_to_preview.get(check_eeprom)
                if preview_eeprom:
                    preview_eeprom.setEnabled(False)

                # 禁用全選與全取消按鈕
                button_all_select = getattr(self.ui, "Button_iTem_Select", None)
                if button_all_select:
                    button_all_select.setEnabled(False)
                button_all_clean = getattr(self.ui, "Button_iTem_Clean", None)
                if button_all_clean:
                    button_all_clean.setEnabled(False)

    def on_config_save(self):
        """按下『儲存設定』：收集 UI → 更新 cfg → 寫 TOML → 訊息回饋。"""
        data = self.save_toml_cfg()  # save_toml_cfg 內會同步 self.cfg，並回傳 data
        self.ui.Information_textEdit.append(f"[Config] 已儲存：{data}")
        QMessageBox.information(self, "Config設定", "Config設定已成功儲存, 請關閉程式並重新開啟, 以讀取Config")
        # 如需立刻套到畫面，可選擇：
        # self.apply_tomlcfg_to_ui(data)

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
    
    def load_toml_cfg(self, toml_file_name=None):
        """
        讀取 TOML 設定檔，並回傳設定值。
        
        如果 path 為 None，則自動選擇 TOML 檔名：
        1. 如果系統有讀到 DTS name，且存在對應的 {dts_name}.toml 檔案，就使用此 TOML
        2. 如果系統沒有讀到 DTS name，或是系統的 DTS name 與 TOML 名稱不匹配（檔案不存在），就使用預設名稱
        """
        # 如果 toml_name 為 None，自動選擇 TOML 檔名
        if toml_file_name is None:
            sys_info = self.get_dts_and_x86_name() # 使用 get_dts_and_x86_name() 函式，取得 DTS name
            print(f"載入TOML 設定檔時, 取得 DTS or x86 name: {sys_info}") # 印出 DTS name, debug用
            dts_name = sys_info.get("dts", "") # 如果沒有讀到 DTS name，則使用預設值 "(There is no DTS)"
            
            # 處理 DTS name：去掉 .dts 後綴（如果有的話），並清理特殊字元
            if dts_name and dts_name != "(There is no DTS)": # Jetson/ARM 平台：使用 DTS name
                # 去掉 .dts 後綴
                if dts_name.endswith('.dts'):
                    dts_name = dts_name[:-4] # 去掉 .dts 後綴
                # 清理檔名不允許的字元（保留底線、連字號、點號）
                dts_name = re.sub(r'[<>:"/\\|?*]', '_', dts_name) # 清理檔名不允許的字元（保留底線、連字號、點號）
                dts_toml_name = f"./{dts_name}.toml" # 將 DTS name 轉換為 TOML 檔名
                
                # 如果對應的 TOML 檔案存在，就使用此檔案
                if os.path.exists(dts_toml_name): # 如果對應的 TOML 檔案存在，就使用此檔名
                    toml_file_name = dts_toml_name # 使用 DTS name 對應的 TOML 檔名
                else:
                    # 如果檔案不存在，使用預設檔名
                    toml_file_name = "./mb_test_config.toml" # 使用預設檔名
            else:
                # x86 平台：從系統讀取 board_name 作為 TOML 檔名（與 Jetson 使用 DTS name 的方式一致）
                x86_name = self.read_text("/sys/class/dmi/id/board_name", "")  # 直接從系統檔案讀取
                if x86_name and x86_name != "-":
                    # 清理檔名不允許的字元（保留底線、連字號、點號）
                    x86_name = re.sub(r'[<>:"/\\|?*]', '_', x86_name)
                    x86_toml_name = f"./{x86_name}.toml"  # 將 board_name 轉換為 TOML 檔名
                    
                    # 如果對應的 TOML 檔案存在，就使用此檔案
                    if os.path.exists(x86_toml_name):
                        toml_file_name = x86_toml_name
                    else:
                        # 如果檔案不存在，使用預設檔名
                        toml_file_name = "./mb_test_config.toml"
                else:
                    # 如果無法取得 board_name，使用預設檔名
                    toml_file_name = "./mb_test_config.toml" # 使用預設檔名
        
        # 標記這次有沒有成功讀到 TOML 設定
        self.toml_loaded = False

        if not os.path.exists(toml_file_name):
            toml_display_name = os.path.basename(toml_file_name)  # 只顯示檔名，不顯示路徑
            # self.ui.Information_textEdit.append(f"未找到TOML 設定檔：{toml_file_name}，使用預設值。")
            # self.ui.config_read_TextLabel.setText(f"未找到TOML 設定檔：{toml_display_name}，使用預設值。")
            self.ui.config_read_TextLabel.setText(f"未找到TOML 設定檔：程式使用預設狀態。")
            self.ui.config_read_TextLabel.setStyleSheet("color: red;")
            self.unlock_all_items_from_toml()      # ★ 全開放
            return
        try:
            with open(toml_file_name, "r", encoding="utf-8") as f:
                data = toml.load(f) or {}
            self.cfg.update(data)
            # 設定全域 TOML 路徑，讓 Test_item.toml_get 使用正確的檔案
            set_current_toml_path(toml_file_name)
            self.ui.Information_textEdit.append(f"載入TOML 設定檔：{toml_file_name}")
            # 顯示實際讀到的 TOML 檔名
            toml_display_name = os.path.basename(toml_file_name)  # 只顯示檔名，不顯示路徑
            self.ui.config_read_TextLabel.setText(f"已讀取 TOML 設定檔：{toml_display_name}")
            self.ui.config_read_TextLabel.setStyleSheet("color: green;")
            self.toml_loaded = True # 標記這次有沒有成功讀到 TOML 設定

        except Exception as e:
            self.ui.Information_textEdit.append(f"[警告] 讀取TOML 設定檔失敗：{toml_file_name} - {e}")
            toml_display_name = os.path.basename(toml_file_name)  # 只顯示檔名，不顯示路徑
            self.ui.config_read_TextLabel.setText(f"讀取 TOML 設定檔失敗：{toml_display_name}")
            self.ui.config_read_TextLabel.setStyleSheet("color: red;")
            QMessageBox.warning(self, "設定檔錯誤", f"讀取 TOML 設定檔失敗：{toml_file_name}\n錯誤：{e}")
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

    def _parse_one_dmidecode_memory_block(self, block_text):
        """
        解析 dmidecode 單一 Memory Device 區塊，回傳 (容量字串, 插槽名稱)。
        容量：'16.0 GiB' 或 '---'；插槽：如 'Controller0-ChannelA-DIMM0'，無則 ''。
        """
        # 插槽名稱（Locator）
        loc_match = re.search(r"\n\s*Locator:\s*(.+)", block_text)
        locator = loc_match.group(1).strip() if loc_match else ""

        # 容量（Size）那一行
        size_match = re.search(r"\n\s*Size:\s*(.+)", block_text)
        if not size_match:
            return ("---", locator)
        size_val = size_match.group(1).strip()

        # 空插槽（no module installed 等）
        if re.search(r"(?i)no module installed|not installed|unknown", size_val):
            return ("---", locator)

        # 數字 + GB/MB → 換算成 GiB 字串
        num_unit = re.match(r"(?i)\s*(\d+(?:\.\d+)?)\s*(GB|MB)\s*$", size_val)
        if num_unit:
            num, unit = float(num_unit.group(1)), num_unit.group(2).upper()
            gib = num if unit == "GB" else num / 1024
            return (f"{gib:.1f} GiB", locator)
        return (size_val, locator)

    def mem_slot_sizes_for_ui(self, max_slots=4):
        """
        向系統取得記憶體插槽資料，回傳「剛好 max_slots 筆」的列表，供 UI 顯示用。
        回傳 [(容量, 插槽名稱), ...]，長度固定為 max_slots（不足補 ("---", "")，超過則截斷）。
        ARM/Jetson：/proc/meminfo（只有總記憶體，無插槽）；x86：dmidecode -t 17（每槽容量與 Locator）。
        對應關係：MAC 的「取系統資料」是 mac_address()，由 all_mac_addresses() 呼叫；MEM 的「取系統資料」是本函式，由 all_mem_slots() 呼叫。
        """
        empty_slot = ("---", "")
        fail_result = [empty_slot] * max_slots

        # --- ARM/Jetson：只有總記憶體，無插槽 ---
        if os.path.exists("/proc/device-tree/model"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            gib = kb / 1024 / 1024
                            size_str = f"{int(gib)} GiB" if gib == int(gib) else f"{gib:.1f} GiB"
                            result = [(size_str, "")] + [empty_slot] * (max_slots - 1)
                            return result[:max_slots]
            except Exception as e:
                self.ui.Information_textEdit.append(f"[MEM] 讀取 /proc/meminfo 失敗：{e}")
                return fail_result

        # --- x86：dmidecode 取得每槽容量與插槽名 ---
        exe = shutil.which("dmidecode")
        if not exe:
            self.ui.Information_textEdit.append("[MEM] 找不到 dmidecode，請安裝（如 sudo apt install dmidecode）")
            return fail_result

        try:
            out = subprocess.check_output(
                [exe, "-t", "17"],
                text=True, stderr=subprocess.STDOUT,
                env={**os.environ, "LANG": "C", "LC_ALL": "C"},
                timeout=6.0
            )
        except subprocess.CalledProcessError as e:
            msg = (e.output or "").strip() if isinstance(e.output, str) else str(e)
            if "permission" in msg.lower():
                self.ui.Information_textEdit.append(
                    "[MEM] dmidecode 權限不足，請執行：\n"
                    "  sudo setcap cap_sys_rawio=ep $(which dmidecode)\n或改用 sudo 執行程式。"
                )
            else:
                self.ui.Information_textEdit.append(f"[MEM] dmidecode 失敗：{msg}")
            return fail_result
        except subprocess.TimeoutExpired:
            self.ui.Information_textEdit.append("[MEM] dmidecode 逾時（>6 秒），請重試或改用 sudo。")
            return fail_result
        except Exception as e:
            self.ui.Information_textEdit.append(f"[MEM] dmidecode 錯誤：{e}")
            return fail_result

        # 依序解析每個 Memory Device 區塊
        blocks = re.split(r"\n\s*Memory Device\s*\n", "\n" + out)
        result = [self._parse_one_dmidecode_memory_block(b) for b in blocks[1:]]

        if not result:
            self.ui.Information_textEdit.append("[MEM] dmidecode 無解析到任何 DIMM。")
            return fail_result

        # 不足 max_slots 則補空槽
        while len(result) < max_slots:
            result.append(empty_slot)
        return result[:max_slots]

    def all_mem_slots(self):
        """把找到的記憶體插槽依序填到 valMEM1..valMEMN，多餘的補 "---"。依 UI 有幾個 valMEM 自動決定欄位數（與 all_mac_addresses 同一寫法）。"""
        # --- 第一步：數 UI 有幾個 MEM 欄位 ---
        # getattr(self.ui, "valMEM1", None) 會取得 self.ui.valMEM1；若沒有這個屬性就回傳 None。
        # 從 valMEM1 開始依序檢查，直到某個 valMEM(N+1) 不存在為止，n_mem_slots 就是欄位數。
        n_mem_slots = 0
        while getattr(self.ui, f"valMEM{n_mem_slots + 1}", None) is not None:
            n_mem_slots += 1
        if n_mem_slots == 0:
            return
        # --- 第二步：取得系統各插槽容量與插槽名（列表，長度 n_mem_slots）---
        mem = self.mem_slot_sizes_for_ui(n_mem_slots) # 取得系統各插槽容量與插槽名（列表，長度 n_mem_slots）
        # --- 第三步：依序填到 valMEM1 ~ valMEM(N)，有資料就填容量(插槽名)，沒有就填 "---" ---
        for i in range(n_mem_slots):
            size_str, locator_str = mem[i] if i < len(mem) else ("---", "") # 有資料就填容量(插槽名)，沒有就填 "---"
            display = f"{size_str} ({locator_str})" if locator_str else size_str
            getattr(self.ui, f"valMEM{i+1}").setText(display)

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
    
    def all_mac_addresses(self): # 此函式的功能是將mac_address()函式的結果依序填到 valMAC1..valMACN
        """把找到的 MAC 依序填到 valMAC1..valMACN，多餘的補 '-'。依 UI 有幾個 valMAC 自動決定欄位數（與 MEM 同一寫法）。"""
        # --- 第一步：數 UI 有幾個 MAC 欄位 ---
        # getattr(self.ui, "valMAC1", None) 會取得 self.ui.valMAC1；若沒有這個屬性就回傳 None。
        # 從 valMAC1 開始依序檢查，直到某個 valMAC(N+1) 不存在為止，n_mac_slots 就是欄位數。
        n_mac_slots = 0 # 設定0是為了讓while迴圈可以正常執行，並且在第一次執行時，n_mac_slots會被設置為1
        while getattr(self.ui, f"valMAC{n_mac_slots + 1}", None) is not None: # 依序檢查 valMAC1, valMAC2, ...
            n_mac_slots += 1 # 有幾個 valMAC 欄位
        if n_mac_slots == 0: # 沒有 valMAC 欄位，直接返回
            return
        # --- 第二步：取得系統所有 MAC 位址（列表）---
        macs_only = [mac for iface, mac in self.mac_address()] # 只取 MAC
        # --- 第三步：依序填到 valMAC1 ~ valMAC(N)，有 MAC 就填，沒有就填 "---" ---
        for i in range(n_mac_slots): # 填 N 個欄位
            label = getattr(self.ui, f"valMAC{i+1}", None) # valMAC1..valMACN
            if label is None: # 找到這個屬性
                continue # 找不到這個屬性，直接跳過
            if i < len(macs_only): # 有對應的 MAC
                label.setText(macs_only[i]) # 填 MAC
            else: # 沒有對應的 MAC
                label.setText("---") # 補 '---'
    
    # ===== 取得系統資訊（BSP、DTS、BOARD、MODULE、CID、CPU、MEMORY）=====
    def get_dts_and_x86_name(self):
        """取得 BSP 和 DTS（參考 test_tool.sh 的做法）
        
        回傳值：
        - platform_type: 平台類型 ("jetson", "rk", "arm", "x86", "unknown")
        - dts: DTS 檔案名稱
        - bsp: BSP 名稱
        - board: 板子名稱
        """
        platform_type = "unknown"
        dts = ""
        bsp = ""
        board = ""
        
        # 1. NVIDIA Jetson 平台
        dts_path = "/proc/device-tree/nvidia,dtsfilename"
        if os.path.exists(dts_path):
            try:
                with open(dts_path, "rb") as f:
                    dts = f.read().rstrip(b'\x00').decode('utf-8', errors='ignore')
                bsp = dts[:-4] if dts.endswith('.dts') else dts  # 去掉 .dts
                platform_type = "jetson"
            except Exception:
                pass
        
        # 2. ARM 平台（包含 RK/Rockchip）
        if not dts and os.path.exists("/proc/device-tree/model"):
            try:
                with open("/proc/device-tree/model", "rb") as f:
                    model = f.read().rstrip(b'\x00').decode('utf-8', errors='ignore')
                dts = "(There is no DTS)"
                bsp = model
                board = model
                
                # 判斷是 RK 還是其他 ARM 平台
                if "rk" in model.lower() or "rockchip" in model.lower():
                    platform_type = "rk"
                else:
                    platform_type = "arm"
            except Exception:
                pass
        
        # 3. x86 平台
        if not bsp:
            platform_type = "x86"
            # 直接從 /sys/class/dmi/id/board_name 讀取板子名稱
            try:
                board_name = self.read_text("/sys/class/dmi/id/board_name", "")
                if board_name and board_name != "-":
                    board = board_name
                    bsp = f"{board_name}"
            except Exception:
                pass
        
        return {
            "platform_type": platform_type,
            "bsp or x86 name": bsp or "",
            "dts": dts or "(There is no DTS)",
            "board": board or ""
        }
    
    def get_board_from_bsp(self, bsp):
        """從 BSP 名稱解析 BOARD（參考 test_tool.sh 的做法）"""
        if not bsp:
            return ""
        
        # 解析 BSP 名稱：JP_R36_4_3_ORIN_AGX_AIB-MX03-A2_STD_v1.0.0_Aetina
        # BOARD 是第 6 個欄位（索引 6）：AIB-MX03-A2
        arr = bsp.split('_')
        if len(arr) >= 7:
            # 檢查是否符合 JP_ 或 RK_ 格式
            if (bsp.startswith('JP_') or bsp.startswith('RK_')) and len(arr) >= 8:
                return arr[6]  # JP 格式：第 7 個欄位（索引 6）
            elif len(arr) >= 7 and 'v' in arr[6]:
                return arr[5]  # R35 格式：第 6 個欄位（索引 5）
        
        return ""
    
    def get_module(self, board):
        """取得 MODULE（參考 test_tool.sh 的做法）"""
        # NVIDIA 平台
        if os.path.exists("/proc/device-tree/nvidia,dtsfilename"):
            if os.path.exists("/proc/device-tree/model"):
                try:
                    with open("/proc/device-tree/model", "rb") as f:
                        return f.read().rstrip(b'\x00').decode('utf-8', errors='ignore')
                except Exception:
                    pass
        
        # ARM 平台
        if os.path.exists("/proc/device-tree/model"):
            try:
                with open("/proc/device-tree/model", "rb") as f:
                    return f.read().rstrip(b'\x00').decode('utf-8', errors='ignore')
            except Exception:
                pass
        
        # 特殊情況：ABBI-120
        try:
            result = subprocess.check_output(["dmidecode"], text=True, stderr=subprocess.DEVNULL, timeout=5)
            if "ABBI-120" in result:
                return "AIP-KQ67"
        except Exception:
            pass
        
        # 預設使用 BOARD
        return board or ""
    
    def get_cid(self):
        """取得 CID（eMMC serial number）"""
        cid_path = "/sys/class/mmc_host/mmc0/mmc0:0001/cid"
        if os.path.exists(cid_path):
            try:
                with open(cid_path, "r") as f:
                    return f.read().strip()
            except Exception:
                pass
        return "(There is no CID)"
    
    def get_cpu_name(self):
        """取得 CPU 名稱"""
        cpuinfo_path = "/proc/cpuinfo"
        if os.path.exists(cpuinfo_path):
            try:
                with open(cpuinfo_path, "r") as f:
                    for line in f:
                        if "model name" in line.lower():
                            # 取得 "model name" 後面的內容
                            parts = line.split(":", 1)
                            if len(parts) == 2:
                                return parts[1].strip()
            except Exception:
                pass
        return "(There is no CPU)"
    
    def get_memory_info(self):
        """取得記憶體資訊（參考 test_tool.sh 的做法）"""
        
        # 先判斷是否為 ARM/Jetson 平台
        is_arm_platform = os.path.exists("/proc/device-tree/model")
        
        # x86 平台：優先使用 dmidecode（與 test_tool.sh 一致）
        if not is_arm_platform:
            exe = shutil.which("dmidecode")
            if exe:
                env = os.environ.copy()
                env["LANG"] = "C"
                env["LC_ALL"] = "C"
                
                try:
                    out = subprocess.check_output(
                        [exe, "-t", "memory"],
                        text=True, stderr=subprocess.DEVNULL, env=env, timeout=6.0
                    )
                    # 取得 Size 資訊（每 5 行取一次，類似 test_tool.sh 的 awk 'NR % 5 == 1'）
                    # test_tool.sh: dmidecode -t memory | grep -i size | awk 'NR % 5 == 1'
                    sizes = []
                    size_lines = []
                    for line in out.split('\n'):
                        if 'Size:' in line and 'size' in line.lower():
                            size_lines.append(line)
                    
                    # 每 5 行取一次（索引 0, 5, 10, ...）
                    for i in range(0, len(size_lines), 5):
                        if i < len(size_lines):
                            line = size_lines[i]
                            # 提取 Size 後面的內容
                            match = re.search(r'Size:\s*(.+)', line, re.IGNORECASE)
                            if match:
                                size_val = match.group(1).strip()
                                if size_val and 'No Module Installed' not in size_val.upper():
                                    sizes.append(size_val)
                    
                    # 組合成字串，用 / 分隔（類似 test_tool.sh 的 MEM_INFO=$MEM_INFO$single_memory\/\）
                    if sizes:
                        return " / ".join(sizes)
                except Exception:
                    pass
        
        # ARM/Jetson 平台：使用 /proc/meminfo（dmidecode 在 ARM 平台可能不可用或資訊不完整）
        if is_arm_platform:
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            # 轉換為 GB，保留 2 位小數，但如果是整數則不顯示小數
                            gb = kb / 1024 / 1024
                            if gb == int(gb):
                                return f"{int(gb)} GB"
                            else:
                                return f"{gb:.2f} GB"
            except Exception:
                pass
        
        # 如果 x86 平台的 dmidecode 失敗，也嘗試使用 /proc/meminfo 作為備用方案
        if not is_arm_platform:
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            gb = kb / 1024 / 1024
                            if gb == int(gb):
                                return f"{int(gb)} GB"
                            else:
                                return f"{gb:.2f} GB"
            except Exception:
                pass
        
        return ""

    def set_related_widgets_enables(self, cb: QCheckBox, enabled: bool):
        """
        依照 checkbox 打勾狀態，把對應的 ComboBox 一起啟用/停用。
        對應關係來自 self.checkbox_to_combo（與 UI 物件名稱一致）。
        """
        if not cb:
            return
        combo = self.checkbox_to_combo.get(cb)
        if combo is not None:
            combo.setEnabled(enabled)
    
    def lock_items_from_toml(self):
        """
        已成功從 TOML 回填 UI 後呼叫：
        - 有勾選的項目：checkbox + comboBox 維持可操作
        - 沒勾選的項目：checkbox + comboBox 全部灰階
        - 對應的 ToolButton 全部灰階
        - RD mode 下：EEPROM checkbox 強制禁用
        """
        # 檢查是否為 RD mode（從 mes_info_meta 讀取，與環境變數一致）
        mes_info_init = self.cfg.get("mes_info_meta", {}) or {}
        mode = (mes_info_init.get("mode", "") or os.environ.get("MODE", "")).strip().upper()
        is_rd_mode = (mode == "RD")
        
        for checkbox, combo in getattr(self, "checkbox_to_combo", {}).items(): # 走訪 checkbox_to_combo 所有測項
            if checkbox is None: # 如果 checkbox 是 None
                continue

            checked = checkbox.isChecked() # 取得 checkbox 是否被勾選

            # RD mode 下，EEPROM checkbox 強制禁用
            if is_rd_mode and checkbox.objectName() == "checkBox_EEPROM":
                checkbox.setEnabled(False)
                checkbox.setChecked(False)  # 取消勾選
                if combo is not None:
                    combo.setEnabled(False)
                toolbut = getattr(self, "checkbox_to_toolbutton", {}).get(checkbox)
                if toolbut is not None:
                    toolbut.setEnabled(False)
                preview = getattr(self, "checkbox_to_preview", {}).get(checkbox)
                if preview is not None:
                    preview.setEnabled(False)
                continue  # 跳過後續處理

            # checkbox 本身
            checkbox.setEnabled(checked) # 啟用 checkbox

            # 對應的 Config comboBox
            if combo is not None:
                combo.setEnabled(checked) # 啟用 comboBox

            # 對應的 ToolButton
            toolbut = getattr(self, "checkbox_to_toolbutton", {}).get(checkbox)
            if toolbut is not None:
                toolbut.setEnabled(checked) # 啟用 toolbutton

            # 對應的 Preview
            preview = getattr(self, "checkbox_to_preview", {}).get(checkbox)
            if preview is not None:
                preview.setEnabled(checked) # 啟用 preview

    def unlock_all_items_from_toml(self):
        """
        沒有載入 TOML 時呼叫：
        - 所有測項 checkbox 都可以勾/取消
        - 所有 Config comboBox 都可以選
        - 對應的 ToolButton 全部可操作
        """
        for checkbox, combo in getattr(self, "checkbox_to_combo", {}).items(): # 走訪 checkbox_to_combo 所有測項
            if checkbox is not None: # 如果 checkbox 不是 None
                checkbox.setEnabled(True) # 啟用 checkbox
            if combo is not None: # 如果 comboBox 不是 None
                combo.setEnabled(True) # 啟用 comboBox

        # 對應的 ToolButton 全部可操作
        for checkbox, toolbut in getattr(self, "checkbox_to_toolbutton", {}).items(): # 走訪 checkbox_to_toolbutton 所有測項
            if checkbox is not None: # 如果 checkbox 不是 None
                toolbut.setEnabled(True) # 啟用 toolbutton

        for checkbox, preview in getattr(self, "checkbox_to_preview", {}).items(): # 走訪 checkbox_to_preview 所有測項
            if checkbox is not None: # 如果 checkbox 不是 None
                preview.setEnabled(True) # 啟用 preview

        # 啟用全選與全取消按鈕
        button_all_select = getattr(self.ui, "Button_iTem_Select", None)
        if button_all_select:
            button_all_select.setEnabled(True)
        button_all_clean = getattr(self.ui, "Button_iTem_Clean", None)
        if button_all_clean:
            button_all_clean.setEnabled(True)
    
    # def validate_test_config(self) -> bool:
    #     """
    #     通用檢查：
    #     - 走遍 BTN_MAP 裡的自動測項
    #     - 若 checkbox 有勾，且找得到對應的 combobox
    #     就要求 combobox 的數量 > 0
    #     - 找不到 combobox 的項目視為「不需要數量」，直接略過
    #     """

    #     for display_name, cb in getattr(self, "BTN_MAP", {}).items(): # 走訪 BTN_MAP 所有測項
    #         if not cb:
    #             continue

    #         # 只檢查「有勾選」的項目
    #         if not cb.isChecked():
    #             continue

    #         obj_name = cb.objectName() or ""
    #         if not obj_name.startswith("checkBox_"):
    #             continue

    #         # 由 checkbox 名稱推 combobox 名稱
    #         base = obj_name[len("checkBox_"):]   # 例如 "USB2" / "MICROSD" / "MKEY" / "GPIO"

    #         candidate_names = [
    #             f"{base}_comboBox",          # USB2_comboBox / MKEY_comboBox / EKEY_comboBox ...
    #             f"{base.lower()}_comboBox",  # usb2_comboBox / microsd_comboBox / gpio_comboBox ...
    #             f"{base.capitalize()}_comboBox",  # MicroSD_comboBox 之類，保險用
    #         ]

    #         combo = None
    #         for name in candidate_names:
    #             w = getattr(self.ui, name, None)
    #             if w is not None:
    #                 combo = w
    #                 break

    #         # 沒有找到 combobox → 視為這個測項不需要「數量」，直接跳過
    #         if combo is None:
    #             continue

    #         # 讀 combobox 裡的數字
    #         text = (combo.currentText() or "").strip()
    #         try:
    #             exp = int(text)
    #         except Exception:
    #             exp = 0

    #         if exp <= 0:
    #             QMessageBox.warning(
    #                 self,
    #                 "設定錯誤",
    #                 f"{display_name} 有勾選但數量是 0，請先在 Config 設定 {display_name} 數量。",
    #             )
    #             combo.setFocus()
    #             return False

    #     return True
    def validate_test_config(self) -> bool:
        """
        通用檢查：
        - 走遍 BTN_MAP（也就是所有自動測項的 checkbox）
        - 若 checkbox 有勾選，且在 checkbox_to_combo 找得到對應 comboBox
          → 要求 comboBox 數量 > 0
        - 找不到 comboBox 的項目，視為「不需要數量」，直接略過
        """

        for display_name, cb in getattr(self, "BTN_MAP", {}).items():
            if cb is None:
                continue

            if not cb.isChecked():
                continue

            combo = self.checkbox_to_combo.get(cb)
            if combo is None:
                # 這個測項沒有 comboBox（例如純開關類），不檢查
                continue

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

    # 改變測試項目顯示顏色
    def color_change(self, display_name: str, status: str, tip: str = ""):
        cb = self.BTN_MAP.get(display_name)
        if not cb:
            return

        cb.setAttribute(Qt.WA_StyledBackground, True)

        colors = {
            "RUN":   ("#0066B3", "white"), # 藍色
            "PASS":  ("#16a34a", "white"), # 綠色
            "FAIL":  ("#dc2626", "white"), # 紅色
            "ERROR": ("#dc2626", "white"), # 紅色
            "SKIP":  ("#d376db", "white"), # 紫色
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
        - 更新計時器顯示
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

        # 3) 更新計時器（手動觸發，因為主線程被測試阻塞）
        if hasattr(self, 'start_time') and hasattr(self, 'timer'):
            self.start_test_time()

        # 4) 讓畫面馬上重繪，不要等測試跑完才更新
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()


    def set_all_in(self, container, checked: bool):
        """把某容器底下所有 QCheckBox 設為勾/不勾。"""
        for cb in container.findChildren(QCheckBox):
            cb.setChecked(checked)

    def select_all_items(self, include_manual: bool = False):
        # 自動測項：全勾
        self.set_all_in(self.ui.auto_test_GroupBox, True)
        self.set_all_in(self.ui.manual_test_GroupBox, True)

    def clean_all_items(self, include_manual: bool = False):
        # 自動測項：全取消
        self.set_all_in(self.ui.auto_test_GroupBox, False)
        self.set_all_in(self.ui.manual_test_GroupBox, False)

    def start_test_time(self): # 每秒更新時間 (計時器), 紀錄測試時間
        elapsed = self.start_time.secsTo(QTime.currentTime())
        t = QTime(0, 0, 0).addSecs(elapsed) # 將經過的秒數轉成 QTime（從 00:00:00 開始）
        self.ui.timeEdit_Timer.setTime(t) # 更新顯示

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
        
        # 設定 timeEdit 顯示格式為 HH:mm:ss（24小時制，避免顯示 12:00 AM）
        # self.ui.timeEdit_Timer.setDisplayFormat("HH:mm:ss")
        # self.ui.timeEdit_Timer.setTime(QTime(0, 0, 0))  # 初始化為 00:00:00
        
        self.start_time = QTime.currentTime() # 記錄測試開始時間
        self.timer.start(100)  # 每 100ms 更新一次（更即時）
        
        # 強制處理一次事件，讓 UI 先更新
        QtWidgets.QApplication.processEvents()
        
        self.all_test_items() # 開始測試

    def log_upload(self):
        self.close_test_time()
        # 不歸零計時器，讓測試完成時間保留在畫面上
        # 只有按下「開始測試」時才會歸零
        elapsed = self.start_time.secsTo(QTime.currentTime()) if hasattr(self, 'start_time') else 0
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
                    # 只收集已勾選且已啟用的 checkbox（被禁用的 checkbox 不應該被執行）
                    if cb.isChecked() and cb.isEnabled():
                        names.append(cb.text().strip())

        # 去重保順序
        seen, ordered = set(), []
        for n in names:
            if n not in seen:
                seen.add(n)
                ordered.append(n)
        return ordered
    
    # 組裝完整的 meta 字典，包含所有 JSON/log 輸出需要的欄位
    def build_complete_meta(self):
        """
        組裝完整的 meta 字典，包含所有 JSON/log 輸出需要的欄位
        統一在這裡管理所有 meta 欄位，避免在 Test_item.py 中分散提取
        """
        meta_base = self.cfg.get("mes_info_meta", {}) or {} # 這函式功能是從cfg中取得meta資訊, 如果沒有就返回空字典, meta在TestTool2.0.py中設定
        
        # 組裝完整的 meta 字典
        complete_meta = {
            # ===== 基本資訊（來自登入時的 cfg.meta）=====
            # 格式：JSON鍵名 ← 來源路徑（說明）
            # 前面是JSON輸出用的名稱, 後面是cfg.meta中的名稱
            "RUNCARD": meta_base.get("runcard", ""),             # "runcard" ← cfg.meta["runcard"]（流程卡號）, 前面是JSON輸出用的名稱, 後面是cfg.meta中的名稱
            "WORKORDER": meta_base.get("workorder", ""),         # "workorder" ← cfg.meta["workorder"]（工單號）, 前面是JSON輸出用的名稱, 後面是cfg.meta中的名稱
            "SYSTEM_SN": self.cfg.get("sn", ""),                 # "SYSTEM_SN" ← cfg["sn"]（系統序號）, 前面是JSON輸出用的名稱, 後面是cfg中的名稱
            "OPERATOR": meta_base.get("operator", ""),           # "operator" ← cfg.meta["operator"]（操作員工號）, 前面是JSON輸出用的名稱, 後面是cfg.meta中的名稱
            "MES_MODE": meta_base.get("mode", ""),               # "mes_mode" ← cfg.meta["mode"]（MES模式：RD/AETINA_MES/INNODISK_MES/OFFLINE）
            "PROCESS_NAME": meta_base.get("process_name", ""),   # "process_name" ← cfg.meta["process_name"]（站別名稱，從MES查詢取得）
            "TOOL_VERSION": meta_base.get("tool_version", ""),   # "tool_version" ← cfg.meta["tool_version"]（測試工具版本號）
            "TEST_TOOL_CONFIG": meta_base.get("test_tool_config", ""),   # "test_tool_config" ← cfg.meta["test_tool_config"]（測試工具配置檔名稱，例如：JP_R36_4_3_ORIN_AGX_AIB-MX03-A2_STD.ini）

            # ===== 系統硬體資訊（從系統檔案自動取得）=====
            "BOARD": self.cfg.get("BOARD", ""),                  # "BOARD" ← cfg["BOARD"]（板子名稱，例如：AIB-MX03-A2）
            "MODULE": self.cfg.get("MODULE", ""),                # "MODULE" ← cfg["MODULE"]（模組名稱）
            "BSP": self.cfg.get("BSP", ""),                      # "BSP" ← cfg["BSP"]（BSP版本，例如：JP_R36_4_3_ORIN_AGX_AIB-MX03-A2_STD_v1.0.0_Aetina）
            "DTS": self.cfg.get("DTS", ""),                      # "DTS" ← cfg["DTS"]（Device Tree檔案名稱）
            "CPU": self.cfg.get("cpu_name", ""),                 # "CPU" ← cfg["cpu_name"]（CPU型號，從/proc/cpuinfo取得）
            "MEMORY": self.cfg.get("mem_info", ""),              # "MEMORY" ← cfg["mem_info"]（記憶體資訊，從dmidecode取得，格式：16 GB / 16 GB）
            "PART_NUMBER": meta_base.get("part_no", ""),         # "PART_NUMBER" ← cfg.meta["part_no"]（品號，從MES查詢取得）
            "CID": meta_base.get("cid", ""),                     # "CID" ← cfg.meta["cid"]（eMMC CID，從/sys/class/mmc_host/mmc0/mmc0:0001/cid取得）
            
            # ===== 其他欄位 =====
            "header": meta_base.get("header") or self._build_header_string(meta_base),  # "header" ← cfg.meta["header"]或自動產生（標題字串，顯示在log開頭）
        }
        
        return complete_meta
    
    # 建立 header 字串（用於 log 檔, 顯示在log開頭）
    def _build_header_string(self, meta_base):
        """建立 header 字串（用於 log 檔）"""
        runcard = meta_base.get("runcard", "")
        workorder = meta_base.get("workorder", "")
        sn = self.cfg.get("sn", "")
        operator = meta_base.get("operator", "")
        mode = meta_base.get("mode", "")
        
        parts = []
        if runcard:
            parts.append(f"流程卡：{runcard}")
        if workorder:
            parts.append(f"工單：{workorder}")
        if sn:
            parts.append(f"SN: {sn}")
        if operator:
            parts.append(f"工號：{operator}")
        if mode:
            parts.append(f"模式：{mode}")
        
        return " | ".join(parts) if parts else ""
    
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

        # 組裝完整的 complete_meta 字典（統一在 GUI 層管理所有欄位）
        complete_meta = self.build_complete_meta()
        
        # MB_Test.py -> all_test_items()
        result, text, item_status, actual_result_path = run_selected_tests(
            selected_display_names,
            log_dir = self.cfg.get("log_dir"),
            sn = self.cfg.get("sn"),
            mes_info_meta = complete_meta,  # 使用完整組裝的 complete_meta for mes_info_meta 帶入 Test_item.py使用
            log_path = self.cfg.get("user_log_path"),  # 如果為 None，會在 run_selected_tests 中產生
            window = self,  # 傳入主視窗參考以更新目前測試項目顯示, 提供給Test_item.py使用
        )
        # 更新 cfg 中的 user_log_path（目前存放本輪主要輸出的 JSON 路徑），供後續 rename_log 使用
        if actual_result_path:
            self.cfg["user_log_path"] = actual_result_path
        try:
            self.ui.Information_textEdit.append(text)
        except Exception:
            print(text)

        # 變色
        for name, status in item_status.items():
            # 這裡先不放 tip；如果之後回傳 item_message，就可以塞進來
            self.color_change(name, status) # 改顏色 name是顯示名稱, status是 'PASS'/'FAIL' 等等

        # 只依據本次有勾選的項目計算 Pass/Fail
        total_tests = result.testsRun
        total_failures = len(result.failures)
        total_errors = len(result.errors)
        total_passed = total_tests - total_failures - total_errors

        summary = (f"{total_passed}/{total_tests} passed，"
                   f"fail={total_failures}，err={total_errors}")
        self.ui.Information_textEdit.append(summary)

        # 根據累積狀態（PERSISTED_STATUS）判斷整體 PASS/FAIL，而非只看本次測試結果
        # 這樣即使本次測試全部 PASS，但之前有未重測的 FAIL 項目，檔名仍會是 _FAIL
        overall_passed = all(v == "PASS" for v in PERSISTED_STATUS.values()) if PERSISTED_STATUS else False
        self.rename_log(overall_passed)

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

        # MES 出站（從 mes_info_meta 讀取 mode）
        mes_info = self.cfg.get("mes_info_meta", {}) or {}
        mode = (mes_info.get("mode") or "").strip()
        if mode in ("RD", "OFFLINE"):
            self.ui.Information_textEdit.append("【MES 出站略過】目前是 RD/OFFLINE 模式。")
            return

        # === MES 出站：用 TOML 的 expect 做 QTY，item_status 做 RESULT ===
        run_status = item_status                     # run_selected_tests 回傳的字典
        picked = selected_display_names[:]           # 本輪勾選的顯示名稱

        # 準備 TEST_LOG 其他欄位（BOARD/MODULE/...）
        # 注意：mes_info 已在上面定義
        mes_meta = {
            "BOARD":             self.cfg.get("BOARD",""),
            "MODULE":            self.cfg.get("MODULE",""),
            "BSP":               self.cfg.get("BSP",""),
            "DTS":               self.cfg.get("DTS",""),
            "WORK_ORDER":        mes_info.get("workorder",""),
            "PART_NUMBER":       mes_info.get("part_no",""),
            "CID":               mes_info.get("cid",""),
            "CPU":               self.cfg.get("cpu_name",""),
            "MEMORY":            self.cfg.get("mem_info",""),
            "TEST_TOOL_VERSION": self.cfg.get("version",""),
            "TEST_TOOL_CONFIG":  self.cfg.get("config_name",""),
        }

        # 產生完整 TEST_LOG（內含 ITEM_LIST/ QTY/ RESULT）
        testlog   = build_mes_testlog(mes_meta, picked, run_status)
        item_list = testlog["ITEM_LIST"]
        extra_log = {k: v for k, v in testlog.items() if k != "ITEM_LIST"}

        # 參數（從 mes_info_meta 讀取，這是進站時設定的）
        runcard      = (mes_info.get("runcard","") or "").strip()
        system_sn    = (self.cfg.get("sn","") or "").strip()
        employee_no  = (mes_info.get("operator","") or "").strip()
        process_name = (mes_info.get("process_name","") or "").strip()
        workorder    = (mes_info.get("workorder","") or "").strip()

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
                self.ui.Information_textEdit.append("[MES出站] 成功")
                QMessageBox.information(self, "[MES出站]", "MES 出站成功！", QMessageBox.Ok)
            else:
                self.ui.Information_textEdit.append(f"[MES][出站] 失敗：{lev.get('error') or lev.get('msg')}")
                QMessageBox.critical(self, "[MES 出站]", f"MES 出站失敗：{lev.get('error') or lev.get('msg')}", QMessageBox.Ok)

    def rename_log(self, passed: bool):
        """把 user_log_path 指向的檔案改名，結尾加 _PASS 或 _FAIL"""
        log_path = self.cfg.get("user_log_path")
        if not log_path:
            return
        
        p = pathlib.Path(log_path)

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
        
        # 處理三種檔案：.log, .json, .csv
        extensions = [".log", ".json", ".csv"]
        
        for ext in extensions:
            old_file = p.with_suffix(ext)
            new_file = new_log.with_suffix(ext)
            
            # 若目前檔名跟新檔名不同，需要改名
            if old_file != new_file:
                try:
                    # 先刪除目標檔（如果存在）
                    if new_file.exists():
                        new_file.unlink()
                except Exception:
                    pass
                
                try:
                    # 改名
                    if old_file.exists():
                        os.replace(old_file, new_file)
                except Exception:
                    pass
            
            # 清掉同 base 的其他 TAG 版本（例如舊的 _PASS 或 _FAIL）
            for old in p.parent.glob(f"{base_stem}_*{ext}"):
                if old != new_file:
                    try:
                        old.unlink()
                    except Exception:
                        pass

        # 更新 cfg（若之後還要繼續寫入同一顆）
        self.cfg["user_log_path"] = str(new_log)

    def upload_report(self):
        # 1) 取得 WO 與本機要上傳的資料夾
        wo = (getattr(self, "wo", "") or # 優先用 self.wo
            self.cfg.get("mes_info_meta", {}).get("workorder") or "").strip() # 再用 cfg
        if not wo and hasattr(self.ui, "WO_lineEdit"): # 再用 UI
            wo = (self.ui.WO_lineEdit.text() or "").strip() # 這裡不更新 self.wo

        base_dir = (self.cfg.get("log_dir") or "").strip() # 這是 log_dir
        candidate = base_dir if (base_dir and os.path.isdir(base_dir)) else wo # 以工單為主

        local_log_folder = candidate # 本機要上傳的資料夾
        # upload_log 放在程式根目錄，不會被上傳
        upload_log_name = os.path.join(PROGRAM_ROOT, f"upload_log_{wo or 'NO_WO'}.log")

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
        def upload_folder(ftp, local_path, remote_path, target_name):
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
                            log.write(f"[{target_name}] {msg}\n")
                        continue

                    with open(full_local_path, 'rb') as f:
                        ftp.storbinary(f'STOR {item}', f)
                        msg = f"上傳檔案: {item} 成功"
                        self.ui.Information_textEdit.append(msg)
                        with open(upload_log_name, "a", encoding="utf-8") as log:
                            log.write(f"[{target_name}] {msg}\n")

                elif os.path.isdir(full_local_path):
                    self.ui.Information_textEdit.append(f"上傳資料夾: {item} 開始")
                    upload_folder(ftp, full_local_path, item, target_name)

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
                upload_folder(ftp, local_log_folder, folder_name, current_target_name)
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
        self.refresh_ftp_counts(only_ext=".json") # 只數 .json


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

    def _ftp_count_pass_fail_in_dir(self, ftp, remote_dir, only_ext=".json"):
        """
        遞迴統計 remote_dir 底下檔名含 _PASS/_FAIL 的檔數（預設只數 .json）。
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

        counts["total"] = counts["pass"] + counts["fail"] # 總數 = PASS + FAIL
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

    def refresh_ftp_counts(self, only_ext=".json"):
        """
        依『WO 資料夾名』＋『radio 選擇的 FTP』遞迴統計 _PASS/_FAIL 檔數，
        並更新右下角 LCD。
        """
        self.ui.Information_textEdit.append("[DEBUG] refresh_ftp_counts() 開始執行...")
        
        # 取得工單資料夾名稱（與 upload_report 邏輯完全一致）
        wo = (getattr(self, "wo", "") or  # 優先用 self.wo
              self.cfg.get("mes_info_meta", {}).get("workorder") or "").strip()
        if not wo and hasattr(self.ui, "WO_lineEdit"):
            wo = (self.ui.WO_lineEdit.text() or "").strip()
        
        # 與 upload_report 一致：如果 log_dir 存在就用它的資料夾名稱
        base_dir = (self.cfg.get("log_dir") or "").strip()
        if base_dir and os.path.isdir(base_dir):
            folder_name = os.path.basename(os.path.normpath(base_dir))
        else:
            folder_name = wo
        
        self.ui.Information_textEdit.append(f"[DEBUG] wo='{wo}', log_dir='{base_dir}', 使用資料夾名稱='{folder_name}'")
        
        if not folder_name:
            self.ui.Information_textEdit.append("【FTP 統計略過】沒有工單資料夾名稱")
            return
        
        # 後續統計使用 folder_name
        wo = folder_name

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
        self.ui.Information_textEdit.append(f"[DEBUG] 統計結果：PASS={counts['pass']}，FAIL={counts['fail']}")
        self.ui.Information_textEdit.append(f"[DEBUG] 準備更新 LCD...")
        
        # 檢查 LCD 元件是否存在
        has_pass_lcd = hasattr(self.ui, "pass_lcdNumber")
        has_fail_lcd = hasattr(self.ui, "fail_lcdNumber")
        self.ui.Information_textEdit.append(f"[DEBUG] pass_lcdNumber 存在: {has_pass_lcd}, fail_lcdNumber 存在: {has_fail_lcd}")
        
        self._set_pass_fail_counts(counts["pass"], counts["fail"])
        self.ui.Information_textEdit.append(
            f"[{tgt['name']}] FTP 統計（{wo}）：PASS={counts['pass']}，FAIL={counts['fail']}，TOTAL={counts['total']}"
        )
    # ====== /PASS/FAIL 顯示與 FTP 統計 ======



def mbtest_run(cfg=None):
    win = MBTestWindow(cfg)
    win.show()          # 一定要 show
    return win          # 一定要回傳，避免被回收
        
