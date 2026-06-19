# 镜头导演 Shot Director

根据项目锁、角色锁、场景锁和当前镜头动作自动生成完整提示词、负面词、稳定镜头种子和连续性镜头包。

从第二镜开始，把上一镜的 `shot_manifest` 连接到当前镜头的 `previous_shot`。

只有列入 `allowed_changes` 的状态才能改变。
