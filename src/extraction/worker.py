import asyncio
import logging
import multiprocessing as mp

from fastapi.concurrency import run_in_threadpool

from src.extraction.exceptions import ExtractionError

logger = logging.getLogger(__name__)


def serve(connection, settings):
    try:
        from src.extraction.service import Converter

        converter = Converter(settings)
        connection.send(("ready", None))
        while True:
            args = connection.recv()
            try:
                connection.send(("ok", converter.extract(*args)))
            except ExtractionError as exc:
                connection.send(("error", (exc.status, exc.detail)))
            except Exception:
                logger.exception("Conversion failed")
                connection.send(("error", (500, "Conversion failed")))
    except Exception:
        logger.exception("Worker stopped")
    finally:
        connection.close()


class Worker:
    def __init__(self, settings):
        self.settings = settings
        self.ready = False
        self.busy = False
        self.process = None

    async def start(self):
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=serve, args=(child, self.settings), daemon=True
        )
        self.process.start()
        child.close()
        try:
            status, _ = await self.receive(self.settings.startup_timeout)
            self.ready = status == "ready"
        except (ExtractionError, EOFError, OSError):
            await self.close()
            logger.error("Worker initialization failed; readiness is false")

    async def receive(self, timeout):
        if not await run_in_threadpool(self.connection.poll, timeout):
            raise ExtractionError(504, "Extraction worker deadline exceeded")
        return await run_in_threadpool(self.connection.recv)

    async def close(self):
        self.ready = False
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            await run_in_threadpool(self.process.join, 5)
            if self.process.is_alive():
                self.process.kill()
                await run_in_threadpool(self.process.join)
            self.connection.close()

    async def extract(self, *args):
        if self.busy or not self.ready:
            raise ExtractionError(503, "Extraction worker unavailable")
        self.busy = True
        try:
            await run_in_threadpool(self.connection.send, args)
            status, value = await self.receive(self.settings.extraction_timeout)
            if status == "error":
                raise ExtractionError(*value)
            return value
        except (EOFError, OSError) as exc:
            await self.close()
            await self.start()
            raise ExtractionError(503, "Extraction worker crashed") from exc
        except (ExtractionError, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError) or exc.status == 504:
                await self.close()
                await self.start()
            raise
        finally:
            self.busy = False
