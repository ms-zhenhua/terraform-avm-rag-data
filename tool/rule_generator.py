import json
import logging
from .utils import RULES_FILE_PATH

def generate(modules: dict[str, dict]):
    with open(RULES_FILE_PATH, 'r', encoding='utf-8') as f:
        rules = json.load(f)

    for k, v in rules.items():
        if k not in modules:
            continue

        if 'rules' in v:
            modules[k]['rules'] = v['rules']
        
        for vk, vv in v.get('variables', {}).items():
            if vk not in modules[k]['variables']:
                continue

            modules[k]['variables'][vk]['rules'] = vv

def main():
    from utils import DATA_FILE_PATH
    with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    generate(data)

    with open(DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()