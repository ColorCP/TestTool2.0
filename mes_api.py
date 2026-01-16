# mes_api.py — 純 API：不碰 UI、不寫測試 log；只寫 mes.log，回傳 dict 結果
import requests
import json
import time
from datetime import datetime

class MESClient:
    # 端點
    URL_QUERY_AETINA   = "https://scm.aetina.com/API/MES/Runcard"
    URL_QUERY_INNODISK = "http://mfg_api.innodisk.com/MFG_WebAPI/api/MesCheck"
    URL_CHECK_AETINA   = "https://scm.aetina.com/API/MES/Check"
    URL_LOG_INNODISK   = "http://mfg_api.innodisk.com/Inno_API/api/MES_Sub/AT_TEST_LOG"

    def __init__(self, mode="AETINA_MES", timeout=10, retries=4, retry_sleep=1.0, mes_log_path="mes.log"):
        self.mode = mode
        self.timeout = timeout
        self.retries = retries
        self.retry_sleep = retry_sleep
        self.mes_log_path = mes_log_path
        self.last_error = ""

    # --------- mes.log ----------
    def _write_mes_log(self, title, content):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.mes_log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts} - {title}\n")
                if isinstance(content, (dict, list)):
                    f.write(json.dumps(content, indent=2, ensure_ascii=False) + "\n")
                else:
                    f.write(str(content) + "\n")
        except Exception:
            pass  # 失敗就略過，不讓呼叫端掛掉

    # --------- HTTP ----------
    def _post(self, url, payload):
        headers = {"Content-Type": "application/json"}
        self.last_error = ""

        # 這裡新增：記錄即將送出的 JSON 內容
        # self._write_mes_log("[POST JSON]", {"url": url, "payload": payload}) # 記錄送出內容, debug 用

        for i in range(self.retries):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                return r.json()
            except Exception as e:
                self.last_error = str(e)
                self._write_mes_log("[HTTP 失敗/重試]", {"url": url, "error": str(e), "retry": i})
                time.sleep(self.retry_sleep)
        raise RuntimeError(self.last_error or "HTTP post failed")

    # --------- API：查流程卡 ----------
    def query_api(self, runcard):
        is_aetina = (runcard or "").strip().upper().startswith(("A", "S", "P"))
        url = self.URL_QUERY_AETINA if is_aetina else self.URL_QUERY_INNODISK
        payload = {"CHECK_TYPE": "RUNCARD", "CHECK_VALUE": runcard}
        try:
            data = self._post(url, payload)
            self._write_mes_log("[MES查詢結果]", data)

            # 解析摘要
            result = {}
            if isinstance(data, dict):
                arr = data.get("RESULT") or [{}]
                if isinstance(arr, list) and arr:
                    result = arr[0]
            wo  = result.get("WORKORDER", "") or result.get("WORK_ORDER", "")
            pn  = result.get("PART_NUMBER", "")
            prc = result.get("PROCESS_NAME", "")
            qty = result.get("RUNCARD_QTY", "")
            st  = result.get("INPUT_STATUS", "")
            msg = data.get("MSG", "") if isinstance(data, dict) else ""

            ok = (msg == "")
            return {
                "ok": ok,
                "wo": wo,
                "pn": pn,
                "process_name": prc,
                "qty": qty,
                "status": st,
                "msg": msg,
                "raw": data,
                "error": ""
            }
        except Exception as e:
            self._write_mes_log("[MES查詢例外]", {"error": str(e)})
            return {"ok": False, "error": str(e)}

    # --------- API：進站 ----------
    def enter_api(self, runcard, sn, process_name, employee_no):
        is_aetina = (runcard or "").strip().upper().startswith(("A", "S", "P"))
        url = self.URL_CHECK_AETINA if is_aetina else self.URL_LOG_INNODISK
        payload = [{
            "IO_TYPE": "I",
            "RUNCARD": runcard,
            "SYSTEM_SN": sn,
            "PROCESS_NAME": process_name,
            "EMPLOYEE_NO": employee_no,
            "INPUT_NOCHECK": "Y"
        }]
        try:
            data = self._post(url, payload)
            self._write_mes_log("[MES進站結果]", data)

            res = ""
            if isinstance(data, list) and data:
                res = data[0].get("RESULT", "")
            elif isinstance(data, dict):
                res = data.get("RESULT", "")

            return {"ok": (res == "OK"), "result": res, "raw": data, "error": ""}
        except Exception as e:
            self._write_mes_log("[MES進站例外]", {"error": str(e)})
            return {"ok": False, "result": "", "raw": None, "error": str(e)}

    # --------- API：離站 ----------
    def leave_api(self, runcard, sn, operator, wo, process_name, item_list=None, extra_log=None):
        if self.mode not in ["AETINA_MES", "INNODISK_MES"]:
            self._write_mes_log("[離站略過]", {"mode": self.mode})
            return {"ok": True, "result": "SKIPPED", "raw": None, "error": ""}

        url = self.URL_CHECK_AETINA if self.mode == "AETINA_MES" else self.URL_LOG_INNODISK
        now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        test_log = {
            "BOARD": "", "MODULE": "", "BSP": "", "DTS": "",
            "WORK_ORDER": wo, "PART_NUMBER": "",
            "CID": "", "CPU": "", "MEMORY": "",
            "TEST_TOOL_VERSION": "v2.0",
            "TEST_TOOL_CONFIG": "",
            "DATE": now, "INPUTDATE": now,
            "ITEM_LIST": item_list or []
        }
        if extra_log:
            try:
                test_log.update(extra_log)
            except Exception:
                pass

        payload = [{
            "IO_TYPE": "O",
            "RUNCARD": runcard,
            "SYSTEM_SN": sn,
            "PROCESS_NAME": process_name,
            "EMPLOYEE_NO": operator,
            "INPUT_NOCHECK": "N",
            "TEST_LOG": test_log
        }]
        try:
            data = self._post(url, payload)
            self._write_mes_log("[離站結果]", data)
            return {"ok": True, "result": "OK", "raw": data, "error": ""}
        except Exception as e:
            self._write_mes_log("[離站例外]", {"error": str(e)})
            return {"ok": False, "result": "", "raw": None, "error": str(e)}
