import asyncio
import os
import json
import logging
import hcl2
from asyncio.subprocess import Process
from ..utils import DATA_DIRECTORY_PATH, AZURERM_TO_AVM_FILE_PATH, raise_error
from .example_parser import ExampleParser
from abc import ABC, abstractmethod
import hashlib
import time
import shutil


class Node(ABC):
    def __init__(self, parent: 'Node'):
        self.parent = parent
        self.id = hashlib.md5(f"{time.time():.9f}".encode())

    @abstractmethod
    def to_module(self)-> str:
        pass

class ValueNode(Node):
    def __init__(self, parent: Node):
        super().__init__(parent)
    
    def set_value(self, value):
        raise NotImplementedError("set_value method must be implemented in subclasses")

class ComplexValueNode(ValueNode):
    def __init__(self, parent: Node, schema: str):
        super().__init__(parent)
        self.schema = schema        

class PrimitiveValueNode(ValueNode):
    def __init__(self, parent: Node, default_value: str = ''):
        super().__init__(parent)
        self.default_value = default_value.strip('"').strip("'")
        self.possible_values: set[str] = set()

class StringValueNode(PrimitiveValueNode):
    def __init__(self, parent, default_value: str = ''):
        super().__init__(parent, default_value)
    
    def set_value(self, value):
        if not valid_value(value):
            return
        
        value = str(value).strip().strip('"').strip("'")
        if len(value) == 0:
            return
        if not value.startswith('module.') and value.find('.') != -1:
            print(f"Warning: String value {value} contains a dot, which may not be supported in AVM.")
        
        self.default_value = value
        self.possible_values.add(value)

    def to_module(self) -> str:
        default_value = self.default_value.strip('"').strip("'")
        if default_value.startswith('module.'):
            if self.parent and isinstance(self.parent, AttributeNode) and self.parent.required:
                return default_value
            else:
                return '""'
        
        if default_value and default_value != 'null':
            return f'"{default_value}"'  
        
        if self.parent and isinstance(self.parent, AttributeNode) and self.parent.required:       
            if self.parent.name == 'name':
                return '"example1"'
            if self.parent.name == 'location':
                return '"westeurope"'
            if self.parent.name == 'resource_group_name':
                return 'module.avm_res_resources_resourcegroup.resource.name'
            if self.parent.name == 'resource_group_resource_id':
                return 'module.avm_res_resources_resourcegroup.resource.id'
            if self.parent.name.endswith('ip_address_resource_name'):
                return 'module.avm_res_network_publicipaddress.name'
            if self.parent.name.endswith('ip_address_resource_id'):
                return 'module.avm_res_network_publicipaddress.resource_id'
            if self.parent.name in ['tenant_id', 'subscription_id', 'client_id', 'principal_id']:
                return '"00000000-0000-0000-0000-000000000000"'
            if self.parent.name == 'zone':
                return '"1"'
            if self.parent.name.find('email') != -1:
                return '"example@example.com"'
            
            parent_parent = get_parrent_attribute_node(self.parent)
            parent_label = f'_{parent_parent.name}' if parent_parent else ''
            return f'var.string{parent_label}_{self.parent.name}'

        return '""'

class AnyValueNode(StringValueNode):
    pass

class UnknownValueNode(StringValueNode):
    pass

class NumberValueNode(PrimitiveValueNode):
    def __init__(self, parent, default_value: str = ''):
        super().__init__(parent, default_value)

    def set_value(self, value):
        if not valid_value(value):
            return
        
        value = str(value).strip().strip('"').strip("'")
        if len(value) == 0:
            return
        
        if value.startswith('module.'):
            self.default_value = value
            return
        
        try:
            float_value = float(value)
            self.default_value = str(float_value)
            return
        except ValueError:
            raise_error(f"Expected a number for number value, got {type(value)}: {value}")

    def to_module(self) -> str:
        default_value = self.default_value.strip('"').strip("'")
        if default_value and default_value != 'null':
            return default_value
        
        return '0'

class BoolValueNode(PrimitiveValueNode):
    def __init__(self, parent, default_value: str = ''):
        super().__init__(parent, default_value)
    
    def set_value(self, value):
        if not valid_value(value):
            return
        
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ['true', 'false']:
                self.default_value = value
                return
            
            if value.startswith('module.'):
                self.default_value = value
                return
        
        if isinstance(value, bool):
            self.default_value = str(value).lower()
            return
            
        raise_error(f"Expected a boolean for bool value, got {type(value)}")

    def to_module(self) -> str:
        default_value = self.default_value.strip('"').strip("'")
        return default_value if default_value and default_value != 'null' else 'false'

class AttributeNode(Node):
    def __init__(self, name: str, parent: Node, required: bool):
        super().__init__(parent)
        self.name = name
        self.parent = parent
        self.required = required
        self.value_node = None
        self.Note : str = ''
        self.rely_on: set[str] = set()
    
    def set_value_node(self, value_node: ValueNode):
        self.value_node = value_node

    def set_value(self, value):
        self.value_node.set_value(value)
    
    def to_module(self)-> str:
        required_str = 'Required' if self.required else 'Optional'
        parent_attribute_node = get_parrent_attribute_node(self)
        parent_name = f"`{parent_attribute_node.name}`" if parent_attribute_node else 'module'
        
        return f'# `{self.name}` is {required_str} in {parent_name}\n{self.name} = {self.value_node.to_module()}\n'

class SetValueNode(ComplexValueNode):
    def __init__(self, parent: Node, schema: str):
        super().__init__(parent, schema)
        self.children = []

    def set_value(self, value):
        if not valid_value(value):
            return
        
        if len(self.children) == 0:
            self.children.append(create_value_node(self, self.schema[self.schema.index('(')+1:self.schema.rindex(')')]))

        if isinstance(value, list):
            for item in value:
                self.children[0].set_value(item)
        else:
            return

    def to_module(self) -> str:
        if len(self.children) == 0:
            child_node = create_value_node(self, self.schema[self.schema.index('(')+1:self.schema.rindex(')')])
            if isinstance(child_node, PrimitiveValueNode):
                return '[]'
            
            self.children.append(child_node)

        return f'[{", ".join(child.to_module() for child in self.children)}]'

class ListValueNode(SetValueNode):
    pass

class MapValueNode(ComplexValueNode):
    def __init__(self, parent: Node, schema: str):
        super().__init__(parent, schema)
        self.children = {}

    def set_value(self, value):
        if not valid_value(value):
            return
        
        if isinstance(value, dict):
            for k, v in value.items():
                if len(self.children) == 0:
                    child = create_value_node(self, self.schema[self.schema.index('(')+1:self.schema.rindex(')')])
                    self.children[k] = child
                    key = k
                else:
                    key = list(self.children.keys())[0]
                    
                self.children[key].set_value(v)
        else:
            return

    def to_module(self) -> str:
        children = self.children
        if len(children) == 0:
            children = {"example_key": create_value_node(self, self.schema[self.schema.index('(')+1:self.schema.rindex(')')])}
        result = "{\n"
        for k, v in children.items():
            if k.find('.') != -1:
                k = f'"{k}"'
            result += f'  {k} = {v.to_module()}\n'
        return result + '}\n'
    
class ObjectValueNode(ComplexValueNode):
    def __init__(self, parent: Node, schema: str):
        super().__init__(parent, schema)
        self.children = self.create_children_nodes(schema)
    
    def decode_schema(self, schema: str) -> list[tuple[str, str]]:
        result = []
        schema = schema[len('object('): -len(')')]
        start = len('{')
        while start < len(schema):
            end = parse_object_key(schema, start)
            if end == -1:
                raise_error(f"parse_key error at position {start}: {schema}")
            
            key = schema[start:end].strip().strip('"')
            start = end + len(': ')
            end = parse_object_value(schema, start)
            if end == -1:
                raise_error(f"parse_value error at position {start}: {schema}")
            value = schema[start:end].strip().strip('"')
            result.append([key, value])

            if end >= len(schema) and schema[end] == '}':
                break

            start = end + len(', ')

        return result

    def decode_attribute_schema(self, attribute_schema: str) -> tuple[str, str]:
        if any(attribute_schema.startswith(pt) for pt in primitive_types()):
            split_values = attribute_schema.split(',')
            schema = split_values[0].strip()
            default_value = split_values[1].strip() if len(split_values) > 1 else ''
            return schema, default_value
        elif attribute_schema.startswith('set(') or attribute_schema.startswith('list('):
            if any(attribute_schema[attribute_schema.index('(')+1:].startswith(pt) for pt in primitive_types()):
                return attribute_schema[:attribute_schema.index(')')+1], ''
            else:
                return attribute_schema[:attribute_schema.rindex(')')+1], ''
        elif attribute_schema.startswith('map('):
            if any(attribute_schema[attribute_schema.index('(')+1:].startswith(pt) for pt in primitive_types()):
                return attribute_schema[:attribute_schema.index(')')+1], ''
            else:
                return attribute_schema[:attribute_schema.rindex(')')+1], ''
        elif attribute_schema.startswith('object('):
            return attribute_schema[:attribute_schema.rindex('"})')+3], ''
        
        raise_error(f"Unsupported attribute schema: {attribute_schema}")


    def create_children_nodes(self, schema: str) -> list[AttributeNode]:
        required_children = []
        optional_children = []
        attributes = self.decode_schema(schema)
        for name, value in attributes:
            try:
                name = name.strip().strip('"')
                value = value.strip().strip('"')
                if value.startswith('${'):
                    value = value[len('${'):value.rindex('}')]
                required = not value.startswith('optional(')
                if not required:
                    value = value[len('optional('):value.rindex(')')]
                value_schema, default_value = self.decode_attribute_schema(value)  
                attribute_node = AttributeNode(name=name, parent=self, required = required)
                attribute_node.set_value_node(create_value_node(attribute_node, value_schema, default_value))
                if required:
                    required_children.append(attribute_node)
                else:
                    optional_children.append(attribute_node)
            except Exception as e:
                raise_error(f"Error creating child node for {name}: {e}")
        return required_children + optional_children
            
    def set_value(self, value):
        if not valid_value(value):
            return
        
        if not isinstance(value, dict):
            raise_error(f"Expected a dict for object value, got {type(value)}")
        
        for child in self.children:
            if child.name in value:
                child.set_value(value[child.name])
            else:
                if child.required:
                    raise_error(f"Required attribute {child.name} is missing in the provided value.")

    def to_module(self) -> str:
        result = "{\n"
        for child in self.children:
            result += f'  {child.to_module()}'
        return result + '}\n'

class VariableNode(AttributeNode):
    def __init__(self, name: str, parent: Node, required: bool, description: str):
        super().__init__(name, parent, required)
        self.description = description

class RootNode(Node):
    def __init__(self, name : str, source: str): 
        super().__init__(None)
        self.children: list[VariableNode] = []
        self.name = name
        self.source = source

    def decode_variables(self, data: dict):
        for k, v in data.items():
            node = create_variable_node(k, v, self)
            self.children.append(node)
                

    def to_module(self)-> str:
        result = f'module "{self.name}" {{\n'
        result += f'source   = "{self.source}"\n'
        try:
            for child in self.children:
                result += child.to_module()
        except Exception as e:
            raise_error(f"Error generating module for {child.name}: {e}")
        result += '}\n'
        return result
    
    async def generate_context_data(self, example_data: dict) -> dict:
        result = dict()
        for k, data in example_data.items():
            for child in self.children:
                if child.name in data:
                    try:
                        child.set_value(data[child.name])
                    except Exception as e:
                        raise_error(f"Error setting value for {child.name}: {e}")

        temp_dir = os.path.join(DATA_DIRECTORY_PATH, self.name, 'dbc941d2-91d5-4474-94f1-949dab0e69a5')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)
        for child in self.children:
            try:
                file_path = os.path.join(temp_dir, f"{child.name}.tf")
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(child.to_module())
            except Exception as e:
                raise_error(f"Error generating schema for {child.name}: {e}")
        
        await run_terraform_command(f"terraform -chdir={temp_dir} fmt")
        
        required_variables = []
        optional_variables = []
        for child in self.children:
            with open(os.path.join(temp_dir, f"{child.name}.tf"), "r", encoding="utf-8") as f:
                content = f.read()
            
            if child.required:
                required_variables.append({
                    'name': child.name,
                    'required': True,
                    'description': child.description,
                    'schema': content
                })
            else:
                optional_variables.append({
                    'name': child.name,
                    'required': False,
                    'description': child.description,
                    'schema': content
                })

        shutil.rmtree(temp_dir)

        required_variables.sort(key=lambda x: x['schema'].count('\n'))
        NAME_PRIORITY = 0
        LOCATION_PRIORITY = 1
        current_priority = 2

        for item in required_variables:
            variable_name = item['name']
            if variable_name.lower() == 'name':
                priority = NAME_PRIORITY
            elif variable_name.lower() == 'location':
                priority = LOCATION_PRIORITY
            else:
                priority = current_priority
                current_priority += 1

            result[variable_name] = {
                "required": item['required'],
                "description": item['description'],
                "priority": priority,
                "schema": item['schema'],
            }
        
        optional_variables.sort(key=lambda x: x['schema'].count('\n'))
        current_priority = 10000
        for item in optional_variables:
            variable_name = item['name']
            priority = current_priority
            current_priority += 1

            result[variable_name] = {
                "required": item['required'],
                "description": item['description'],
                "priority": priority,
                "schema": item['schema'],
            }
        
        return result

def get_parrent_attribute_node(node: Node) -> AttributeNode:
    current_node = node
    while current_node.parent is not None:
        if isinstance(current_node.parent, AttributeNode):
            return current_node.parent
        current_node = current_node.parent
    
    return None

def valid_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return len(value.strip()) > 0
    return True

def value_error(message: str) -> None:
    raise ValueError(message)

def parse_object_key(schema: str, start: int) -> int:
        current = start + len('"') 
        while current < len(schema) and schema[current] != '"':
            current += 1
        
        return current + 1
    
def parse_primitive_type_expression(data_type: str, schema: str, start: int) -> int:
    current = start + len(data_type)
    if schema[current] == ',':
        while schema[current] != ')':
            current += 1
        return current
    elif schema[current] == ')' or schema[current] == '"':
        return current

    value_error(f"Unsupported {data_type} expression format at position {current}: {schema}")

def parse_complex_expression(data_type: str, schema: str, start: int) -> int:
    current = start + len(data_type + '(')
    current = parse_expression(schema, current)
    return current + len(')')    

def parse_object_expression(schema: str, start: int) -> int:
    current = start + len('object({')

    while current < len(schema):
        current = parse_object_key(schema, current)
        current += len(': ')
        current = parse_object_value(schema, current)
        if current < len(schema) and schema[current] == '}':
            current += len('}')
            break
        current += len(', ')

    return current + len(')')

def skip_default(schema: str, start: int) -> int:
    mark = schema[start]
    if mark == '{':
        start_char = '{'
        end_char = '}'
    elif mark == '[':
        start_char = '['
        end_char = ']'
    elif schema[start:].startswith('null'):
        return start + len('null')
    else:
        value_error(f"Unsupported default value format at position {start}: {schema}")
    
    times = 1

    current = start + 1
    while current < len(schema):
        if times == 0:
            break
        if schema[current] == start_char:
            times += 1
        elif schema[current] == end_char:
            times -= 1
        current += 1

    return current


def parse_optional_expression(schema: str, start: int) -> int:
    current = start + len('optional(')
    current = parse_expression(schema, current)
    if schema[current] == ',':
        current += len(', ')
        current = skip_default(schema, current)

    return current + len(')')

def parse_dollar_expression(schema: str, start: int) -> int:
    current = start + len('${')
    current = parse_expression(schema, current)
    return current + len('}')

def parse_expression(schema: str, start: int) -> int:
    current = start
    if schema[current:].startswith('${'):
        current = parse_dollar_expression(schema, current)
    elif schema[current:].startswith('optional'):
        current = parse_optional_expression(schema, current)
    elif schema[current:].startswith('bool'):
        current = parse_primitive_type_expression('bool', schema, current)
    elif schema[current:].startswith('string'):
        current = parse_primitive_type_expression('string', schema, current)
    elif schema[current:].startswith('number'):
        current = parse_primitive_type_expression('number', schema, current)
    elif schema[current:].startswith('any'):
        current += len('any')
    elif schema[current:].startswith('unknown'):
        current = parse_primitive_type_expression('unknown', schema, current)
    elif schema[current:].startswith('list'):
        current = parse_complex_expression('list', schema, current)
    elif schema[current:].startswith('set'):
        current = parse_complex_expression('set', schema, current)
    elif schema[current:].startswith('map'):
        current = parse_complex_expression('map', schema, current)
    elif schema[current:].startswith('object'):
        current = parse_object_expression(schema, current)
    else:
        value_error(f"Unsupported optional expression format at position {current}: {schema}")

    return current

def parse_object_value(schema: str, start: int) -> int:
    current = start + len('"')
    current = parse_expression(schema, current)
    return current + len('"')

def create_primitive_node(parent: Node, data_type: str, default_value = '') -> PrimitiveValueNode:
    if data_type == 'string':
        return StringValueNode(parent, default_value)
    elif data_type == 'number':
        return NumberValueNode(parent, default_value)
    elif data_type == 'bool':
        return BoolValueNode(parent, default_value)
    elif data_type == 'any':
        return AnyValueNode(parent, default_value)
    elif data_type == 'unknown':
        return UnknownValueNode(parent, default_value)
    
    value_error(f"Unsupported primitive type: {data_type}")

def primitive_types() -> list[str]:
    return ['string', 'number', 'bool', 'any', 'unknown']

def create_value_node(parent: Node, schema : str, default_value = '') -> ValueNode:
    if schema.startswith('${'):
        schema = schema[2:-1]
    
    if schema.startswith('set('):
        return SetValueNode(parent, schema)
    elif schema.startswith('list('):
        return ListValueNode(parent, schema)
    elif schema.startswith('object('):
        return ObjectValueNode(parent, schema)
    elif schema.startswith('map('):
        return MapValueNode(parent, schema)
    elif schema in primitive_types():
        return create_primitive_node(parent, schema, default_value)
    
    value_error(f"Unsupported data type: {schema}")

def create_variable_node(name: str, data: dict, parent: RootNode) -> ValueNode:
    try:   
        variable_node = VariableNode(
            name=name,
            parent=parent,
            required=('default' not in data) and (not data.get('nullable', False)),
            description=data.get('description', '')
        )

        variable_node.set_value_node(create_value_node(variable_node, data.get('type', 'unknown')))
        return variable_node
        
    except Exception as e:
        value_error(f"Error creating variable node for {name}: {e}")

async def run_terraform_command(cmd) -> tuple[int, bytes, bytes]:
    proc: Process = None
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout, stderr
    except Exception as e:
        logging.error(f"Error running terraform command '{cmd}': {e}")
        if proc and proc.returncode is None:
            # Process is still running, terminate it
            try:
                proc.terminate()
                await proc.wait()
            except Exception as cleanup_error:
                logging.error(f"Error cleaning up process: {cleanup_error}")
        return -1, b"", str(e).encode()
    finally:
        # Ensure the process is properly cleaned up
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await proc.wait()
            except Exception as cleanup_error:
                logging.error(f"Error in final cleanup: {cleanup_error}")


class VariableParser:
    def __init__(self, modules: dict[str, dict]):
        self.modules = modules
        with open(AZURERM_TO_AVM_FILE_PATH, 'r', encoding='utf-8') as f:
            self.azurerm_to_avm = json.loads(f.read())

    async def parse(self, module_name: str) -> dict:
        logging.info(f"Parsing variables for module: {module_name}")

        example_parser = ExampleParser(self.modules, self.azurerm_to_avm, module_name)
        parsed_examples = example_parser.parse(module_name)

        tf_files = [os.path.join(DATA_DIRECTORY_PATH, module_name, item) for item in os.listdir(os.path.join(DATA_DIRECTORY_PATH, module_name)) if os.path.isfile(os.path.join(DATA_DIRECTORY_PATH, module_name, item)) and item.startswith('variable') and item.endswith('.tf')]

        parsed_variables = dict()
        for tf_file in tf_files:
            try:
                with open(tf_file, "r", encoding='utf-8') as f:
                    content = VariableParser._refactor_variable_content(f.read())
                parsed_variable = hcl2.loads(content)
                if 'variable' not in parsed_variable:
                    continue
                for list_item in parsed_variable['variable']:
                    for k, v in list_item.items():
                        parsed_variables[k] = v
            except Exception as e:
                logging.error(f"Error parsing variable file: {tf_file}")
        
        try:
            root = RootNode(module_name, self.modules[module_name]['source'])
            root.decode_variables(parsed_variables)
            variables = await root.generate_context_data(parsed_examples)
        except Exception as e:
            raise_error(f"Error handling variables for module {module_name}: {e}")

        return {module_name: variables}
    
    @staticmethod
    def _refactor_variable_content(content: str) -> str:
        result = []
        lines = content.splitlines()
        idx = 0
        
        while idx < len(lines):
            if lines[idx].startswith('  validation {'):
                while not lines[idx].startswith('  }'):
                    idx += 1
                idx += 1
                continue
            
            result.append(lines[idx].rstrip())
            idx += 1
        
        return '\n'.join(result)