from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape

from bson import ObjectId

from app.models import AlertReason


@dataclass(frozen=True, slots=True)
class AlertEmailJob:
    alert_id: ObjectId
    user_id: str
    product_title: str
    image_url: str
    product_url: str
    old_price: Decimal
    new_price: Decimal
    reason: AlertReason
    target_price: Decimal | None
    detected_at: datetime


def format_price(value: Decimal) -> str:
    return f"₹{value:,.2f}"


def percent_drop(old_price: Decimal, new_price: Decimal) -> Decimal:
    return ((old_price - new_price) / old_price * 100).quantize(Decimal("0.1"))


def reason_text(job: AlertEmailJob) -> str:
    if job.reason is AlertReason.TARGET_PRICE and job.target_price is not None:
        return f"Target price reached (your target: {format_price(job.target_price)})"
    if job.reason is AlertReason.TARGET_PRICE:
        return "Target price reached"
    return "Lowest price in the last 30 days"


def render_alert_email(job: AlertEmailJob) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for a price-drop alert."""
    drop = percent_drop(job.old_price, job.new_price)
    old_price = format_price(job.old_price)
    new_price = format_price(job.new_price)
    reason = reason_text(job)

    title = job.product_title
    subject = f"Price drop: {title[:80]} is now {new_price} (-{drop}%)"

    text = (
        f"Price drop on {title}\n\n"
        f"Was: {old_price}\n"
        f"Now: {new_price} ({drop}% off)\n"
        f"Why you're seeing this: {reason}\n\n"
        f"View product: {job.product_url}\n"
    )

    html = f"""\
<!doctype html>
<html>
<body style="margin:0;padding:24px;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:#1f2933;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:8px;overflow:hidden;">
        <tr><td style="background:#0f766e;color:#ffffff;padding:16px 24px;font-size:14px;font-weight:bold;">PriceScope &middot; Price drop alert</td></tr>
        <tr><td align="center" style="padding:24px 24px 8px;">
          <img src="{escape(job.image_url, quote=True)}" alt="" width="200" style="max-width:200px;height:auto;border-radius:4px;">
        </td></tr>
        <tr><td style="padding:8px 24px;font-size:18px;font-weight:bold;">{escape(title)}</td></tr>
        <tr><td style="padding:8px 24px;">
          <span style="color:#6b7280;text-decoration:line-through;font-size:16px;">{old_price}</span>
          <span style="color:#0f766e;font-size:26px;font-weight:bold;margin-left:8px;">{new_price}</span>
          <span style="background:#dcfce7;color:#166534;font-size:13px;font-weight:bold;padding:3px 8px;border-radius:12px;margin-left:8px;">-{drop}%</span>
        </td></tr>
        <tr><td style="padding:8px 24px 16px;font-size:14px;color:#52606d;">{escape(reason)}</td></tr>
        <tr><td align="center" style="padding:8px 24px 28px;">
          <a href="{escape(job.product_url, quote=True)}" style="display:inline-block;background:#0f766e;color:#ffffff;text-decoration:none;padding:12px 28px;border-radius:6px;font-weight:bold;">View product</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, text, html
