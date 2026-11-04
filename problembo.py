# -*- coding: utf-8 -*-
"""Работа с API Problembo (код из исходного бота, без изменений логики)."""
import asyncio
import json
import logging
from pathlib import Path

from config import API_BASE, API_TOKEN, MODEL_ID

logger = logging.getLogger(__name__)


def get_image_extension(data: bytes):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def api_request(session, method, url, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {API_TOKEN}"

    async with session.request(method, url, headers=headers, **kwargs) as response:
        body = await response.text()
        if response.status >= 400:
            raise RuntimeError(f"Problembo HTTP {response.status}: {body}")
        try:
            return json.loads(body)
        except ValueError:
            raise RuntimeError(f"Неожиданный ответ API: {body[:500]}")


async def upload_photo(session, photo_bytes, filename):
    upload_info = await api_request(
        session,
        "POST",
        f"{API_BASE}/files/upload-url-for-src",
        json={"origFileName": filename, "fileSizeBytes": str(len(photo_bytes))},
    )
    payload = upload_info.get("payload", upload_info)
    upload_url = payload.get("uploadUrl")
    file_id = payload.get("fileId")

    if not upload_url or not file_id:
        raise RuntimeError(
            "API не вернул uploadUrl/fileId: "
            + json.dumps(upload_info, ensure_ascii=False)
        )

    async with session.put(upload_url, data=photo_bytes) as response:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(
                f"Ошибка загрузки файла: HTTP {response.status}: {body[:300]}"
            )

    await api_request(
        session, "POST", f"{API_BASE}/files/upload-complete", json={"fileId": file_id}
    )
    return file_id


async def create_task(session, file_id, prompt):
    request_data = {
        "modelId": MODEL_ID,
        "imageCount": 1,
        "prompt": prompt,
        "sourceImageFileIds": [file_id],
    }
    logger.info("Создание задачи: modelId=%s, file_id=%s", MODEL_ID, file_id)
    result = await api_request(
        session, "POST", f"{API_BASE}/image-edit/tasks", json=request_data
    )
    logger.info(
        "Ответ создания задачи: %s", json.dumps(result, ensure_ascii=False)[:1500]
    )
    return result


async def wait_result(session, task_id, timeout=240):
    deadline = asyncio.get_running_loop().time() + timeout

    while asyncio.get_running_loop().time() < deadline:
        result = await api_request(session, "GET", f"{API_BASE}/tasks/{task_id}")
        payload = result.get("payload", result)
        status = payload.get("status")
        ready = payload.get("ready")

        if ready or status == "END_SUCCESS":
            task_result = payload.get("result", {}).get("taskResult", [])
            for item in task_result:
                if isinstance(item, dict) and item.get("url"):
                    return item["url"]
            raise RuntimeError(
                "Задача завершилась, но ссылка не найдена: "
                + json.dumps(result, ensure_ascii=False)[:1500]
            )

        if status in ("END_ERROR", "FAILED", "ERROR"):
            raise RuntimeError(
                "Ошибка обработки: " + json.dumps(result, ensure_ascii=False)[:1500]
            )

        await asyncio.sleep(3)

    raise TimeoutError("Problembo не завершил задачу за отведённое время")


async def download_result(session, url, output_dir):
    async with session.get(url) as response:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(
                f"Ошибка скачивания: HTTP {response.status}: {body[:300]}"
            )
        data = await response.read()

    if not data:
        raise RuntimeError("Получен пустой файл")

    extension = get_image_extension(data)
    if extension is None:
        preview = data[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"Результат не является изображением: {preview}")

    path = Path(output_dir) / f"result{extension}"
    path.write_bytes(data)
    return str(path)
