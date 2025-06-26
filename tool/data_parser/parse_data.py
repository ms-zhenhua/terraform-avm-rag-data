import asyncio
import json
import logging
from ..utils import run_tasks
from .output_parser import parse as parse_module_outputs
from .variable_parser import VariableParser

async def parse_variables(modules: dict[str, dict]):
    tasks = []
    variable_parser = VariableParser(modules)
    for module_name in modules:
        tasks.append(variable_parser.parse(module_name))
    results = await run_tasks(tasks, 10)

    for result in results:
        for k, v in result.items():
            modules[k]['variables'] = v


async def parse_outputs(modules: dict[str, dict]):
    tasks = []
    for module in modules:
        tasks.append(lambda x=modules[module]: parse_module_outputs(x))
    results = await run_tasks(tasks, 10)

    for result in results:
        for k, v in result.items():
            modules[k]['outputs'] = v

async def parse_data(modules: dict[str, dict]):
    await parse_outputs(modules)
    await parse_variables(modules)

async def main():
    from utils import DEBUG_DATA_FILE_PATH
    with open(DEBUG_DATA_FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    await parse_data(data)

    with open(DEBUG_DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())