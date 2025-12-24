#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new Env('WPS签到抽奖');
cron: 1 1 1 1 1
"""

"""
WPS自动签到和抽奖脚本

该脚本用于自动执行WPS的签到和抽奖任务，包括：
- 读取账号配置信息
- 获取RSA加密公钥
- 执行签到操作
- 执行抽奖操作
- 推送执行结果

Author: Assistant
Date: 2025-12-01
Updated: 2025-12-18
"""

import json
import logging
import sys
from typing import List, Dict, Any
from pathlib import Path

from api import WPSAPI

# 获取项目根目录
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# 导入需要的模块
from notification import send_notification, NotificationSound


class WPSTasks:
    """WPS签到和抽奖任务自动化执行类"""

    def __init__(self, config_path: str = None):
        """
        初始化任务执行器

        Args:
            config_path (str): 配置文件的完整路径，如果为None则使用项目根目录下的config/token.json
        """
        # 设置配置文件路径
        if config_path is None:
            self.config_path = project_root / "config" / "token.json"
        else:
            self.config_path = Path(config_path)

        self.accounts: List[Dict[str, Any]] = []
        self.logger = self._setup_logger()
        self._init_accounts()
        self.account_results: List[Dict[str, Any]] = []

    def _setup_logger(self) -> logging.Logger:
        """
        设置日志记录器

        Returns:
            logging.Logger: 配置好的日志记录器
        """
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 设置日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)

        # 避免重复添加处理器
        if not logger.handlers:
            logger.addHandler(console_handler)

        return logger

    def _init_accounts(self):
        """从配置文件中读取账号信息"""
        if not self.config_path.exists():
            self.logger.error(f"配置文件不存在: {self.config_path}")
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                # 从统一配置文件的 wps 节点读取
                wps_config = config_data.get('wps', {})
                self.accounts = wps_config.get('accounts', [])

            if not self.accounts:
                self.logger.warning("配置文件中没有找到 wps 账号信息")
            else:
                self.logger.info(f"成功加载 {len(self.accounts)} 个账号配置")

        except json.JSONDecodeError as e:
            self.logger.error(f"配置文件JSON解析失败: {e}")
            raise
        except Exception as e:
            self.logger.error(f"读取配置文件失败: {e}")
            raise

    def process_account(self, account_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理单个账号的签到和抽奖任务

        Args:
            account_info (Dict[str, Any]): 账号信息字典

        Returns:
            Dict[str, Any]: 处理结果
        """
        account_name = account_info.get('account_name', '未命名账号')
        self.logger.info(f"\n{'=' * 60}")
        self.logger.info(f"开始处理账号: {account_name}")
        self.logger.info(f"{'=' * 60}")

        result = {
            'account_name': account_name,
            'success': False,
            'message': '',
            'sign_info': {},
            'sign_rewards': [],
            'lottery_info': {},
            'user_info': {}
        }

        try:
            # 获取账号配置
            user_id = account_info.get('user_id')
            cookies = account_info.get('cookies', '')
            user_agent = account_info.get('user_agent')

            # 检查必需参数
            if not user_id:
                error_msg = "账号配置中缺少user_id，跳过签到"
                self.logger.warning(f"⚠️ {account_name}: {error_msg}")
                result['message'] = error_msg
                return result

            if not cookies:
                error_msg = "账号配置中缺少cookies"
                self.logger.error(f"❌ {error_msg}")
                result['message'] = error_msg
                return result

            # 创建API实例
            api = WPSAPI(cookies=cookies, user_agent=user_agent)

            # 执行签到（通过签到接口判断token是否过期）
            self.logger.info(f"\n{'=' * 60}")
            self.logger.info(f"{account_name} - 执行签到")
            self.logger.info(f"{'=' * 60}")

            sign_result = api.sign_in(user_id=user_id)

            if sign_result['success']:
                result['success'] = True
                result['sign_info'] = sign_result.get('data', {}) or {}

                # 检查是否是今日已签到
                if sign_result.get('already_signed'):
                    result['message'] = '今日已签到'
                    self.logger.info(f"✅ {account_name} 今日已签到")
                else:
                    result['message'] = '签到成功'
                    self.logger.info(f"✅ {account_name} 签到成功")

                    # 只有在签到成功（非已签到）时才提取签到奖励
                    if result['sign_info']:
                        rewards = result['sign_info'].get('rewards', [])
                        reward_names = [reward.get('reward_name', '') for reward in rewards if reward.get('reward_name')]
                        result['sign_rewards'] = reward_names

                        # 打印签到奖励
                        if reward_names:
                            self.logger.info(f"🎁 签到奖励:")
                            for idx, reward_name in enumerate(reward_names, 1):
                                self.logger.info(f"   {idx}. {reward_name}")

                # 打印完整签到详情(可选,已注释)
                # self.logger.info(f"签到详情: {json.dumps(result['sign_info'], ensure_ascii=False, indent=2)}")
            else:
                error_msg = sign_result.get('error', '签到失败')
                error_type = sign_result.get('error_type', '')

                # 检查是否是token过期
                if error_type == 'token_expired':
                    result['message'] = 'Token已过期，请重新登录'
                    self.logger.error(f"❌ {account_name} Token已过期，请重新登录")
                    # Token过期时跳过后续所有任务
                    return result
                else:
                    result['message'] = error_msg
                    self.logger.error(f"❌ {account_name} 签到失败: {error_msg}")
                    # 签到失败也跳过后续任务
                    return result

            # 获取签到后的用户信息（包含最新的抽奖次数）
            self.logger.info(f"\n{'=' * 60}")
            self.logger.info(f"{account_name} - 获取签到后的用户信息")
            self.logger.info(f"{'=' * 60}")

            user_info_result = api.get_user_info()

            if user_info_result['success']:
                result['user_info'] = user_info_result
                self.logger.info(f"✅ {account_name} 用户信息获取成功")
                self.logger.info(f"📊 抽奖次数: {user_info_result.get('lottery_times', 0)} 次")
                self.logger.info(f"💰 当前积分: {user_info_result.get('points', 0)}")
                self.logger.info(f"⏰ 即将过期积分: {user_info_result.get('advent_points', 0)}")
            else:
                error_msg = user_info_result.get('error', '获取用户信息失败')
                self.logger.warning(f"⚠️ {account_name} 获取用户信息失败: {error_msg}")
                # 获取用户信息失败不影响后续流程，继续执行

            # 执行抽奖任务
            self.logger.info(f"\n{'=' * 60}")
            self.logger.info(f"{account_name} - 执行抽奖任务")
            self.logger.info(f"{'=' * 60}")

            # 获取抽奖次数和组件信息
            lottery_times = result['user_info'].get('lottery_times', 0)
            component_number = result['user_info'].get('lottery_component_number', 'ZJ2025092916515917')
            component_node_id = result['user_info'].get('lottery_component_node_id', 'FN1762346087mJlk')

            # 获取最大抽奖次数限制（从账号配置中读取，如果没有则默认为2）
            default_max_lottery = 5
            max_lottery_limit = account_info.get('max_lottery_limit')

            # 检查是否自定义了最大抽奖次数
            if max_lottery_limit is None:
                # 没有设置，使用默认值
                max_lottery_limit = default_max_lottery
                is_custom_limit = False
            else:
                # 已设置自定义值
                is_custom_limit = True

            # 实际执行的抽奖次数为可用次数和限制次数中的较小值
            actual_lottery_times = min(lottery_times, max_lottery_limit)

            if lottery_times > 0:
                self.logger.info(f"🎲 {account_name} 有 {lottery_times} 次抽奖机会")

                # 根据是否自定义显示不同的提示信息
                if is_custom_limit:
                    self.logger.info(f"⚙️  最大抽奖次数限制: {max_lottery_limit} 次")
                else:
                    self.logger.info(f"⚙️  最大抽奖次数限制: {max_lottery_limit} 次（默认值，如需自定义请在token.json中添加max_lottery_limit字段）")

                self.logger.info(f"🎯 本次将执行 {actual_lottery_times} 次抽奖")

                lottery_results = []
                prize_list = []

                for i in range(actual_lottery_times):
                    # 随机延迟 1-3 秒
                    import random
                    import time
                    delay = random.uniform(1, 3)
                    self.logger.info(f"⏱️  等待 {delay:.1f} 秒后进行第 {i+1}/{actual_lottery_times} 次抽奖...")
                    time.sleep(delay)

                    # 执行抽奖
                    lottery_result = api.lottery(
                        component_number=component_number,
                        component_node_id=component_node_id
                    )

                    lottery_results.append(lottery_result)

                    if lottery_result['success']:
                        prize_name = lottery_result.get('prize_name', '未知奖品')
                        prize_list.append(prize_name)
                        self.logger.info(f"🎁 第 {i+1} 次抽奖成功！获得: {prize_name}")
                    else:
                        error_type = lottery_result.get('error_type', '')
                        error_msg = lottery_result.get('error', '抽奖失败')

                        # 检查是否是token过期
                        if error_type == 'token_expired':
                            self.logger.error(f"❌ {account_name} Token已过期，停止抽奖")
                            break
                        else:
                            self.logger.error(f"❌ 第 {i+1} 次抽奖失败: {error_msg}")

                # 保存抽奖结果
                result['lottery_info'] = {
                    'total_attempts': actual_lottery_times,
                    'successful_draws': len([r for r in lottery_results if r['success']]),
                    'results': lottery_results,
                    'prizes': prize_list
                }

                # 输出抽奖统计
                if prize_list:
                    self.logger.info(f"🎉 {account_name} 抽奖完成！共获得 {len(prize_list)} 个奖品:")
                    for idx, prize in enumerate(prize_list, 1):
                        self.logger.info(f"   {idx}. {prize}")
                else:
                    self.logger.info(f"📭 {account_name} 抽奖完成，未中奖")
            else:
                self.logger.info(f"📭 {account_name} 没有抽奖次数")

            # 获取任务完成后的最新用户信息
            self.logger.info(f"\n{'=' * 60}")
            self.logger.info(f"{account_name} - 获取任务完成后的最新信息")
            self.logger.info(f"{'=' * 60}")

            final_user_info = api.get_user_info()
            if final_user_info['success']:
                result['final_user_info'] = final_user_info
                self.logger.info(f"✅ {account_name} 最新信息获取成功")
                self.logger.info(f"📊 剩余抽奖次数: {final_user_info.get('lottery_times', 0)} 次")
                self.logger.info(f"💰 当前积分: {final_user_info.get('points', 0)}")
                self.logger.info(f"⏰ 即将过期积分: {final_user_info.get('advent_points', 0)}")
            else:
                self.logger.warning(f"⚠️ {account_name} 获取最新信息失败")


        except Exception as e:
            error_msg = f"处理账号时发生异常: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            result['message'] = error_msg
            import traceback
            traceback.print_exc()

        return result

    def run(self):
        """执行所有账号的签到和抽奖任务"""
        import random
        import time

        self.logger.info("=" * 60)
        self.logger.info("WPS自动签到和抽奖任务开始")
        self.logger.info("=" * 60)

        if not self.accounts:
            self.logger.warning("没有需要处理的账号")
            return

        # 处理每个账号
        for idx, account_info in enumerate(self.accounts):
            result = self.process_account(account_info)
            self.account_results.append(result)

            # 在处理完一个账号后，如果还有下一个账号，则等待5-10秒
            if idx < len(self.accounts) - 1:
                delay = random.uniform(5, 10)
                self.logger.info(f"\n⏱️  等待 {delay:.1f} 秒后处理下一个账号...")
                time.sleep(delay)

        # 输出统计信息
        self._print_summary()

        # 发送通知
        self._send_notification()

    def _print_summary(self):
        """打印执行结果统计"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("执行结果统计")
        self.logger.info("=" * 60)

        total = len(self.account_results)
        success = sum(1 for r in self.account_results if r['success'])
        failed = total - success

        self.logger.info(f"总账号数: {total}")
        self.logger.info(f"签到成功: {success}")
        self.logger.info(f"签到失败: {failed}")

        # 统计抽奖信息
        prize_summary = {}
        total_attempts = 0
        total_successful_draws = 0

        for result in self.account_results:
            if result.get('lottery_info'):
                lottery_info = result['lottery_info']
                # 从新的数据结构中提取所有抽奖结果
                lottery_results = lottery_info.get('results', [])

                for single_result in lottery_results:
                    if single_result['success']:
                        lottery_data = single_result.get('data', {})
                        prize_name = lottery_data.get('prize_name', '未知')
                        if prize_name and prize_name != '未知' and prize_name != '未中奖':
                            prize_summary[prize_name] = prize_summary.get(prize_name, 0) + 1

                # 统计抽奖次数
                total_attempts += lottery_info.get('total_attempts', 0)
                total_successful_draws += lottery_info.get('successful_draws', 0)

        if total_attempts > 0:
            self.logger.info(f"\n📊 抽奖统计: 总共尝试 {total_attempts} 次，成功 {total_successful_draws} 次")

        if prize_summary:
            self.logger.info("\n🎁 奖品统计:")
            for prize, count in prize_summary.items():
                self.logger.info(f"  {prize}: {count}个")

        # 打印详细结果
        self.logger.info("\n详细结果:")
        for result in self.account_results:
            status = "✅ 成功" if result['success'] else "❌ 失败"
            self.logger.info(f"  {result['account_name']}: {status} - {result['message']}")

        self.logger.info("=" * 60)

    def _send_notification(self):
        """发送推送通知"""
        if not self.account_results:
            return

        total = len(self.account_results)
        success = sum(1 for r in self.account_results if r['success'])
        failed = total - success

        # 构造通知标题
        title = "WPS签到和抽奖结果通知"

        # 构造通知内容
        content_lines = [
            f"📊 总账号数: {total}",
            f"✅ 签到成功: {success}",
            f"❌ 签到失败: {failed}",
            ""
        ]

        content_lines.append("📋 详细结果:")
        for result in self.account_results:
            status = "✅" if result['success'] else "❌"
            content_lines.append(f"{status} {result['account_name']}: {result['message']}")

            # 添加签到奖励信息
            sign_rewards = result.get('sign_rewards', [])
            if sign_rewards:
                content_lines.append(f"    🎁 签到奖励: {', '.join(sign_rewards)}")

            # 添加抽奖结果信息
            lottery_info = result.get('lottery_info')
            if lottery_info:
                lottery_results = lottery_info.get('results', [])
                if lottery_results:
                    content_lines.append("    🎲 抽奖结果:")
                    for idx, single_result in enumerate(lottery_results, 1):
                        if single_result['success']:
                            # 直接从single_result获取prize_name，因为api.py返回的数据结构中prize_name在第一层
                            prize_name = single_result.get('prize_name', '未知')
                            content_lines.append(f"       第{idx}次: {prize_name}")
                        else:
                            # 抽奖失败的情况
                            error_msg = single_result.get('error', '抽奖失败')
                            content_lines.append(f"       第{idx}次: {error_msg}")

            # 添加账户信息
            final_info = result.get('final_user_info', {}) or {}
            if final_info.get('success'):
                content_lines.append(
                    f"    📊 账户信息: 抽奖次数 {final_info.get('lottery_times', 0)} | 积分 {final_info.get('points', 0)} | 即将过期 {final_info.get('advent_points', 0)}"
                )
            else:
                content_lines.append("    ⚠️ 账户信息获取失败")

            # 在每个账号之间添加空行（最后一个账号除外）
            if result != self.account_results[-1]:
                content_lines.append("")

        content = "\n".join(content_lines)

        # 发送通知
        try:
            send_notification(
                title=title,
                content=content,
                sound=NotificationSound.BIRDSONG
            )
            self.logger.info("✅ 推送通知已发送")
        except Exception as e:
            self.logger.warning(f"⚠️ 发送推送通知失败: {str(e)}")


def main():
    """主函数"""
    try:
        # 创建任务执行器
        tasks = WPSTasks()

        # 执行任务
        tasks.run()

    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print("请确保配置文件存在并包含WPS账号信息")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()