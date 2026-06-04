import logging
import asyncio
import threading
import os
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from handlers.admin import get_admin_handlers
from handlers.user import (
    start_with_code_handler,
    check_sub_callback,
    movie_search_handler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


async def main():
    # Health check server
    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("Health server ishga tushdi ✅")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    for handler in get_admin_handlers():
        app.add_handler(handler)

    app.add_handler(CommandHandler("start", start_with_code_handler))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, movie_search_handler))

    logger.info("Bot ishga tushdi! ✅")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Ctrl+C bosilguncha kutadi
    stop_event = asyncio.Event()

    def _stop():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows da SIGTERM ishlamaydi
            signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(_stop))

    await stop_event.wait()

    await app.updater.stop()
    await app.stop()
    await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())