from astrbot.api import logger
import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
import re
import time

@register("auto_at_plugin", "TEOFTU", "将LLM回复中的@文本转换为真正的@消息", "1.0.0")
class AutoAtPlugin(Star):

    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化群成员缓存 {group_id: {'members': [], 'last_updated': timestamp}}
        self.group_member_cache = {}
        # 缓存过期时间（秒）
        self.cache_expiry = 3000  # 50分钟
        logger.info("AutoAtPlugin 初始化完成")

    @filter.on_decorating_result()
    async def on_decorating_result_hook(self, event: AstrMessageEvent):
        """
        在消息装饰阶段处理@提及
        """
        result = event.get_result()
        if not result or not hasattr(result, 'chain'):
            return
        
        # 只处理群消息
        group_id = event.get_group_id()
        if not group_id:
            return
        
        # 检查消息链中是否包含@文本
        original_text = ''.join([c.text for c in result.chain if hasattr(c, 'text')])
        
        # 定义匹配@用户名的正则表达式模式
        pattern = r'@(\S+)|艾特一下?(\S+)'
        matches = list(re.finditer(pattern, original_text))
        
        if not matches:
            return
        
        # 确保我们有最新的群成员信息
        await self._ensure_group_members(event, group_id)
        
        # 创建一个新的消息链
        new_chain = []
        last_end = 0
        found_at = False
        
        for match in matches:
            # 添加匹配点之前的文本
            text_before_match = original_text[last_end:match.start()]
            if text_before_match:
                new_chain.append(Comp.Plain(text_before_match))
            
            # 处理匹配到的用户名
            username = match.group(1) if match.group(1) else match.group(2)
            
            # 从群成员缓存中查找用户ID
            user_id = self._find_user_in_group_members(group_id, username)
            
            # 如果找到了user_id，就添加一个At组件
            if user_id:
                new_chain.append(Comp.At(qq=user_id))
                found_at = True
                logger.info(f"成功将@{username}转换为At组件，用户ID: {user_id}")
            else:
                # 没找到用户，保留原始文本
                new_chain.append(Comp.Plain(match.group(0)))
                logger.warning(f"未找到用户{username}的ID，保留原始文本")
            
            last_end = match.end()
        
        # 添加最后一段文本
        text_after_last_match = original_text[last_end:]
        if text_after_last_match:
            new_chain.append(Comp.Plain(text_after_last_match))
        
        # 只有在成功找到至少一个用户ID时才修改结果
        if found_at:
            result.chain = new_chain
            logger.info(f"已将@文本转换为At组件: {original_text} -> {[str(c) for c in new_chain]}")

    async def _ensure_group_members(self, event, group_id):
        """确保我们有最新的群成员信息"""
        current_time = time.time()
        
        # 检查缓存是否存在且未过期
        if (group_id in self.group_member_cache and 
            current_time - self.group_member_cache[group_id]['last_updated'] < self.cache_expiry):
            return
        
        # 缓存不存在或已过期，获取新的群成员列表
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            if isinstance(event, AiocqhttpMessageEvent):
                client = event.bot
                # 调用OneBot API获取群成员列表
                ret = await client.api.call_action('get_group_member_list', group_id=group_id)
                
                # 根据日志，API直接返回成员列表，而不是包含'data'字段的字典
                if ret and isinstance(ret, list) and len(ret) > 0:
                    # 更新缓存
                    self.group_member_cache[group_id] = {
                        'members': ret,
                        'last_updated': current_time
                    }
                    logger.info(f"已更新群 {group_id} 的成员缓存，共 {len(ret)} 名成员")
                elif ret and isinstance(ret, dict) and 'data' in ret:
                    # 如果API返回包含'data'字段的字典
                    self.group_member_cache[group_id] = {
                        'members': ret['data'],
                        'last_updated': current_time
                    }
                    logger.info(f"已更新群 {group_id} 的成员缓存，共 {len(ret['data'])} 名成员")
                else:
                    logger.error(f"获取群 {group_id} 成员列表失败: API返回格式不正确: {ret}")
        except Exception as e:
            logger.error(f"获取群 {group_id} 成员列表失败: {e}")

    def _find_user_in_group_members(self, group_id, username):
        """从群成员缓存中查找用户ID"""
        if group_id not in self.group_member_cache:
            logger.warning(f"群 {group_id} 的成员缓存不存在")
            return None
        
        members = self.group_member_cache[group_id]['members']
        username_clean = username.strip()
        
        logger.debug(f"在群 {group_id} 中查找用户: {username_clean}")
        logger.debug(f"群成员列表: {[{'nickname': m.get('nickname'), 'card': m.get('card'), 'user_id': m.get('user_id
