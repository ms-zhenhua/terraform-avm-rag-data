import asyncio
import os
import json
import logging
from .utils import run_tasks, raise_error

class DependencyGenerator:
    def __init__(self, modules: dict[str, dict]):
        self.modules = modules
    
    @staticmethod
    def _find_avm_dependencies(schema: str) -> list[str]:
        dependencies = []
        try:            
            module_prefix = 'module.avm-res-'.replace('-', '_')
            if schema.find(module_prefix) == -1:
                return dependencies
            
            current = 0
            while current < len(schema):
                start = schema.find(module_prefix, current)
                if start == -1:
                    break
                
                end = schema.find('.', start + len(module_prefix))
                if end == -1:
                    break
                
                module_name = schema[start + len('module.'):end]
                if module_name:
                    dependencies.append(module_name.replace('_', '-'))
                
                current = end + 1
                
        except Exception as e:
            logging.error(f"Error finding AVM dependencies in schema: {e}")
        
        return list(set(dependencies))

    def _generate_module_dependencies(self, module_name: str) -> dict:
        try:       
            result = {
                "avm_depends_on": list(),
                "required_depends_on": list(),
                "required": dict(),
                "optional": dict(),
            }

            for k, v in self.modules[module_name]['variables'].items():
                if v['required']:
                    result['required'][k] = DependencyGenerator._find_avm_dependencies(v['schema'])
                else:
                    result['optional'][k] = DependencyGenerator._find_avm_dependencies(v['schema'])

            for rv in result['required']:
                result['required'][rv] = list(set(result['required'][rv]))
                result['required_depends_on'] += result['required'][rv]
                result['avm_depends_on'] += result['required'][rv]

            for ov in result['optional']:
                result['optional'][ov] = list(set(result['optional'][ov]))
                result['avm_depends_on'] += result['optional'][ov]

            result['required_depends_on'] = list(set(result['required_depends_on']))
            result['avm_depends_on'] = list(set(result['avm_depends_on']))
                
            return {module_name: result}
                
        except Exception as e:
            raise_error(f"Error generating module dependencies: {e}")
    
    def _remove_exceptional_dependencies(self, module_name: str) -> dict:
        dependencies = self.modules[module_name]['denpends_on']
            
        if module_name in dependencies["avm_depends_on"]:
            dependencies["avm_depends_on"].remove(module_name)
        if module_name in dependencies["required_depends_on"]:
            dependencies["required_depends_on"].remove(module_name)
        for rv in dependencies["required"]:
            if module_name in dependencies["required"][rv]:
                dependencies["required"][rv].remove(module_name)
        for ov in dependencies["optional"]:
            if module_name in dependencies["optional"][ov]:
                dependencies["optional"][ov].remove(module_name)
                
        if module_name == "avm-res-resources-resourcegroup":
            dependencies["avm_depends_on"] = []
            dependencies["required_depends_on"] = []
            for rv in dependencies["required"]:
                dependencies["required"][rv] = []
            for ov in dependencies["optional"]:
                dependencies["optional"][ov] = []


        return {module_name: dependencies}
            

    def _generate_dependency_priorities(self):
        try:            
            visited = set()
            stack = set()
            relations = {}

            def visit(node: str):
                if node in stack:
                    raise_error(f"Cycle detected in AVM dependencies: {' -> '.join(stack)}")
                if node in visited:
                    return
                
                relations[node] = set()
                visited.add(node)
                stack.add(node)

                for dep in self.modules.get(node, {}).get('denpends_on', {}).get("avm_depends_on", []):
                    relations[node].add(dep)
                    visit(dep)

                stack.remove(node)

            for module_name in self.modules:
                visit(module_name)
            
            queue = list()
            for k, v in relations.items():
                if len(v) == 0:
                    queue.append(k)
            
            priority = 0
            while queue:
                current = queue.pop(0)
                if current not in self.modules:
                    continue
                
                self.modules[current]['priority'] = priority
                priority += 1
                
                for k in relations:
                    if current in relations[k]:
                        relations[k].remove(current)
                        if len(relations[k]) == 0:
                            queue.append(k)
            
            for _,v in relations.items():
                if len(v) > 0:
                    raise_error(f"Cycle detected in AVM dependencies: {v}")
            
            for module_name in self.modules:
                if 'priority' not in self.modules[module_name]:
                    raise_error(f"Module {module_name} does not have a priority assigned.")

            logging.info("No cycles detected in AVM dependencies.")
        except Exception as e:
            raise_error(f"Error checking cycles in AVM dependencies: {e}")

    async def generate(self):
        tasks = []
        for module_name in self.modules:
            tasks.append(lambda x=module_name: self._generate_module_dependencies(x))
        
        results = await run_tasks(tasks, 10)
        for result in results:
            for k, v in result.items():
                self.modules[k]['denpends_on'] = v

        tasks = []
        for module_name in self.modules:
            tasks.append(lambda x=module_name: self._remove_exceptional_dependencies(x))
        
        results = await run_tasks(tasks, 10)
        for result in results:
            for k, v in result.items():
                self.modules[k]['denpends_on'] = v
        

        self._generate_dependency_priorities()

async def generate(modules: dict[str, dict]):
    dependency_generator = DependencyGenerator(modules)
    await dependency_generator.generate()

async def main():
    from utils import DATA_FILE_PATH
    with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    await generate(data)

    with open(DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())