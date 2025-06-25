import os
import json
import logging
import hcl2
import re

from ..utils import DATA_DIRECTORY_PATH, TOOL_DIRECTORY_PATH, AZURERM_TO_AVM_FILE_PATH, raise_error

class ExampleFileParser:
    def __init__(self, modules: dict[str, dict], azurerm_to_avm: dict[str, str], module_name: str, file_path: str):
        self.modules = modules
        self.azurerm_to_avm = azurerm_to_avm
        self.module_name = module_name
        self.file_path = file_path
        self.config_modules = dict()

        #file_path = 'D:\\code\\avm\\terraform-avm-rag-data\\tool\\e9666d6d-96ee-4eb0-94e4-92c5f9bfca1d\\avm-res-desktopvirtualization-scalingplan\\examples\\default\\main.tf'
        with open(file_path, 'r', encoding='utf-8') as f:
            file_str = ExampleFileParser._refactor_example_data(f.read())
            try:
                self.parsed_data = hcl2.loads(file_str, False)
            except Exception as e:
                raise_error(f"Error parsing example file {file_path}: {e}")
        
        if 'module' not in self.parsed_data:
            return
        
        for item in self.parsed_data['module']:
            for k,v in item.items():
                self.config_modules[k] = v

    def _renew_dollar_expression(self, value: str) -> str:
        try:
            if self.module_name == 'avm-res-resources-resourcegroup':
                return '' # avoid circular reference
                            
            if value.startswith('data.'):
                value = value[value.index('.')+1:]
            
            if value.startswith('azurerm_'):
                azurerm_name = value[:value.index('.')]
                azurerm_to_avm = self.azurerm_to_avm
                if azurerm_name in azurerm_to_avm:
                    if self.module_name == azurerm_to_avm[azurerm_name]:
                        return '' # avoid circular reference
                    outputs = self.modules.get(azurerm_to_avm[azurerm_name], {}).get('outputs', [])
                    new_value = value[value.index('.', value.index('.')+1)+1:]
                    if len(new_value) == 0:
                        raise_error(f"Invalid azurerm value: {value}")
                    module_name = azurerm_to_avm[azurerm_name].replace('-', '_')

                    if 'resource' in outputs:
                        return f'module.{module_name}.resource.{new_value}'
                    if new_value == 'id' and 'resource_id' in outputs:
                        return f'module.{module_name}.resource_id'
                    
                    end_with = new_value.split('.')[-1].split('_')[-1]
                    for output in outputs:
                        if output.endswith(end_with):
                            return f'module.{module_name}.{output}'
                
                return ''
            
            if value.startswith('module.'):
                module_label = value[value.index('.')+1:value.index('.', value.index('.')+1)]
                if module_label in self.config_modules:
                    source = self.config_modules[module_label].get('source', '')

                    if source == 'Azure/avm-utl-sku-finder/azapi' and value.endswith('.sku'):
                        return "Standard_D2ds_v5"
                    if source.find('avm-res-') == -1:
                        return ''
                    
                    if source == 'Azure/avm-res-keyvault-vault/azurerm' and value.endswith('resource.id'):
                        value = value.replace('resource.id', 'resource_id')

                    module_name = source[source.index('avm-res-'):source.index('/', source.index('avm-res-')+1)].replace('-', '_')
                    new_value = value[len('module.'):]
                    return f'module.{module_name}.{new_value[new_value.index(".")+1:]}'
                else:
                    return ''
            
            if re.match(r'^[a-zA-Z0-9]+\(', value):
                return ''
                
            raise_error(f"Unsupported value format: {value}")
        except Exception as e:
            raise_error(f"Error parsing string value {value}: {e}")

    def _parse_example_string(self, value: str):
        if value.startswith('${toset('):
            new_value = value[len('${toset('):-len(')}')]
            try:
                return self._parse_example_data(json.loads(new_value))
            except Exception as e:
                logging.error(f"Error parsing JSON string value {value}: {e}")
                return ''

        if value.count('\n') > 0:
            return ''
        if value.startswith('${({'):
            new_value = value[len('${('): -len(')}')].replace("'", '"')
            try:
                return self._parse_example_data(json.loads(new_value))
            except Exception as e:
                raise_error(f"Error parsing JSON string value {new_value}: {e}")
        
        if value.find('[*]') != -1:
            value = [value.replace('[*]', '')]
            return self._parse_example_data(value)
            
        if value.find('${') != -1:
            if any(value.find(word) != -1 for word in ['random_','module.naming', 'tls_private_key.', 'azurerm_client_config.', 'azuread_client_config.', 'azapi_client_config.', 'local.', 'http.', 'var.', 'azapi_resource.', 'each.', 'azuredevops_project.']):
                return ''
        
            if value.find('data.') == -1 and value.find('azurerm_') == -1 and value.find('module.') == -1:
                return ''
        else:
            return value.strip().strip('"').strip("'")
        
        result = ''
        while len(value) > 0:
            start = value.find('${')
            if start == -1:
                result += value
                break

            result += value[:start]
            end = value.find('}', start)
            if end == -1:
                raise_error(f"Unmatched dollar expression in value: {value}")
            dollar_expression = value[start+len('${'):end]
            result += self._renew_dollar_expression(dollar_expression)
            value = value[end+len('}'):]

        return result
    
    def _parse_example_int(self, value: int) -> int:
        return value

    def _parse_example_bool(self, value: bool) -> bool:
        return value

    def _parse_example_float(self, value: float) -> float:
        return value

    def _parse_example_dict(self, data: dict) -> dict:
        result = dict()
        for k, v in data.items():
            result[k] = self._parse_example_data(v)
        
        return result

    def _parse_example_list(self, data: list) -> list:
        result = list()
        for item in data:
            result.append(self._parse_example_data(item))
        
        return result
    
    def _parse_example_data(self, data):
        data_type = type(data)
        if data_type == str:
            return self._parse_example_string(data)
        elif data_type == int:
            return self._parse_example_int(data)
        elif data_type == float:
            return self._parse_example_float(data)
        elif data_type == bool:
            return self._parse_example_bool(data)           
        elif data_type == dict:
            return self._parse_example_dict(data)
        elif data_type == list:
            return self._parse_example_list(data)
        elif data_type == type(None):
            return None
        else:
            raise raise_error(f"Unsupported data type {data_type}")
    
    def parse(self) -> dict[str, dict]:
        try:
            result = dict()
            if 'module' not in self.parsed_data:
                return result

            sources = ['../..', '../../', self.modules[self.module_name]['source']]
            for item in self.parsed_data['module']:
                for k,v in item.items():
                    if v.get('source', '') in sources:
                        del v['source']
                        if 'depends_on' in v:
                            del v['depends_on']
                        result[k] = self._parse_example_data(v)
            return result
        except Exception as e:
            raise raise_error(f"Error reading example file {self.file_path}: {e}")  

    @staticmethod
    def _refactor_example_data(data: str) -> str:
        lines = [item.rstrip() for item in data.splitlines()]
        return '\n'.join(lines)

class ExampleParser:
    def __init__(self, modules: dict[str, dict], azurerm_to_avm: dict[str, str], module_name: str):
        self.modules = modules
        self.azurerm_to_avm = azurerm_to_avm
        self.module_name = module_name

    def parse(self, module_name: str) -> dict:
        example_directory = os.path.join(DATA_DIRECTORY_PATH, module_name, 'examples')
        entries = os.listdir(example_directory)
        example_data = {}
        for entry in entries:
            entry_path = os.path.join(example_directory, entry)
            if not os.path.isdir(entry_path):
                continue

            file_path = os.path.join(entry_path, "main.tf")
            if not os.path.exists(file_path):
                continue
            
            try:
                example_file_parser = ExampleFileParser(self.modules, self.azurerm_to_avm, module_name, file_path)     
                parsed_data = example_file_parser.parse()
                for k, v in parsed_data.items():
                    example_data[f'{file_path}.{k}'] = v
            except Exception as e:
                raise_error(f"Error parsing example file {file_path}: {e}")
            
            return example_data