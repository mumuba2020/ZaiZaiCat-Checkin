"""华润通文体未来荟 API 接口。"""

import base64
import json
import ssl
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter


class _LegacyTlsAdapter(HTTPAdapter):
    """仅为目标服务启用旧式 TLS 服务端连接兼容。"""

    def init_poolmanager(self, *args, **kwargs):
        """创建保留证书校验、允许旧式重协商的连接池。"""
        ssl_context = ssl.create_default_context()
        ssl_context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


class WenTiWeiLaiHuiAPI:
    """封装文体未来荟签到和会员积分接口。"""

    BASE_URL = "https://wlhmobile.crland.com.cn"
    APP_ID = "wx020209beec4251e0"
    PROJECT_UUID = "3a59e62a07f811f1bec0aeefcf2e061a"
    AUTH_SCHEME = "Wechat "
    REQUEST_TIMEOUT = (3, 10)
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 "
        "Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
        "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF "
        "MacWechat/3.8.7(0x13080712) UnifiedPCMacWechat(0xf264171e) "
        "XWEB/18788"
    )

    def __init__(
        self,
        token: str,
        mobile: str = "",
        user_agent: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        """初始化 API 客户端。

        Args:
            token: 手机登录返回的 JWT，或完整的 Wechat Authorization 值。
            mobile: 手机号，仅为兼容现有配置保留，不参与接口请求。
            user_agent: 可选的小程序 User-Agent。
            session: 可选的 requests 会话，主要用于连接复用和测试。
        """
        self.token = self._normalize_token(token)
        self.mobile = mobile
        if session is None:
            self.session = requests.Session()
            self.session.mount(self.BASE_URL, _LegacyTlsAdapter())
        else:
            self.session = session
        self.headers = {
            "User-Agent": user_agent or self.DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Authorization": f"{self.AUTH_SCHEME}{self.token}" if self.token else "",
            "appId": self.APP_ID,
            "projectUuid": self.PROJECT_UUID,
            "xweb_xhr": "1",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{self.APP_ID}/64/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    @classmethod
    def _normalize_token(cls, token: str) -> str:
        """将裸 JWT 或完整 Authorization 值统一为裸 JWT。"""
        normalized = (token or "").strip()
        if normalized.lower().startswith(cls.AUTH_SCHEME.lower()):
            return normalized[len(cls.AUTH_SCHEME):].strip()
        return normalized

    @staticmethod
    def _error(code: str, message: str) -> Dict[str, Any]:
        """构造不包含敏感请求信息的稳定错误结果。"""
        return {"success": False, "code": code, "msg": message}

    @staticmethod
    def _response_message(response_data: Dict[str, Any]) -> str:
        """从远端响应中提取适合展示的消息。"""
        result = response_data.get("result")
        if isinstance(result, str) and result:
            return result

        for key in ("text", "message", "msg"):
            value = response_data.get(key)
            if isinstance(value, str) and value:
                return value
        return "请求成功" if response_data.get("success") else "接口返回失败"

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发送 POST 请求并将远端响应归一化为统一结果。"""
        try:
            response = self.session.post(
                f"{self.BASE_URL}{path}",
                json=payload,
                headers=self.headers,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            return self._error("REQUEST_TIMEOUT", "请求超时，请稍后重试")
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "未知"
            return self._error("HTTP_ERROR", f"接口返回 HTTP {status_code}")
        except requests.exceptions.RequestException:
            return self._error("REQUEST_FAILED", "网络请求失败")

        try:
            response_data = response.json()
        except ValueError:
            return self._error("INVALID_RESPONSE", "接口响应不是有效的 JSON")

        if not isinstance(response_data, dict):
            return self._error("INVALID_RESPONSE", "接口响应格式异常")

        response_data["success"] = response_data.get("code") == 200
        response_data["msg"] = self._response_message(response_data)
        return response_data

    def _extract_openid(self) -> Optional[str]:
        """从 JWT 载荷读取 openid，不记录或返回 Token 原文。"""
        token_parts = self.token.split(".")
        if len(token_parts) != 3:
            return None

        encoded_payload = token_parts[1]
        encoded_payload += "=" * (-len(encoded_payload) % 4)
        try:
            payload_bytes = base64.urlsafe_b64decode(encoded_payload)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

        openid = payload.get("openid") if isinstance(payload, dict) else None
        return openid.strip() if isinstance(openid, str) and openid.strip() else None

    def query_sign_in_record(self) -> Dict[str, Any]:
        """查询当前签到周期和今日签到状态。"""
        response = self._post(
            "/marketing/client/task/sign-in/record",
            {"projectUuid": self.PROJECT_UUID},
        )
        if response.get("success") and not isinstance(response.get("result"), dict):
            return self._error("INVALID_RESPONSE", "签到记录响应缺少 result")
        return response

    def sign_in(self) -> Dict[str, Any]:
        """执行每日签到；今日已签到时直接返回成功。"""
        record = self.query_sign_in_record()
        if not record.get("success"):
            return record

        if record["result"].get("isSignedToday") is True:
            record["msg"] = "今日已签到"
            record["already_signed"] = True
            return record

        response = self._post(
            "/marketing/client/task/daily/sign-in",
            {"projectUuid": self.PROJECT_UUID},
        )
        response["already_signed"] = False
        return response

    def query_points(self) -> Dict[str, Any]:
        """查询会员当前积分。"""
        openid = self._extract_openid()
        if not openid:
            return self._error("INVALID_TOKEN", "Token 格式无效或缺少 openid")

        response = self._post(
            "/member/client/detail",
            {"projectUuid": self.PROJECT_UUID, "openId": openid},
        )
        result = response.get("result")
        if response.get("success") and (
            not isinstance(result, dict) or "points" not in result
        ):
            return self._error("INVALID_RESPONSE", "会员详情响应缺少积分字段")
        return response
