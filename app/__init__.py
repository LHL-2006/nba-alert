"""NBA 关注球员实时提醒面板。

架构：
  数据层  nba_api(主) / ESPN(降级)  ->  逐回合事件
  视觉层  直播流抓帧 -> RapidOCR -> 球衣号码/姓名 -> 在场状态
  规则层  关注球员匹配 / 去重 / 冷却 -> Alert
  服务层  FastAPI + WebSocket -> 实时面板 + 推送适配器
"""
__version__ = "1.0.0"
