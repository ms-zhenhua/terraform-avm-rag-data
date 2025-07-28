
import asyncio
import csv
import io
import json
import logging
import os
import requests
import shutil
import tarfile
import time

from .utils import AVAILABLE_MODULES_URL, DATA_DIRECTORY_PATH, DOWNLOADED_TAR_PATH, run_tasks, raise_error

def _source_from_repo_url(repo_url: str) -> str:
        _, first_part, other_parts = repo_url.rsplit('/', 2)
        _, third_part,second_part = other_parts.split('-', 2)
        return f"{first_part}/{second_part}/{third_part}"

def load_modules_info() -> dict[str, dict]:  
    logging.info("Loading modules info from AVM official website...")
    response = requests.get(AVAILABLE_MODULES_URL)
    response.raise_for_status()
    csv_content = response.text

    dict_reader = csv.DictReader(io.StringIO(csv_content))
    modules_info = {}

    for row in dict_reader:
        if row['ModuleStatus'] == 'Proposed':
            continue

        module_name = row['ModuleName']
        display_name = row['ModuleDisplayName']
        repo_url = row['RepoURL']
        modules_info[module_name] = {
            "module_name": module_name,
            "display_name": display_name,
            "source": _source_from_repo_url(repo_url),
            "git_hub_url": repo_url,
            "description": f"Manages {display_name}.",
        }
        
        logging.info(f"load module info: Module Name: {module_name}")                                            
                    
    return modules_info 

def get_tarball_url(module: dict, headers: dict) -> str:
    response = requests.get('/'.join([module["git_hub_url"].replace("github.com", "api.github.com/repos"),'releases', 'latest']), headers=headers)
    if response.status_code == 200:
        release_info = response.json()
        if 'tarball_url' in release_info:
            return release_info['tarball_url']
    
    response = requests.get('/'.join([module["git_hub_url"].replace("github.com", "api.github.com/repos"),'releases']), headers=headers)
    release_info_list = response.json()
    if len(release_info_list) > 0:
        release_info = release_info_list[0]
        if 'tarball_url' in release_info:
            return release_info['tarball_url']
    
    response = requests.get('/'.join([module["git_hub_url"].replace("github.com", "api.github.com/repos"),'tags']), headers=headers)
    release_info_list = response.json()
    if len(release_info_list) > 0:
        release_info = release_info_list[0]
        if 'tarball_url' in release_info:
            return release_info['tarball_url']

    raise_error(f"Failed to get tarball URL for module {module['module_name']}. Please check the module's GitHub repository.")
 
def retrieve_the_latest_version_module(module: dict, headers: dict):
    logging.info("Downloading the latest version of module: %s", module['module_name'])
    extract_to = os.path.join(DATA_DIRECTORY_PATH, module['module_name'])
    dest_path = os.path.join(DOWNLOADED_TAR_PATH, f"{module['module_name']}.tar.gz")

    # Download the package
    try:
        if not os.path.exists(dest_path):
            tarball_url = get_tarball_url(module, headers)
            response = requests.get(tarball_url, stream=True, headers=headers)
            response.raise_for_status()
            with open(dest_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
    except Exception as e:
        raise_error(f"Failed to download module {module['module_name']}: {e}")
    
    # Extract the downloaded file
    if os.path.exists(extract_to):
        shutil.rmtree(extract_to)
    os.makedirs(extract_to, exist_ok=True)
    with tarfile.open(dest_path, "r:gz") as tar:
        # Run this command to avoid Windows length limitation: Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1
        tar.extractall(path=extract_to)
    
    # re-organize the directory structure
    if len(os.listdir(extract_to)) == 1:
        src = os.path.join(extract_to, os.listdir(extract_to)[0])
        if os.path.isdir(src):
            for entry in os.listdir(src):
                shutil.move(os.path.join(src, entry), extract_to)
            shutil.rmtree(src)

async def retrieve_the_latest_version_modules(modules_info: dict[str, dict]):
    os.environ['PYTHONUTF8'] = '1'  # Enable UTF-8 mode
    os.makedirs(DOWNLOADED_TAR_PATH, exist_ok=True)
    
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        raise_error("GITHUB_TOKEN environment variable is not set. Please set it to your GitHub token.")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
    }
    
    tasks = []
    for module in modules_info:
        tasks.append(lambda x=modules_info[module]: retrieve_the_latest_version_module(x, headers))
    await run_tasks(tasks, 10)



async def load_data() -> dict[str, dict]:
    try:
        data = load_modules_info()
    except Exception as e:
        raise_error(f"Failed to load modules info: {e}")
    
    try:
        await retrieve_the_latest_version_modules(data)
    except Exception as e:
        raise_error(f"Failed to retrieve the latest version: {e}")
    
    return data

async def main():
    from utils import DEBUG_DATA_FILE_PATH
    data = await load_data()
    with open(DEBUG_DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
