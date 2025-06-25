import os
import logging
import hcl2
from utils import DATA_DIRECTORY_PATH, raise_error

def parse(module: dict) -> dict:
    logging.info(f"Parsing outputs for module: {module['module_name']}")
    try:
        outputs = []
        with open(os.path.join(DATA_DIRECTORY_PATH, module['module_name'], "outputs.tf"), 'r', encoding='utf-8') as f:
            outputs_data = hcl2.loads(f.read(), False).get('output', [])
            for output_data in outputs_data:
                for output_name in output_data:
                    outputs.append(output_name)

        return {module['module_name']: outputs}
    except Exception as e:
        raise_error(f"Error parsing outputs for module {module['module_name']}: {e}")