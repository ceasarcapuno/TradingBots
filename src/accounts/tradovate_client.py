"""
Tradovate API Client

Handles authentication, order placement, position management, and account
data retrieval for Tradovate/Apex accounts.

API docs: https://api.tradovate.com/
WebSocket: Real-time data and order updates

This client manages a single Tradovate account. The AccountManager
maintains one client per account.
"""

import asyncio
import structlog
import httpx
from datetime import datetime, timedelta
from typing import Optional

from src.core.models import (
    Order, OrderSide, OrderType, OrderStatus, Position,
    TradingSignal, SignalAction, AccountState,
)
from config.settings import TradovateConfig

logger = structlog.get_logger()


class TradovateClient:
    """
    Async HTTP/WebSocket client for a single Tradovate account.
    """

    def __init__(self, account_id: str, config: TradovateConfig,
                 credentials: dict = None):
        self.account_id = account_id
        self.config = config
        self._credentials = credentials or {}

        base_url = config.demo_api_url if config.use_demo else config.api_url
        self._base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=config.request_timeout,
        )

        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._tradovate_account_id: Optional[int] = None  # Numeric account ID

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """
        Authenticate with Tradovate API and obtain access token.
        """
        try:
            payload = {
                "name": self._credentials.get("username", self.config.username),
                "password": self._credentials.get("password", self.config.password),
                "appId": self.config.app_id,
                "appVersion": self.config.app_version,
            }
            if self.config.cid:
                payload["cid"] = self.config.cid
            if self.config.sec:
                payload["sec"] = self.config.sec

            response = await self._http.post("/auth/accesstokenrequest", json=payload)
            response.raise_for_status()
            data = response.json()

            self._access_token = data.get("accessToken")
            expiry_str = data.get("expirationTime", "")
            if expiry_str:
                self._token_expiry = datetime.fromisoformat(
                    expiry_str.replace("Z", "+00:00")
                )

            self._http.headers["Authorization"] = f"Bearer {self._access_token}"

            # Get account spec ID
            await self._resolve_account_id()

            logger.info("tradovate_authenticated",
                        account_id=self.account_id,
                        tradovate_id=self._tradovate_account_id)
            return True

        except httpx.HTTPStatusError as e:
            logger.error("tradovate_auth_failed",
                         account_id=self.account_id,
                         status=e.response.status_code,
                         detail=e.response.text)
            return False
        except Exception as e:
            logger.error("tradovate_auth_error",
                         account_id=self.account_id,
                         error=str(e))
            return False

    async def _resolve_account_id(self):
        """Get the numeric Tradovate account ID for order placement."""
        response = await self._http.get("/account/list")
        response.raise_for_status()
        accounts = response.json()
        if accounts:
            # Use the first account (or match by name if multiple)
            self._tradovate_account_id = accounts[0].get("id")

    async def _ensure_authenticated(self):
        """Re-authenticate if token is expired or missing."""
        if not self._access_token or (
            self._token_expiry and datetime.utcnow() >= self._token_expiry
        ):
            await self.authenticate()

    # -------------------------------------------------------------------------
    # Order Placement
    # -------------------------------------------------------------------------

    async def place_order(self, signal: TradingSignal,
                          account: AccountState) -> Optional[Order]:
        """
        Place an order on Tradovate based on a trading signal.
        Returns the Order object with fill status.
        """
        await self._ensure_authenticated()

        if not self._tradovate_account_id:
            logger.error("no_tradovate_account_id", account_id=self.account_id)
            return None

        order = self._build_order(signal, account)

        try:
            payload = self._order_to_tradovate_payload(order)
            endpoint = self._get_order_endpoint(signal.action)

            response = await self._http.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()

            order.order_id = str(data.get("orderId", ""))
            order.status = self._map_order_status(data.get("ordStatus", ""))
            if data.get("avgPx"):
                order.filled_price = float(data["avgPx"])
                order.filled_quantity = int(data.get("cumQty", 0))

            logger.info("order_placed",
                        account_id=self.account_id,
                        order_id=order.order_id,
                        status=order.status.value,
                        instrument=order.instrument)
            return order

        except httpx.HTTPStatusError as e:
            logger.error("order_placement_failed",
                         account_id=self.account_id,
                         status=e.response.status_code,
                         detail=e.response.text)
            order.status = OrderStatus.REJECTED
            return order
        except Exception as e:
            logger.error("order_placement_error",
                         account_id=self.account_id,
                         error=str(e))
            return None

    async def place_bracket_order(self, signal: TradingSignal,
                                  account: AccountState) -> Optional[Order]:
        """
        Place a bracket order (entry + stop loss + take profit) atomically.
        This is the preferred method for risk-managed entries.
        """
        await self._ensure_authenticated()

        if not self._tradovate_account_id:
            return None

        order = self._build_order(signal, account)

        try:
            payload = {
                "accountSpec": self._credentials.get("username", ""),
                "accountId": self._tradovate_account_id,
                "action": "Buy" if signal.action in (
                    SignalAction.LONG_ENTRY,) else "Sell",
                "symbol": self._resolve_symbol(signal.instrument),
                "orderQty": order.quantity,
                "orderType": "Market",
                "isAutomated": True,
            }

            # Add bracket legs
            bracket = {"qty": order.quantity}
            if signal.stop_loss:
                bracket["profitTarget"] = abs(signal.take_profit - signal.price) if signal.take_profit else 0
                bracket["stopLoss"] = abs(signal.price - signal.stop_loss)
                bracket["trailingStop"] = False

            payload["bracket"] = bracket

            response = await self._http.post(
                "/order/placeOrder", json=payload
            )
            response.raise_for_status()
            data = response.json()

            order.order_id = str(data.get("orderId", ""))
            order.status = self._map_order_status(data.get("ordStatus", ""))

            return order

        except Exception as e:
            logger.error("bracket_order_failed",
                         account_id=self.account_id,
                         error=str(e))
            return None

    async def flatten_all(self) -> bool:
        """Close all open positions for this account immediately."""
        await self._ensure_authenticated()

        if not self._tradovate_account_id:
            return False

        try:
            response = await self._http.post(
                "/order/liquidatePosition",
                json={"accountId": self._tradovate_account_id}
            )
            response.raise_for_status()
            logger.info("positions_flattened", account_id=self.account_id)
            return True
        except Exception as e:
            logger.error("flatten_failed",
                         account_id=self.account_id,
                         error=str(e))
            return False

    async def cancel_all_orders(self) -> bool:
        """Cancel all pending orders."""
        await self._ensure_authenticated()

        try:
            response = await self._http.post(
                "/order/cancelAllOrders",
                json={"accountId": self._tradovate_account_id}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error("cancel_all_failed",
                         account_id=self.account_id,
                         error=str(e))
            return False

    # -------------------------------------------------------------------------
    # Account Data
    # -------------------------------------------------------------------------

    async def get_positions(self) -> list[Position]:
        """Get all open positions for this account."""
        await self._ensure_authenticated()

        try:
            response = await self._http.get("/position/list")
            response.raise_for_status()
            positions = []
            for pos_data in response.json():
                if pos_data.get("netPos", 0) != 0:
                    positions.append(Position(
                        account_id=self.account_id,
                        instrument=pos_data.get("contractId", ""),
                        side=OrderSide.BUY if pos_data["netPos"] > 0 else OrderSide.SELL,
                        quantity=abs(pos_data["netPos"]),
                        entry_price=pos_data.get("netPrice", 0),
                        current_price=pos_data.get("netPrice", 0),
                    ))
            return positions
        except Exception as e:
            logger.error("get_positions_failed",
                         account_id=self.account_id,
                         error=str(e))
            return []

    async def get_account_balance(self) -> dict:
        """Get current account balance and margin info."""
        await self._ensure_authenticated()

        try:
            response = await self._http.get(
                f"/cashBalance/getCashBalanceSnapshot",
                params={"accountId": self._tradovate_account_id}
            )
            response.raise_for_status()
            data = response.json()
            return {
                "balance": data.get("totalCashValue", 0),
                "realized_pnl": data.get("realizedPnL", 0),
                "unrealized_pnl": data.get("openPnL", 0),
            }
        except Exception as e:
            logger.error("get_balance_failed",
                         account_id=self.account_id,
                         error=str(e))
            return {}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_order(self, signal: TradingSignal,
                     account: AccountState) -> Order:
        action_side_map = {
            SignalAction.LONG_ENTRY: OrderSide.BUY,
            SignalAction.SHORT_ENTRY: OrderSide.SELL,
            SignalAction.EXIT_LONG: OrderSide.SELL,
            SignalAction.EXIT_SHORT: OrderSide.BUY,
            SignalAction.FLATTEN: OrderSide.SELL,  # Handled separately
        }
        return Order(
            account_id=self.account_id,
            instrument=signal.instrument,
            side=action_side_map.get(signal.action, OrderSide.BUY),
            order_type=OrderType.MARKET,
            quantity=signal.contracts,
            price=signal.price,
            stop_price=signal.stop_loss,
            signal_id=signal.signal_id,
        )

    def _order_to_tradovate_payload(self, order: Order) -> dict:
        return {
            "accountSpec": self._credentials.get("username", ""),
            "accountId": self._tradovate_account_id,
            "action": order.side.value,
            "symbol": self._resolve_symbol(order.instrument),
            "orderQty": order.quantity,
            "orderType": order.order_type.value,
            "isAutomated": True,
        }

    def _get_order_endpoint(self, action: SignalAction) -> str:
        if action == SignalAction.FLATTEN:
            return "/order/liquidatePosition"
        return "/order/placeOrder"

    def _resolve_symbol(self, instrument: str) -> str:
        """Convert generic instrument name to Tradovate contract symbol."""
        # In production, this needs to resolve the current front-month contract
        # e.g., "ES" → "ESH5" (March 2025)
        return instrument

    def _map_order_status(self, status: str) -> OrderStatus:
        mapping = {
            "PendingNew": OrderStatus.PENDING,
            "New": OrderStatus.SUBMITTED,
            "Filled": OrderStatus.FILLED,
            "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "Rejected": OrderStatus.REJECTED,
        }
        return mapping.get(status, OrderStatus.PENDING)

    async def close(self):
        """Clean up HTTP client."""
        await self._http.aclose()
