#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new Env('鸿星尔克签到');
cron: 1 1 1 1 1
"""

"""
鸿星尔克签到脚本

该脚本用于自动执行鸿星尔克小程序的签到任务，包括：
- 读取账号配置信息
- 查询积分明细
- 执行签到操作
- 输出执行结果统计

Author: ZaiZaiCat
Date: 2025-11-28
"""

import json
import logging
import sys
from typing import List, Dict, Any
from pathlib import Path

from api import ErkeAPI

# 获取项目根目录
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# 导入需要的模块
from notification import send_notification, NotificationSound



class ErkeTasks:
    """鸿星尔克签到任务自动化执行类"""

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
                # 从统一配置文件的 erke 节点读取
                erke_config = config_data.get('erke', {})
                self.accounts = erke_config.get('accounts', [])

            if not self.accounts:
                self.logger.warning("配置文件中没有找到 erke 账号信息")
            else:
                self.logger.info(f"成功加载 {len(self.accounts)} 个账号配置")

        except json.JSONDecodeError as e:
            self.logger.error(f"配置文件JSON解析失败: {e}")
            raise
        except Exception as e:
            self.logger.error(f"读取配置文件失败: {e}")
            raise

    def process_account(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理单个账号的任务

        Args:
            account (Dict[str, Any]): 账号信息字典

        Returns:
            Dict[str, Any]: 账号处理结果
        """
        account_name = account.get('account_name', '未命名账号')
        self.logger.info(f"\n{'='*50}")
        self.logger.info(f"开始处理账号: {account_name}")
        self.logger.info(f"{'='*50}")

        result = {
            'account_name': account_name,
            'success': False,
            'integral_info': None,
            'sign_info': None,
            'error': None
        }

        try:
            # 初始化API
            api = ErkeAPI(
                member_id=account.get('member_id', ''),
                enterprise_id=account.get('enterprise_id', ''),
                unionid=account.get('unionid', ''),
                openid=account.get('openid', ''),
                wx_openid=account.get('wx_openid', ''),
                user_agent=account.get('user_agent')
            )

            # 1. 查询积分明细
            self.logger.info(f"[{account_name}] 查询积分明细...")
            integral_result = api.get_integral_record(current_page=1, page_size=5)

            if integral_result['success']:
                result['integral_info'] = integral_result['result']
                self.logger.info(f"[{account_name}] 积分明细查询成功")

                # 解析积分信息
                if integral_result['result'] and isinstance(integral_result['result'], dict):
                    response = integral_result['result'].get('response', {})
                    if isinstance(response, dict):
                        # 获取累计积分和冻结积分
                        accumulate_points = response.get('accumulatPoints', 0)
                        frozen_points = response.get('frozenPoints', 0)
                        available_points = accumulate_points - frozen_points

                        self.logger.info(f"[{account_name}] 累计积分: {accumulate_points}")
                        self.logger.info(f"[{account_name}] 冻结积分: {frozen_points}")
                        self.logger.info(f"[{account_name}] 可用积分: {available_points}")

                        # 获取积分明细列表
                        page_data = response.get('page', {})
                        if page_data:
                            total_count = page_data.get('totalCount', 0)
                            self.logger.info(f"[{account_name}] 积分记录数: {total_count}")
            else:
                self.logger.warning(f"[{account_name}] 积分明细查询失败: {integral_result['error']}")

            # 2. 执行签到
            self.logger.info(f"[{account_name}] 执行签到...")
            sign_result = api.member_sign()

            if sign_result['success']:
                result['sign_info'] = sign_result['result']
                self.logger.info(f"[{account_name}] 签到结果: {sign_result['result']}")

                # 解析签到返回的信息
                if sign_result['result'] and isinstance(sign_result['result'], dict):
                    code = str(sign_result['result'].get('code', '') or '').strip()
                    message = sign_result['result'].get('message', '') or ''

                    success_codes = {'0000', '1001', '0', '200'}
                    message_indicates_success = any(keyword in message for keyword in ['成功', '已签到'])

                    if code in success_codes or message_indicates_success:
                        result['success'] = True
                        log_msg = message or '签到成功'
                        self.logger.info(f"[{account_name}] {log_msg}")
                    else:
                        result['success'] = False
                        result['error'] = message or f'未知返回码: {code}'
                        self.logger.warning(f"[{account_name}] 签到返回: {message or code}")
                else:
                    result['success'] = True
                    self.logger.info(f"[{account_name}] 签到完成")
            else:
                result['error'] = sign_result['error']
                self.logger.error(f"[{account_name}] 签到失败: {sign_result['error']}")

        except Exception as e:
            error_msg = f"处理账号时发生异常: {str(e)}"
            self.logger.error(f"[{account_name}] {error_msg}")
            result['error'] = error_msg

        return result

    def run(self):
        """执行所有账号的签到任务"""
        self.logger.info("="*60)
        self.logger.info("鸿星尔克签到任务开始执行")
        self.logger.info("="*60)

        if not self.accounts:
            self.logger.error("没有可处理的账号")
            return

        # 处理每个账号
        for account in self.accounts:
            result = self.process_account(account)
            self.account_results.append(result)


        # 输出统计信息
        self._print_summary()

        # 发送通知
        self._send_notification()

    def _print_summary(self):
        """输出执行结果统计"""
        self.logger.info("\n" + "="*60)
        self.logger.info("执行结果统计")
        self.logger.info("="*60)

        success_count = sum(1 for r in self.account_results if r['success'])
        fail_count = len(self.account_results) - success_count

        self.logger.info(f"总账号数: {len(self.account_results)}")
        self.logger.info(f"成功: {success_count}")
        self.logger.info(f"失败: {fail_count}")

        if fail_count > 0:
            self.logger.info("\n失败账号详情:")
            for result in self.account_results:
                if not result['success']:
                    self.logger.info(f"  - {result['account_name']}: {result['error']}")

    def _send_notification(self):
        """发送执行结果通知"""
        try:
            success_count = sum(1 for r in self.account_results if r['success'])
            total_count = len(self.account_results)

            # 构建通知标题
            title = "鸿星尔克签到任务完成"

            # 构建通知内容
            content_lines = [
                f"📊 执行统计:",
                f"  - 总账号数: {total_count}",
                f"  - 成功: {success_count}",
                f"  - 失败: {total_count - success_count}",
            ]

            # 添加每个账号的详细信息
            content_lines.append("\n📋 账号详情:")
            for result in self.account_results:
                status = "✅" if result['success'] else "❌"
                content_lines.append(f"  {status} {result['account_name']}")

                if result['success'] and result['sign_info']:
                    if isinstance(result['sign_info'], dict):
                        message = result['sign_info'].get('message', '')
                        if message:
                            content_lines.append(f"     └─ {message}")

            content = "\n".join(content_lines)

            # 发送通知
            send_notification(
                title=title,
                content=content,
                sound=NotificationSound.BIRDSONG
            )
            self.logger.info("通知发送成功")

        except Exception as e:
            self.logger.error(f"发送通知失败: {str(e)}")


def main():
    """主函数"""
    try:
        tasks = ErkeTasks()
        tasks.run()
    except Exception as e:
        logging.error(f"程序执行失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

