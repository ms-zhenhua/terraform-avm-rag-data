import asyncio
import shutil
import os
import json
import logging

from data_loader import load_data
from data_parser.parse_data import parse_data
from dependency_generator import generate as generate_dependencies
from rule_generator import generate as generate_rules
from utils import DATA_DIRECTORY_PATH, DATA_FILE_PATH

async def main():
    if os.path.exists(DATA_DIRECTORY_PATH):
        shutil.rmtree(DATA_DIRECTORY_PATH)
    
    os.makedirs(DATA_DIRECTORY_PATH, exist_ok=True)

    data = await load_data()
    await parse_data(data)
    await generate_dependencies(data)
    generate_rules(data)

    with open(DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))

    # generate questions and check list

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())