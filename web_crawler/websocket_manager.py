"""
WebSocket communication management
"""

import asyncio
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Handle WebSocket updates safely"""
    
    @staticmethod
    def send_update(client_id: Optional[str], manager, message: Dict) -> None:
        """Send WebSocket update if available"""
        if not manager or not client_id:
            return
        
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                asyncio.create_task,
                manager.send_message(client_id, message)
            )
        except RuntimeError:
            logger.debug("No running event loop for WebSocket update")
        except Exception as e:
            logger.warning(f"WebSocket update failed: {e}")