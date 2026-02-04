#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
恩山论坛API模块

提供恩山论坛签到相关的API接口
"""

import json
import logging
import re
from typing import Dict, Optional, List

import requests

logger = logging.getLogger(__name__)


class EnshanAPI:
    """恩山论坛API类"""

    def __init__(self, cookies: str, formhash: Optional[str] = None, user_agent: Optional[str] = None):
        """
        初始化API类

        Args:
            cookies: 用户的Cookie字符串
            formhash: 表单hash值，用于验证请求（可选，自动获取）
            user_agent: 用户代理字符串，可选
        """
        self.cookies = cookies
        self.formhash = formhash or ""
        self.user_agent = user_agent or (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/144.0.0.0 Safari/537.36'
        )
        self.sign_url = 'https://www.right.com.cn/forum/plugin.php?id=erling_qd:action&action=sign'
        self.sign_in_page_url = 'https://www.right.com.cn/forum/erling_qd-sign_in.html'
        self.base_url = 'https://www.right.com.cn/forum'

    @staticmethod
    def _rotl8(x: int, r: int) -> int:
        """8-bit rotate left."""
        x &= 0xFF
        r &= 7
        return ((x << r) & 0xFF) | (x >> (8 - r))

    @staticmethod
    def _rotr8(x: int, r: int) -> int:
        """8-bit rotate right."""
        x &= 0xFF
        r &= 7
        return (x >> r) | ((x << (8 - r)) & 0xFF)

    @staticmethod
    def _extract_oo(html: str) -> Optional[List[int]]:
        match = re.search(r"oo\s*=\s*\[([^\]]+)\]", html)
        if not match:
            return None
        tokens = re.findall(r"0x[0-9a-fA-F]+|\d+", match.group(1))
        if not tokens:
            return None
        values = []
        for token in tokens:
            if token.lower().startswith("0x"):
                values.append(int(token, 16))
            else:
                values.append(int(token))
        return values

    @staticmethod
    def _extract_wi(html: str) -> Optional[int]:
        match = re.search(r'setTimeout\("\w+\((\d+)\)"', html)
        if match:
            return int(match.group(1))
        match = re.search(r"\b\w+\((\d+)\)", html)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_loop1_params(html: str) -> Optional[Dict[str, int]]:
        pattern = (
            r"qo\s*=\s*(\d+);\s*do\{.*?oo\[qo\]=\(-oo\[qo\]\)&0xff;.*?"
            r"oo\[qo\]=\(\(\(oo\[qo\]>>(\d+)\)\|\(\(oo\[qo\]<<(\d+)\)&0xff\)\)\-(\d+)\)&0xff;.*?"
            r"\}\s*while\(--qo>=2\);"
        )
        match = re.search(pattern, html, re.S)
        if not match:
            return None
        return {
            "start": int(match.group(1)),
            "shift_r": int(match.group(2)),
            "shift_l": int(match.group(3)),
            "sub": int(match.group(4)),
        }

    @staticmethod
    def _extract_loop2_start(html: str) -> Optional[int]:
        match = re.search(
            r"qo\s*=\s*(\d+);\s*do\s*\{[^}]*?oo\[qo\]\s*=\s*\(oo\[qo\]\s*-\s*oo\[qo\s*-\s*1\]\)\s*&\s*0xff;[^}]*?\}\s*while\s*\(\s*--\s*qo\s*>=\s*3\s*\)",
            html,
            re.S,
        )
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_loop3_params(html: str) -> Optional[Dict[str, int]]:
        block_match = re.search(
            r"qo\s*=\s*1;\s*for\s*\(.*?\)\s*\{(.*?)\}\s*po\s*=",
            html,
            re.S,
        )
        if not block_match:
            return None
        block = block_match.group(1)

        upper_match = re.search(r"qo\s*>\s*(\d+)\)\s*break", block)
        if not upper_match:
            return None
        upper = int(upper_match.group(1))

        assign_match = re.search(r"oo\[qo\]\s*=\s*(.+?);", block, re.S)
        if not assign_match:
            return None
        expr = assign_match.group(1)

        add_nums = re.findall(r"\+\s*(\d+)", expr)
        if len(add_nums) < 2:
            return None
        add1 = int(add_nums[0])
        add2 = int(add_nums[1])

        shift_nums = re.findall(r"<<\s*(\d+)|>>\s*(\d+)", expr)
        shifts = []
        for left, right in shift_nums:
            if left:
                shifts.append(int(left))
            if right:
                shifts.append(int(right))
        if len(shifts) < 2:
            return None
        rot_l = shifts[0]
        return {
            "upper": upper,
            "add1": add1,
            "add2": add2,
            "rot_l": rot_l,
        }

    @staticmethod
    def _extract_mod_skip(html: str) -> int:
        match = re.search(r"qo\s*%\s*(\d+)", html)
        if not match:
            return 7
        return int(match.group(1))

    def _decode_po(self, oo_hex: List[int], wi: int, params: Dict[str, int]) -> str:
        oo = [b & 0xFF for b in oo_hex]
        if len(oo) < 6:
            return ""

        last_index = len(oo) - 1

        loop1_start = params["loop1_start"]
        loop2_start = params["loop2_start"]
        loop3_upper = params["loop3_upper"]
        shift_r = params["shift_r"]
        shift_l = params["shift_l"]
        sub = params["sub"]
        add1 = params["add1"]
        add2 = params["add2"]
        rot_l = params["rot_l"]
        mod_skip = params["mod_skip"]

        qo = min(loop1_start, last_index - 1)
        while True:
            oo[qo] = (-oo[qo]) & 0xFF
            if (shift_r + shift_l) == 8:
                oo[qo] = (self._rotr8(oo[qo], shift_r) - sub) & 0xFF
            else:
                oo[qo] = (((oo[qo] >> shift_r) | ((oo[qo] << shift_l) & 0xFF)) - sub) & 0xFF
            qo -= 1
            if qo < 2:
                break

        qo = min(loop2_start, last_index - 2)
        while True:
            oo[qo] = (oo[qo] - oo[qo - 1]) & 0xFF
            qo -= 1
            if qo < 3:
                break

        for qo in range(1, min(loop3_upper, last_index - 1) + 1):
            x = (oo[qo] + add1) & 0xFF
            x = (x + add2) & 0xFF
            oo[qo] = self._rotl8(x, rot_l)

        po_chars = []
        for qo in range(1, last_index):
            if qo % mod_skip != 0:
                po_chars.append(chr((oo[qo] ^ (wi & 0xFF)) & 0xFF))

        return "".join(po_chars)

    @staticmethod
    def _extract_cookie_kv(decoded_js: str) -> Optional[str]:
        match = re.search(r"document\.cookie=['\"]([^'\"]+)['\"]", decoded_js)
        if not match:
            return None
        cookie_str = match.group(1).strip()
        if not cookie_str:
            return None
        return cookie_str.split(';', 1)[0].strip()

    @staticmethod
    def _upsert_cookie(base_cookies: str, new_cookie_kv: str) -> str:
        if not new_cookie_kv or '=' not in new_cookie_kv:
            return base_cookies
        new_key, new_value = new_cookie_kv.split('=', 1)
        new_key = new_key.strip()
        new_value = new_value.strip()

        parts = []
        replaced = False
        for raw in base_cookies.split(';'):
            part = raw.strip()
            if not part or '=' not in part:
                continue
            key, value = part.split('=', 1)
            key = key.strip()
            if key == new_key:
                parts.append(f"{new_key}={new_value}")
                replaced = True
            else:
                parts.append(f"{key}={value.strip()}")

        if not replaced:
            parts.append(f"{new_key}={new_value}")

        return '; '.join(parts)

    @staticmethod
    def _extract_formhash(html: str) -> Optional[str]:
        match = re.search(
            r"member\.php\?mod=logging(?:&amp;|&)action=logout(?:&amp;|&)formhash=([0-9a-fA-F]+)",
            html,
        )
        if not match:
            return None
        return match.group(1)

    def _get_clearance_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': self.user_agent,
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,image/apng,*/*;q=0.8'
            ),
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Brave";v="144"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'Upgrade-Insecure-Requests': '1',
            'Sec-GPC': '1',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': self.sign_in_page_url,
            'Cookie': self.cookies
        }

    def _merge_response_cookies(self, response: requests.Response) -> None:
        for name, value in response.cookies.items():
            self.cookies = self._upsert_cookie(self.cookies, f"{name}={value}")

    def _refresh_clearance_cookie(self) -> Optional[str]:
        try:
            response = requests.get(
                self.sign_in_page_url,
                headers=self._get_clearance_headers(),
                timeout=30
            )
        except requests.RequestException as exc:
            logger.warning("获取WAF页面失败，可能影响签到: %s", exc)
            return None
        # print(response.text)
        self._merge_response_cookies(response)

        if "oo" not in response.text:
            formhash = self._extract_formhash(response.text)
            if formhash:
                self.formhash = formhash
            return response.text

        oo = self._extract_oo(response.text)
        wi = self._extract_wi(response.text)
        if not oo or wi is None:
            logger.warning("WAF响应解析失败，无法提取解密参数")
            return None

        loop1 = self._extract_loop1_params(response.text)
        loop2_start = self._extract_loop2_start(response.text)
        loop3 = self._extract_loop3_params(response.text)
        if not loop1 or loop2_start is None or not loop3:
            logger.warning("WAF解密参数提取失败")
            return None

        mod_skip = self._extract_mod_skip(response.text)
        params = {
            "loop1_start": loop1["start"],
            "loop2_start": loop2_start,
            "loop3_upper": loop3["upper"],
            "shift_r": loop1["shift_r"],
            "shift_l": loop1["shift_l"],
            "sub": loop1["sub"],
            "add1": loop3["add1"],
            "add2": loop3["add2"],
            "rot_l": loop3["rot_l"],
            "mod_skip": mod_skip,
        }

        decoded_js = self._decode_po(oo, wi, params)
        cookie_kv = self._extract_cookie_kv(decoded_js)
        if not cookie_kv:
            logger.warning("WAF解密成功但未找到cookie")
            return None

        self.cookies = self._upsert_cookie(self.cookies, cookie_kv)
        logger.info("已获取并更新 https_ydclearance cookie")

        try:
            follow = requests.get(
                self.sign_in_page_url,
                headers=self._get_clearance_headers(),
                timeout=30
            )
        except requests.RequestException:
            return None
        self._merge_response_cookies(follow)
        formhash = self._extract_formhash(follow.text)
        if formhash:
            self.formhash = formhash
        return follow.text

    def get_headers(self) -> Dict[str, str]:
        """
        获取请求头

        Returns:
            Dict[str, str]: 请求头字典
        """
        return {
            'User-Agent': self.user_agent,
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'sec-ch-ua-platform': '"macOS"',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Brave";v="144"',
            'sec-ch-ua-mobile': '?0',
            'Sec-GPC': '1',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Origin': 'https://www.right.com.cn',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': self.sign_in_page_url,
            'Cookie': self.cookies
        }

    def sign_in(self) -> Dict:
        """
        执行签到

        Returns:
            Dict: 签到结果
                {
                    'success': bool,  # 是否成功
                    'result': dict,   # 成功时的结果数据
                    'error': str      # 失败时的错误信息
                }
        """
        logger.info("开始执行恩山论坛签到...")
        self._refresh_clearance_cookie()
        if not self.formhash:
            error_msg = "未获取到formhash，无法签到"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
        headers = self.get_headers()
        data = {
            'formhash': self.formhash
        }
        try:
            response = requests.post(
                self.sign_url,
                headers=headers,
                data=data,
                timeout=30
            )

            # 检查响应状态
            response.raise_for_status()

            # 尝试解析JSON响应
            try:
                result = response.json()
            except json.JSONDecodeError:
                result = {
                    'status': 'success',
                    'message': response.text
                }

            logger.info(f"恩山论坛签到成功: {result}")
            return {
                'success': True,
                'result': result
            }

        except requests.RequestException as e:
            error_msg = f"签到失败: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def get_user_info(self) -> Dict:
        """
        获取用户信息（可选功能）

        Returns:
            Dict: 用户信息
        """
        # 这里可以添加获取用户信息的逻辑
        # 目前返回空字典
        return {}
