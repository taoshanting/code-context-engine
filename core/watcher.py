#!/usr/bin/env python3
"""
文件监听器 - 实时增量索引
"""

import asyncio
import time
from pathlib import Path
from typing import Set, Dict
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileChangeHandler(FileSystemEventHandler):
    """文件变化处理器"""
    
    def __init__(self, indexer, debounce_ms: int = 1000):
        self.indexer = indexer
        self.debounce_ms = debounce_ms
        self._pending_changes: Dict[str, float] = {}  # path -> timestamp
        self._lock = asyncio.Lock()
    
    def on_modified(self, event):
        """文件修改"""
        if event.is_directory:
            return
        self._schedule_reindex(event.src_path)
    
    def on_created(self, event):
        """文件创建"""
        if event.is_directory:
            return
        self._schedule_reindex(event.src_path)
    
    def on_deleted(self, event):
        """文件删除"""
        if event.is_directory:
            return
        asyncio.create_task(self._handle_delete(event.src_path))
    
    def _schedule_reindex(self, path: str):
        """调度重新索引"""
        self._pending_changes[path] = time.time()
    
    async def _process_changes(self):
        """处理挂起的变更"""
        async with self._lock:
            now = time.time()
            to_reindex = []
            
            for path, timestamp in self._pending_changes.items():
                if now - timestamp >= self.debounce_ms / 1000:
                    to_reindex.append(path)
            
            for path in to_reindex:
                del self._pending_changes[path]
            
        # 批量重新索引
        if to_reindex:
            logger.info(f"重新索引 {len(to_reindex)} 个文件")
            for path in to_reindex[:10]:  # 限制每次处理数量
                try:
                    await self.indexer.reindex_file(path)
                except Exception as e:
                    logger.error(f"重新索引失败 {path}: {e}")
    
    async def _handle_delete(self, path: str):
        """处理文件删除"""
        try:
            await self.indexer.remove_file(path)
            logger.info(f"已删除索引: {path}")
        except Exception as e:
            logger.error(f"删除索引失败 {path}: {e}")


class FileWatcher:
    """文件监听器"""
    
    def __init__(self, indexer, config):
        self.indexer = indexer
        self.config = config.watcher
        self.observer = Observer()
        self.handler = FileChangeHandler(indexer, config.watcher.debounce_ms)
        self._running = False
    
    def add_path(self, path: str):
        """添加监听路径"""
        self.observer.schedule(self.handler, path, recursive=True)
    
    def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self.observer.start()
        
        # 启动变更处理循环
        asyncio.create_task(self._change_processing_loop())
        
        logger.info("文件监听器已启动")
    
    def stop(self):
        """停止监听"""
        self._running = False
        self.observer.stop()
        self.observer.join()
        logger.info("文件监听器已停止")
    
    async def _change_processing_loop(self):
        """变更处理循环"""
        while self._running:
            await self.handler._process_changes()
            await asyncio.sleep(0.5)


async def watch_and_index(
    indexer, 
    directories: list,
    config
):
    """监听并索引"""
    if not config.watcher.enabled:
        logger.info("文件监听已禁用")
        return
    
    watcher = FileWatcher(indexer, config)
    
    for directory in directories:
        path = Path(directory)
        if path.exists():
            watcher.add_path(str(path.absolute()))
            logger.info(f"监听目录: {directory}")
    
    watcher.start()
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        watcher.stop()
