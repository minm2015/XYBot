#  Copyright (c) 2024. Henry Yang
#
#  This program is licensed under the GNU General Public License v3.0.

import asyncio
import os
import re

import yaml
import requests
from loguru import logger
from wcferry import client, wxmsg

from utils.database import BotDatabase
from utils.plugin_manager import plugin_manager
from wcferry_helper import XYBotWxMsg, async_download_image
from bs4 import BeautifulSoup
import random

def fetch_binance_announcements():
    # 币安中文公告页面的URL
    url = "https://www.binance.com/zh-CN/support/announcement/new-cryptocurrency-listing?c=48&navId=48"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    # 发送HTTP请求获取页面内容
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        # 根据页面结构提取公告标题及链接
        announcements = soup.find_all("a", class_="text-PrimaryText")  # 注意 class 可能需要根据实际页面调整
        random_number = random.randint(0, 100)
        if len(announcements) >= 3:
            third_announcement = announcements[2]
            title = third_announcement.text.strip()
            link = "https://www.binance.com" + third_announcement["href"]
            return {"title": f"{title}{random_number}", "link": link}
    else:
        print(f"无法访问币安公告页面，状态码: {response.status_code}")


async def fetch_announcements(exchange):
    """
    模拟异步获取公告数据
    :param exchange: 交易所名称
    :return: 公告列表
    """
    # 假设有各交易所的抓取逻辑
    if exchange == "binance":
        announcement = fetch_binance_announcements()
        return announcement
    return 


async def monitor_announcements(exchange, bot: client.Wcf, recv: XYBotWxMsg):
    """
    循环检查交易所公告并推送新公告到群
    """
    print(f"开始监控 {exchange} 的公告...")
    checked_announcements = set()  # 已检测过的公告
    while True:
        try:
            # 获取交易所最新公告
            new_announcements = await fetch_announcements(exchange)
            # 筛选出新公告
            for announcement in new_announcements:
                if announcement['title'] not in checked_announcements:
                    # 推送到群组
                    bot.send_text(f"【{exchange} 上新公告】\n{announcement['title']}\n{announcement['link']}", recv.roomid)
                    checked_announcements.add(announcement['title'])
            # 每隔一段时间检查
            await asyncio.sleep(3)  # 每隔 3 s检查一次
        except Exception as e:
            print(f"公告监控出错：{e}")
            break

def isValidSubscriptionCommand(command: str) -> bool:
    """
    验证订阅上新命令格式是否正确
    :param command: 输入的命令字符串
    :return: 是否符合格式
    """
    pattern = r"^订阅上新@(binance|okex|htx|coinbase)$"
    return bool(re.match(pattern, command))

class XYBot:
    def __init__(self, bot: client.Wcf):
        with open("main_config.yml", "r", encoding="utf-8") as f:  # 读取设置
            main_config = yaml.safe_load(f.read())
        self.command_prefix = main_config["command_prefix"]  # 命令前缀
        logger.debug(f"指令前缀为(如果是空则不会显示): {self.command_prefix}")

        self.keywords = plugin_manager.get_keywords()

        self.ignorance_mode = main_config['mode']
        self.ignorance_blacklist = main_config['blacklist']
        self.ignorance_whitelist = main_config['whitelist']

        self.image_save_path = os.path.abspath("resources/cache")
        self.voice_save_path = os.path.abspath("resources/cache")
        logger.debug(f"语音保存路径: {self.voice_save_path}")
        logger.debug(f"图片保存路径: {self.image_save_path}")

        self.self_wxid = bot.get_self_wxid()

    async def message_handler(self, bot: client.Wcf, recv: wxmsg.WxMsg) -> None:
        recv = XYBotWxMsg(recv)

        # 尝试设置用户的昵称
        db = BotDatabase()

        nickname_latest = False
        if not db.get_nickname(recv.sender):  # 如果数据库中没有这个用户的昵称，需要先获取昵称再运行插件
            await self.attempt_set_nickname(bot, recv, db)
            nickname_latest = True

        message_type = recv.type
        if message_type == 1:  # 是文本消息
            await self.text_message_handler(bot, recv)
        elif message_type == 3:  # 是图片消息
            await self.image_message_handler(bot, recv)
        elif message_type == 34:  # 语音消息
            await self.voice_message_handler(bot, recv)
        elif message_type == 10000:
            await self.system_message_handler(bot, recv)
        elif message_type == 47:  # 表情消息
            await self.emoji_message_handler(recv)
        else:  # 其他消息，type不存在或者还未知干啥用的
            logger.info(f"[其他消息] {recv}")

        if not nickname_latest:
            await self.attempt_set_nickname(bot, recv, db)

    async def attempt_set_nickname(self, bot: client.Wcf, recv: XYBotWxMsg, db: BotDatabase) -> None:
        if recv.from_group():  # 如果是群聊
            nickname = bot.get_alias_in_chatroom(recv.sender, recv.roomid)
            db.set_nickname(recv.sender, nickname)
        else:  # 如果是私聊
            flag = True
            for user in bot.contacts:
                if user["wxid"] == recv.sender:
                    db.set_nickname(recv.sender, user["name"])
                    flag = False
                    break

            if flag:  # 如果没有找到，重新获取一次最新的联系人列表
                for user in bot.get_contacts():
                    if user["wxid"] == recv.sender:
                        db.set_nickname(recv.sender, user["name"])
                        break

    async def text_message_handler(self, bot: client.Wcf, recv: XYBotWxMsg) -> None:
        logger.info(f"[收到文本消息]:{recv}")
        ## 这里增加自己新增的定制监控逻辑
        if isValidSubscriptionCommand(recv.content):
            out_message ="订阅上新成功"
            bot.send_text(out_message, recv.roomid)
            return
        #### ===============================================
        if not self.ignorance_check(recv):  # 屏蔽检查
            return

        # @机器人处理
        if self.self_wxid in recv.ats:  # 机器人被@，调用所有mention插件
            for plugin in plugin_manager.plugins["mention"].values():
                await asyncio.create_task(plugin.run(bot, recv))
            return

        # 指令处理
        if recv.content.startswith(self.command_prefix) or self.command_prefix == "":
            if self.command_prefix != "":  # 特殊处理，万一用户想要使用空前缀
                recv.content = recv.content[1:]  # 去除命令前缀

            recv_keyword = recv.content.split(" |\u2005")[0]  # 获取命令关键词
            for keyword in plugin_manager.get_keywords().keys():  # 遍历所有关键词
                if re.match(keyword, recv_keyword):  # 如果正则匹配到了，执行插件run函数
                    plugin_func = plugin_manager.keywords[keyword]
                    await asyncio.create_task(plugin_manager.plugins["command"][plugin_func].run(bot, recv))
                    return

            if recv.from_group() and self.command_prefix != "":  # 不是指令但在群里 且设置了指令前缀
                out_message = "该指令不存在！⚠️"
                logger.info(f'[发送信息]{out_message}| [发送到] {recv.roomid}')
                bot.send_text(out_message, recv.roomid)
                return  # 执行完后直接返回

        # 普通消息处理
        for plugin in plugin_manager.plugins["text"].values():
            await asyncio.create_task(plugin.run(bot, recv))

    async def image_message_handler(self, bot: client.Wcf, recv: XYBotWxMsg) -> None:
        logger.info(f"[收到图片消息]{recv}")

        if not self.ignorance_check(recv):  # 屏蔽检查
            return

        # 如果是图片消息，recv字典中会有一个image键值对，值为图片的绝对路径。
        path = await async_download_image(bot, recv.id, recv.extra, self.image_save_path)
        recv.image = os.path.abspath(path)  # 确保图片为绝对路径

        # image插件调用
        for plugin in plugin_manager.plugins["image"].values():
            await asyncio.create_task(plugin.run(bot, recv))

    async def voice_message_handler(self, bot: client.Wcf, recv: XYBotWxMsg) -> None:
        logger.info(f"[收到语音消息]{recv}")

        if not self.ignorance_check(recv):  # 屏蔽检查
            return

        path = await async_download_image(bot, recv.id, recv.extra, self.voice_save_path)  # 下载语音
        recv.voice = os.path.abspath(path)  # 确保语音为绝对路径

        # voice插件调用
        for plugin in plugin_manager.plugins["voice"].values():
            await asyncio.create_task(plugin.run(bot, recv))

    async def system_message_handler(self, bot: client.Wcf, recv: XYBotWxMsg) -> None:
        logger.info(f"[收到系统消息]{recv}")

        if not self.ignorance_check(recv):  # 屏蔽检查
            return

        # 开始检查有没有群成员加入
        if recv.from_group():
            content = recv.content
            result = re.findall(r'"(.*?)"加入了群聊', content)
            result = result[0] if result else None
            if result:
                recv.join_group = result
                for plugin in plugin_manager.plugins["join_group"].values():
                    await asyncio.create_task(plugin.run(bot, recv))
                return

    async def emoji_message_handler(self, recv) -> None:
        logger.info(f"[收到表情消息]{recv}")

    def ignorance_check(self, recv: XYBotWxMsg) -> bool:
        if self.ignorance_mode == 'none':  # 如果不设置屏蔽，则直接返回通过
            return True

        elif self.ignorance_mode == 'blacklist':  # 如果设置了黑名单
            if (recv.roomid not in self.ignorance_blacklist) and (recv.sender not in self.ignorance_blacklist):
                return True
            else:
                return False

        elif self.ignorance_mode == 'whitelist':  # 白名单
            if (recv.roomid in self.ignorance_whitelist) or (recv.sender in self.ignorance_whitelist):
                return True
            else:
                return False

        else:
            logger.error("未知的屏蔽模式！请检查白名单/黑名单设置！")

    
