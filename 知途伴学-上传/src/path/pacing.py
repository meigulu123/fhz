"""学习节奏适配：正确率与卡壳次数 → 节奏系数与每批知识点数"""
MAX_PACE, MIN_PACE = 1.6, 0.4


def pace_params(accuracy: float, stuck_count: int = 0) -> dict:
    """pace = clip(0.5 + 0.8·(acc−0.70) − 0.10·stuck, 0.4, 1.6)；batch = round(3·pace)

    accuracy 为近 10 题正确率（无数据时取 0.7 中性值）。
    """
    acc = 0.7 if accuracy is None else max(0.0, min(1.0, accuracy))
    pace = max(MIN_PACE, min(MAX_PACE, 0.5 + 0.8 * (acc - 0.70) - 0.10 * stuck_count))
    return {"pace": round(pace, 2), "batch": max(1, round(3 * pace))}
