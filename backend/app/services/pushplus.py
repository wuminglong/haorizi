from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import httpx

from app.config import get_settings
from app.models import Group, Reminder, ReminderPlan


class PushPlusSendError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        request_payload: dict | None = None,
        response_payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.request_payload = request_payload
        self.response_payload = response_payload


class PushPlusClient:
    send_url = "https://www.pushplus.plus/send"
    access_key_url = "https://www.pushplus.plus/api/common/openApi/getAccessKey"
    topic_list_url = "https://www.pushplus.plus/api/open/topic/list"
    topic_qrcode_url = "https://www.pushplus.plus/api/open/topic/qrCode"
    _access_key: str | None = None
    _access_key_expire_at: datetime | None = None
    _access_key_lock = Lock()

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_enabled(self) -> bool:
        return self.settings.pushplus_enabled and bool(self.settings.pushplus_token)

    def is_open_api_enabled(self) -> bool:
        return bool(self.settings.pushplus_token and self.settings.pushplus_secret_key)

    def _plan_type_text(self, plan: ReminderPlan) -> str:
        if plan.kind == "on_day":
            return "当天提醒"
        return "提前提醒"

    def build_payload(self, group: Group, reminder: Reminder, plan: ReminderPlan) -> dict[str, Any]:
        content = "\n".join(
            [
                f"提醒：{reminder.title}",
                f"相关人：{reminder.person_name or '无'}",
                f"目标日：{plan.target_date.isoformat()}",
                f"类型：{self._plan_type_text(plan)}",
                f"备注：{reminder.remark or '无'}",
            ]
        )
        return {
            "token": self.settings.pushplus_token,
            "title": f"好日子提醒：{reminder.title}",
            "content": content,
            "template": "txt",
            "topic": group.push_topic_code,
        }

    def send_group_reminder(
        self,
        group: Group,
        reminder: Reminder,
        plan: ReminderPlan,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.is_enabled():
            # dry mode for local/dev when pushplus not configured
            payload = self.build_payload(group, reminder, plan)
            safe = {**payload, "token": "***"}
            return safe, {"code": 200, "msg": "dry-run", "data": None}

        payload = self.build_payload(group, reminder, plan)
        safe_payload = {**payload, "token": "***"}
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(self.send_url, json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise PushPlusSendError(
                error_code="pushplus_http_error",
                message="PushPlus 网络请求失败",
                request_payload=safe_payload,
                response_payload={"detail": str(exc)},
            ) from exc
        except ValueError as exc:
            raise PushPlusSendError(
                error_code="pushplus_invalid_response",
                message="PushPlus 返回了无法解析的响应",
                request_payload=safe_payload,
            ) from exc
        code = body.get("code")
        if code not in {200, "200"}:
            raise PushPlusSendError(
                error_code=str(code or "pushplus_failed"),
                message=str(body.get("msg") or body.get("message") or "PushPlus send failed"),
                request_payload=safe_payload,
                response_payload=body,
            )
        return safe_payload, body

    def get_access_key(self) -> str:
        if not self.settings.pushplus_token or not self.settings.pushplus_secret_key:
            raise PushPlusSendError("pushplus_open_api_not_configured", "PushPlus open API is not configured")

        now = datetime.now(timezone.utc)
        with self._access_key_lock:
            if self._access_key and self._access_key_expire_at and now < self._access_key_expire_at:
                return self._access_key

            payload = {
                "token": self.settings.pushplus_token,
                "secretKey": self.settings.pushplus_secret_key,
            }
            with httpx.Client(timeout=10) as client:
                response = client.post(self.access_key_url, json=payload)
            response.raise_for_status()
            body = response.json()
            if body.get("code") not in {200, "200"}:
                raise PushPlusSendError(
                    error_code=str(body.get("code") or "access_key_failed"),
                    message=str(body.get("msg") or "PushPlus access-key 获取失败"),
                    request_payload={"token": "***", "secretKey": "***"},
                    response_payload=body,
                )
            data = body.get("data") or {}
            access_key = data.get("accessKey")
            if not access_key:
                raise PushPlusSendError(
                    error_code="access_key_missing",
                    message="PushPlus access-key 响应缺少 accessKey",
                    response_payload=body,
                )
            expires_in = int(data.get("expiresIn") or 7200)
            self.__class__._access_key = str(access_key)
            self.__class__._access_key_expire_at = now + timedelta(seconds=max(60, expires_in - 300))
            return self.__class__._access_key

    def _open_api_headers(self) -> dict[str, str]:
        return {"access-key": self.get_access_key()}

    def get_owned_topics(self) -> list[dict[str, Any]]:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                self.topic_list_url,
                headers=self._open_api_headers(),
                json={"current": 1, "pageSize": 50, "params": {"topicType": 0}},
            )
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in {200, "200"}:
            raise PushPlusSendError(
                error_code=str(body.get("code") or "topic_list_failed"),
                message=str(body.get("msg") or "PushPlus 群组列表获取失败"),
                response_payload=body,
            )
        data = body.get("data") or {}
        return list(data.get("list") or [])

    def get_topic_qrcode_by_code(self, topic_code: str) -> dict[str, Any]:
        normalized_code = (topic_code or "").strip()
        if not normalized_code:
            raise PushPlusSendError("topic_code_required", "请输入群组编码")
        if not self.is_open_api_enabled():
            raise PushPlusSendError("pushplus_open_api_not_configured", "PushPlus open API is not configured")

        topic = next(
            (
                item
                for item in self.get_owned_topics()
                if str(item.get("topicCode", "")).strip() == normalized_code
            ),
            None,
        )
        if not topic:
            raise PushPlusSendError("topic_not_found", "未找到这个群组编码")

        topic_id = topic.get("topicId")
        with httpx.Client(timeout=10) as client:
            response = client.get(
                self.topic_qrcode_url,
                headers=self._open_api_headers(),
                params={
                    "topicId": topic_id,
                    "second": self.settings.pushplus_qr_seconds,
                    "scanCount": self.settings.pushplus_qr_scan_count,
                },
            )
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in {200, "200"}:
            raise PushPlusSendError(
                error_code=str(body.get("code") or "topic_qrcode_failed"),
                message=str(body.get("msg") or "PushPlus 群组二维码获取失败"),
                response_payload=body,
            )
        data = body.get("data") or {}
        qr_code_img_url = data.get("qrCodeImgUrl")
        if not qr_code_img_url:
            raise PushPlusSendError(
                error_code="topic_qrcode_missing",
                message="PushPlus 响应缺少二维码图片地址",
                response_payload=body,
            )
        return {
            "topic_code": topic.get("topicCode"),
            "topic_name": topic.get("topicName"),
            "topic_user_count": topic.get("topicUserCount"),
            "qr_code_img_url": qr_code_img_url,
            "forever": data.get("forever"),
            "expires_in_seconds": self.settings.pushplus_qr_seconds,
            "scan_count": self.settings.pushplus_qr_scan_count,
        }
