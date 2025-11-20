import os, sys
from PyQt5.QtWidgets import QApplication, QMessageBox

def ask_yes_no(title: str, text: str, default_no=False):
    """
    通用確認對話框：
      - 若在 GUI (PyQt5) 環境 → 使用 QMessageBox.question()
      - 若在 CLI / unittest → 使用環境變數 AUTO_CONFIRM 或命令列互動
    """
    try:
        app = QApplication.instance()  # 取得目前是否有 PyQt Application 實例
        if app is not None: # 有 GUI 環境
            parent = app.activeWindow() or None # 找一個父視窗（沒有就 None）
            ret = QMessageBox.question(  # 開一個「是/否」對話框
                parent, title, text, # 標題與內容
                QMessageBox.Yes | QMessageBox.No, # 按鈕選項
                QMessageBox.No if default_no else QMessageBox.Yes # 預設按鈕
            )
            return ret == QMessageBox.Yes # 按 YES 就回傳 True
    except Exception:
        pass

    # --- 無 GUI 環境 ---
    val = os.getenv("AUTO_CONFIRM", "") # 讀取環境變數, AUTO_CONFIRM是自動確認的意思, 可設定為 1, y, yes, true, pass, ok 等表示肯定的值
    if val: # 有設定環境變數則自動回應
        return val.lower() in ("1","y","yes","true","pass","ok") # 判斷是否為肯定回應

    if sys.stdin and sys.stdin.isatty(): # 在互動式終端中
        ans = input(f"{title}: {text} [Y/N] ").strip().lower() # 提示使用者輸入
        return ans in ("y","yes") # 判斷是否為肯定回應, 互動式終端

    return not default_no # 預設回應


def ask_info(title: str, text: str):
    """
    通用提示訊息框：
      - GUI 模式顯示 QMessageBox.information()
      - CLI 模式印在終端上
    """
    try:
        app = QApplication.instance() # 取得現有的 QApplication 實例
        if app is not None: # 有 GUI 環境
            parent = app.activeWindow() or None # 取得目前活動視窗作為父視窗
            QMessageBox.information(parent, title, text) # CLI 模式下顯示訊息框
            return
    except Exception:
        pass

    print(f"[INFO] {title}: {text}") # CLI 模式下印出訊息
