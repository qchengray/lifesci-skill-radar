# 采集与排名 / Methodology

- **观测**：GitHub REST 公共仓库元数据。每条成功记录含 UTC 观测时间、稳定仓库 ID、星数、最后推送时间、归档状态及 GitHub 识别的 SPDX 标识。目录不存代码、私有仓库内容或用户信息。
- **日界线**：北京时间 UTC+08:00，日榜按采集日期记录。同日重复运行保留已成功的观测，只补失败项与新增来源。任务整体失败不覆盖原有榜单。
- **排行**：按星数递减；并列采用竞赛排名（1、1、3）。缺测不参与排名。排名变化只在相邻两天所有同名来源均成功且仓库可比时计算。
- **日与周差**：只对比恰好 1 或 7 个北京时间自然日之前的同一仓库 ID；不能比较就显示「—」。取消星标导致的负数是真实净变化。
- **周报／月报**：有期前一日与期末快照时按完整时间端点统计，否则以观测端点给出局部变化。显示区间快照覆盖；没有两次可比观测不报增长。每次成功刷新都重算上一周和上个月，可在首日排程延迟后补发两种周期报。
- **缺口政策**：不假装历史快照可回填。单仓库缺测保留状态；整体失败让 Actions 显示失败。GitHub 可能延迟启动定时任务；公开仓库无活动 60 天后可能被暂停，见 [GitHub 定时事件文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
- **来源版本**：目录是人工审查的 Git 跟踪 JSON。记录源项目仓库，避免重复统计 fork、镜像或迁移前仓库；支持/可视化扩展不归为 Agent Skill。

## 维护

本地仅渲染：`python3 -m radar.update --render-only`。运行测试：`python3 -m unittest discover -s tests -v`。采集：`python3 -m radar.update`，可选的 `GH_TOKEN` 用于 GitHub 速率配额。

GitHub Actions → **Refresh LifeSci Skill Radar** → **Run workflow** 可手动启动。只允许默认分支发布快照。常规情况下不需要添加私有密钥；需要启用 Actions，并允许工作流的仓库令牌提交到默认分支。若启用了禁止机器人直推的规则，先检查该规则，再计划替代发布路径。
