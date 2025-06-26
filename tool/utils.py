import asyncio
import os
from typing import List, Callable, Awaitable, Union, TypeVar

TOOL_DIRECTORY_PATH = os.path.dirname(os.path.abspath(__file__))
AZURERM_TO_AVM_FILE_PATH = os.path.join(TOOL_DIRECTORY_PATH, 'azurerm_to_avm.json')
DATA_DIRECTORY_PATH = os.path.join(TOOL_DIRECTORY_PATH, 'e9666d6d-96ee-4eb0-94e4-92c5f9bfca1d')
DOWNLOADED_TAR_PATH = os.path.join(DATA_DIRECTORY_PATH, 'downloaded')
DATA_FILE_NAME = 'avm_data.json'
ORIGIN_DATA_FILE_PATH = os.path.join(os.path.dirname(TOOL_DIRECTORY_PATH), 'data', 'avm_data.json')
DEBUG_DATA_FILE_PATH = os.path.join(DATA_DIRECTORY_PATH, DATA_FILE_NAME)
RULES_FILE_PATH = os.path.join(TOOL_DIRECTORY_PATH, 'rules.json')

AVM_OFFICIAL_URL = 'https://azure.github.io/Azure-Verified-Modules/indexes/terraform/tf-resource-modules/'

def raise_error(message: str):
    raise Exception(message)

T = TypeVar('T')

async def run_tasks(
    tasks: List[Union[Callable[[], T], Callable[[], Awaitable[T]], Awaitable[T]]],
    max_concurrency: int = None
) -> List[T]:
    """
    Run multiple tasks concurrently using asyncio.
    
    Args:
        tasks: A list of tasks to run. Can be:
            - Synchronous functions (will be wrapped in asyncio.to_thread)
            - Async functions (will be called)
            - Awaitable objects (like coroutines, will be awaited directly)
        max_concurrency: Maximum number of tasks to run concurrently.
                         If None, all tasks will run concurrently.
    
    Returns:
        A list of results from each task in the same order as input tasks.
    """
    async def _wrap_sync_function(func):
        """Wrap a synchronous function in asyncio.to_thread."""
        if asyncio.iscoroutinefunction(func):
            return await func()
        elif asyncio.iscoroutine(func):
            return await func
        else:
            # Assume it's a regular synchronous function
            return await asyncio.to_thread(func)
    
    # Prepare all tasks
    async_tasks = []
    for task in tasks:
        if asyncio.iscoroutine(task):
            # It's already a coroutine
            async_tasks.append(task)
        elif asyncio.iscoroutinefunction(task):
            # It's an async function, call it
            async_tasks.append(task())
        else:
            # It's a sync function, wrap it
            async_tasks.append(_wrap_sync_function(task))
    
    # If max_concurrency is set, use a semaphore to limit concurrency
    if max_concurrency:
        sem = asyncio.Semaphore(max_concurrency)
        
        async def _limited_task(task):
            async with sem:
                return await task
        
        # Wrap all tasks with the semaphore
        limited_tasks = [_limited_task(task) for task in async_tasks]
        
        # Gather all tasks
        return await asyncio.gather(*limited_tasks)
    else:
        # Run all tasks concurrently without limits
        return await asyncio.gather(*async_tasks)