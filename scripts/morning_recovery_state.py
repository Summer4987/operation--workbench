"""Same-day checkpoints. Runtime files are local to the production host."""
import json
import os
from pathlib import Path

RESUMABLE_STEPS = {
    "双平台评价页及门店评分采集", "直营双平台客服消息采集",
    "直营美团日报下载", "门店日报采集并发布", "推广余额总巡检",
    "饿了么午餐预算真实提交", "美团午餐预算真实提交",
    "饿了么晚餐预算真实提交", "美团晚餐预算真实提交",
}


class RecoveryState:
    def __init__(self, path, *, day, period, mode, started, resume=False):
        self.path = Path(path)
        self.data = {"day": day, "period": period, "mode": mode, "started": started, "completed": []}
        if resume and self.path.exists():
            previous = json.loads(self.path.read_text())
            if all(previous.get(k) == self.data[k] for k in ("day", "period", "mode")):
                self.data = previous
        self.save()

    def completed(self, name):
        return name in RESUMABLE_STEPS and name in self.data["completed"]

    def record(self, name, success):
        if name not in RESUMABLE_STEPS:
            return
        steps = set(self.data["completed"])
        (steps.add if success else steps.discard)(name)
        self.data["completed"] = sorted(steps)
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False))
        os.replace(tmp, self.path)
