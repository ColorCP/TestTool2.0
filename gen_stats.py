import os
import matplotlib.pyplot as plt
import numpy as np

# 改成你的路徑
LOG_ROOT = "/home/chris/My_Code/TestTool2.0/RD_TEST"

# 中文字體設定
plt.rcParams['font.family'] = 'Noto Sans CJK TC'
plt.rcParams['axes.unicode_minus'] = False  # 讓負號正常顯示


def judge_result_from_name(filename: str):
    """
    從檔名判斷 PASS / FAIL
    例如：RD_20250930_140149_PASS.log / RD_20250930_140149_FAIL.log
    """
    lower = filename.lower()
    name, ext = os.path.splitext(lower)

    if name.endswith("_pass"):
        return "pass"
    if name.endswith("_fail"):
        return "fail"
    return None


def collect_stats():
    stats = {}

    root_name = os.path.basename(LOG_ROOT.rstrip("/"))

    # 先看 LOG_ROOT 底下有沒有子資料夾
    entries = list(os.scandir(LOG_ROOT))
    has_subdirs = any(e.is_dir() for e in entries)

    if has_subdirs:
        # 情境 1：每個子資料夾當一個工單
        for e in entries:
            if not e.is_dir():
                continue
            workorder = e.name
            for fname in os.listdir(e.path):
                if not fname.endswith(".log"):
                    continue
                result = judge_result_from_name(fname)
                if not result:
                    continue
                stats.setdefault(workorder, {"pass": 0, "fail": 0})
                stats[workorder][result] += 1
    else:
        # 情境 2：所有 .log 直接放在 LOG_ROOT
        workorder = root_name  # 例如 "RD_TEST"
        for fname in os.listdir(LOG_ROOT):
            if not fname.endswith(".log"):
                continue
            result = judge_result_from_name(fname)
            if not result:
                continue
            stats.setdefault(workorder, {"pass": 0, "fail": 0})
            stats[workorder][result] += 1

    return stats


def plot_pass_fail(stats):
    if not stats:
        print("沒有任何統計資料可以畫 PASS/FAIL 圖。")
        return

    workorders = sorted(stats.keys())
    pass_counts = [stats[wo]["pass"] for wo in workorders]
    fail_counts = [stats[wo]["fail"] for wo in workorders]

    x = np.arange(len(workorders))
    width = 0.35

    plt.figure(figsize=(10, 5))
    plt.bar(x - width / 2, pass_counts, width, label="PASS")
    plt.bar(x + width / 2, fail_counts, width, label="FAIL")
    plt.xticks(x, workorders, rotation=45, ha="right")
    plt.ylabel("數量")
    plt.title("各工單 PASS / FAIL 數量")
    plt.legend()
    plt.tight_layout()
    plt.show()


def plot_yield(stats):
    if not stats:
        print("沒有任何統計資料可以畫良率圖。")
        return

    workorders = sorted(stats.keys())
    yields = []

    for wo in workorders:
        p = stats[wo]["pass"]
        f = stats[wo]["fail"]
        total = p + f
        rate = p / total * 100 if total else 0
        yields.append(rate)

    x = np.arange(len(workorders))

    plt.figure(figsize=(10, 4))
    plt.plot(x, yields, marker="o")
    plt.xticks(x, workorders, rotation=45, ha="right")
    plt.ylabel("良率 (%)")
    plt.title("各工單良率")
    plt.ylim(0, 105)
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    stats = collect_stats()

    for wo, d in stats.items():
        total = d["pass"] + d["fail"]
        rate = d["pass"] / total * 100 if total else 0
        print(f"{wo}: PASS={d['pass']}, FAIL={d['fail']}, 良率={rate:.1f}%")

    plot_pass_fail(stats)
    plot_yield(stats)
