"""
new Env('华润通文体未来荟签到');
cron: 1 1 1 1 1
"""

"""
文体未来荟签到脚本
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from api import WenTiWeiLaiHuiAPI

# 添加项目根目录到Python路径以导入notification模块
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

from notification import send_notification, NotificationSound


def load_config():
    """加载统一配置文件"""
    # 使用统一的 token.json 配置文件
    # 从当前文件位置向上三级到达项目根目录，然后进入 config 目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, '..', '..', '..', 'config', 'token.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def mask_mobile(mobile):
    """脱敏用于日志展示的手机号。"""
    value = str(mobile or "")
    if len(value) <= 7:
        return "*" * len(value) if value else "未配置"
    return f"{value[:3]}****{value[-4:]}"


def process_account(account_config):
    """处理单个账号的签到"""
    account_name = account_config.get('account_name', '未知账号')
    token = account_config.get('token')
    mobile = account_config.get('mobile')

    # 初始化结果
    result_info = {
        'account_name': account_name,
        'mobile': mobile,
        'success': False,
        'error': None,
        'sign_message': None,
        'points': None,
        'points_error': None
    }

    print("=" * 50)
    print(f"账号: {account_name} ({mask_mobile(mobile)})")
    print("=" * 50)

    # 创建API实例
    api = WenTiWeiLaiHuiAPI(token, mobile, account_config.get('user_agent'))

    # 执行签到
    print("\n开始签到...")
    sign_result = api.sign_in()

    if sign_result.get("success"):
        msg = sign_result.get('msg', '签到成功')
        print(f"✓ 签到成功: {msg}")
        result_info['sign_message'] = msg
        result_info['success'] = True
    else:
        msg = sign_result.get('msg', '签到失败')
        print(f"✗ 签到失败: {msg}")
        result_info['error'] = msg

    # 查询积分
    print("\n查询会员积分...")
    points_result = api.query_points()

    if points_result.get("success"):
        data = points_result.get("result", {})
        points = data.get("points", 0)

        print(f"✓ 查询成功")
        print(f"  当前积分: {points}")

        result_info['points'] = points
    else:
        msg = points_result.get('msg', '查询失败')
        print(f"✗ 查询失败: {msg}")
        result_info['points_error'] = msg

    print("\n" + "=" * 50)
    return result_info


def send_notification_summary(all_results, start_time, end_time):
    """
    发送任务执行结果的推送通知

    Args:
        all_results: 所有账号的执行结果列表
        start_time: 任务开始时间
        end_time: 任务结束时间
    """
    try:
        duration = (end_time - start_time).total_seconds()

        # 统计结果
        total_count = len(all_results)
        success_count = sum(1 for r in all_results if r.get('success'))
        failed_count = total_count - success_count

        # 构建通知标题
        if failed_count == 0:
            title = "文体未来荟签到成功 ✅"
            sound = NotificationSound.BIRDSONG
        elif success_count == 0:
            title = "文体未来荟签到失败 ❌"
            sound = NotificationSound.ALARM
        else:
            title = "文体未来荟签到部分成功 ⚠️"
            sound = NotificationSound.BELL

        # 构建通知内容
        content_parts = [
            "📊 执行统计:",
            f"✅ 成功: {success_count} 个账号",
            f"❌ 失败: {failed_count} 个账号",
            f"📈 总计: {total_count} 个账号",
            "",
            "📝 详情:"
        ]

        for result in all_results:
            account_name = result.get('account_name', '未知账号')
            if result.get('success'):
                content_parts.append(f"  ✅ [{account_name}]")
                if result.get('points') is not None:
                    content_parts.append(f"     当前积分: {result['points']}")
                else:
                    content_parts.append("     积分查询失败")
            else:
                error = result.get('error', '未知错误')
                if len(error) > 30:
                    error = error[:30] + "..."
                content_parts.append(f"  ❌ [{account_name}] {error}")

        content_parts.append("")
        content_parts.append(f"⏱️ 执行耗时: {int(duration)}秒")
        content_parts.append(f"🕐 完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        content = "\n".join(content_parts)

        # 发送通知
        send_notification(
            title=title,
            content=content,
            sound=sound
        )
        print("✅ 推送通知发送成功")

    except Exception as e:
        print(f"❌ 推送通知失败: {str(e)}")


def main():
    """主函数"""
    # 记录开始时间
    start_time = datetime.now()
    print("=" * 50)
    print("文体未来荟签到脚本")
    print(f"开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()

    # 加载配置
    config = load_config()
    accounts = config.get('huaruntong', {}).get('wentiweilaihui', {}).get('accounts', [])

    if not accounts:
        print("❌ 配置文件中没有找到账号信息")
        return

    # 收集所有账号的结果
    all_results = []

    # 遍历所有账号
    for account in accounts:
        if not account.get('token'):
            print(f"⚠️  跳过账号 {account.get('account_name', '未知')}: token 为空")
            print("=" * 50)
            all_results.append({
                'account_name': account.get('account_name', '未知'),
                'success': False,
                'error': 'token为空'
            })
            continue

        result = process_account(account)
        all_results.append(result)
        print("\n")

    # 记录结束时间
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("=" * 50)
    print("执行完成")
    print(f"结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"执行耗时: {int(duration)} 秒")
    print("=" * 50)

    # 发送推送通知
    send_notification_summary(all_results, start_time, end_time)


if __name__ == "__main__":
    main()
