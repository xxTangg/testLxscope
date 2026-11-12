"""guard —— 网络隔离与脱敏日志的统一封装（FT-05 / NFR-02）。"""
from __future__ import annotations

import logging
import socket
from typing import NoReturn


class NetworkDisabledError(RuntimeError):
    """在本地隔离模式下发起出站连接时抛出。"""


def block_network() -> None:
    """禁用出站网络：任何 socket.connect 直接抛错。幂等。"""
    def _blocked(*_args: object, **_kwargs: object) -> NoReturn:
        raise NetworkDisabledError("本地隔离模式：已禁用网络访问")

    socket.socket.connect = _blocked          # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked        # type: ignore[method-assign]


def get_logger(name: str) -> logging.Logger:
    """返回仅记录状态计数/错误码的 logger（不得传入交易明细）。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
